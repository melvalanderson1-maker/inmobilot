from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.database import get_db
from app.deps import require_permiso
from app.models import models as m
from app.schemas import schemas as s
from app.services import venta_service as venta_svc
from app.services.separacion_service import hoy_peru
from app.sockets import notificar_pago_registrado, notificar_venta

router = APIRouter(prefix="/cobranza", tags=["cobranza"])

Q2 = Decimal("0.01")
CERO = Decimal("0")


def _total_pagado(db: Session, id_contrato: int) -> Decimal:
    total = db.query(func.coalesce(func.sum(m.Pago.monto), 0)).filter(m.Pago.id_contrato == id_contrato).scalar()
    return Decimal(str(total))


def _cargar_contrato(db: Session, id_contrato: int, usuario: m.Usuario) -> m.Contrato:
    contrato = (
        db.query(m.Contrato)
        .options(selectinload(m.Contrato.cronograma))
        .filter(m.Contrato.id == id_contrato, m.Contrato.id_empresa == usuario.id_empresa)
        .first()
    )
    if not contrato:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contrato no encontrado")
    venta_svc.validar_acceso_proyecto(db, usuario, contrato.id_proyecto)
    return contrato


def _conflicto(detalle: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detalle)


# ---------------------------------------------------------------- resumen --

@router.get("/resumen", response_model=list[s.CobranzaFilaOut])
def resumen_cobranza(
    id_proyecto: int,
    usuario: m.Usuario = Depends(require_permiso("ver_cobranza")),
    db: Session = Depends(get_db),
):
    venta_svc.validar_acceso_proyecto(db, usuario, id_proyecto)
    hoy = hoy_peru()

    contratos = (
        db.query(m.Contrato)
        .options(
            joinedload(m.Contrato.lote),
            selectinload(m.Contrato.clientes_rel).joinedload(m.ContratoCliente.cliente),
            selectinload(m.Contrato.cronograma),
        )
        .filter(
            m.Contrato.id_empresa == usuario.id_empresa,
            m.Contrato.id_proyecto == id_proyecto,
            m.Contrato.forma_pago == m.FormaPagoEnum.credito,
        )
        .all()
    )
    ids = [c.id for c in contratos]
    pagado: dict = {}
    ventas: dict = {}
    if ids:
        pagado = dict(
            db.query(m.Pago.id_contrato, func.sum(m.Pago.monto))
            .filter(m.Pago.id_contrato.in_(ids))
            .group_by(m.Pago.id_contrato)
            .all()
        )
        ventas = dict(db.query(m.Venta.id_contrato, m.Venta.id).filter(m.Venta.id_contrato.in_(ids)).all())

    filas: list[s.CobranzaFilaOut] = []
    for c in contratos:
        cuotas = sorted((q for q in c.cronograma if q.requiere_pago), key=lambda q: q.numero_cuota)
        pendientes = [q for q in cuotas if q.estado != m.EstadoCuotaEnum.pagada]
        vencidas = [q for q in pendientes if q.fecha_pago_programada < hoy]
        monto_vencido = sum((q.monto_cuota - (q.monto_pagado or CERO) for q in vencidas), CERO)
        proxima = pendientes[0] if pendientes else None

        titular = next((vc.cliente for vc in c.clientes_rel if vc.rol == m.RolClienteContratoEnum.titular), None)
        if titular is None and c.clientes_rel:
            titular = c.clientes_rel[0].cliente
        if titular is None:
            continue
        nombre = titular.razon_social if titular.tipo_persona == "juridica" else f"{titular.nombres} {titular.apellidos}"
        documento = titular.ruc if titular.tipo_persona == "juridica" else titular.numero_documento

        total_pagado = Decimal(str(pagado.get(c.id, 0)))
        filas.append(s.CobranzaFilaOut(
            id_contrato=c.id,
            numero_contrato=c.numero_contrato,
            id_venta=ventas.get(c.id),
            lote_codigo=c.lote.codigo if c.lote else None,
            cliente_nombre=nombre or "",
            cliente_documento=documento or "",
            cliente_telefono=titular.telefono,
            precio_total=c.precio_total,
            inicial_abonado=c.inicial_abonado or CERO,
            total_pagado=total_pagado,
            saldo_pendiente=max(c.saldo_financiado - total_pagado, CERO),
            monto_vencido=monto_vencido,
            cuotas_total=len(cuotas),
            cuotas_pagadas=len(cuotas) - len(pendientes),
            cuotas_vencidas=len(vencidas),
            proxima_fecha=proxima.fecha_pago_programada if proxima else None,
            proxima_monto=(proxima.monto_cuota - (proxima.monto_pagado or CERO)) if proxima else None,
            dias_atraso=(hoy - vencidas[0].fecha_pago_programada).days if vencidas else 0,
            estado=c.estado.value,
        ))

    filas.sort(key=lambda f: -f.dias_atraso)
    return filas


# ------------------------------------------------------ recálculo de cuotas --

@router.post("/contratos/{id_contrato}/recalcular-cuotas")
async def recalcular_cuotas(
    id_contrato: int,
    usuario: m.Usuario = Depends(require_permiso("gestionar_cobranza")),
    db: Session = Depends(get_db),
):
    """Reparte el saldo real entre las cuotas pendientes (tras un pago adelantado o de más)."""
    contrato = _cargar_contrato(db, id_contrato, usuario)
    if contrato.forma_pago != m.FormaPagoEnum.credito:
        raise _conflicto("Solo los contratos a crédito tienen cuotas")
    if contrato.estado in (m.EstadoContratoEnum.cancelado, m.EstadoContratoEnum.anulado):
        raise _conflicto("El contrato ya está cerrado")
    if contrato.tiene_interes:
        raise HTTPException(status_code=422, detail="Los contratos con interés aún no se recalculan automáticamente")

    pendientes = sorted(
        (q for q in contrato.cronograma if q.requiere_pago and q.estado != m.EstadoCuotaEnum.pagada),
        key=lambda q: q.numero_cuota,
    )
    if not pendientes:
        raise _conflicto("No hay cuotas pendientes que recalcular")

    saldo = contrato.saldo_financiado - _total_pagado(db, contrato.id)
    if saldo <= 0:
        raise _conflicto("El saldo ya está cubierto: usa 'Cancelar contrato'")

    n = len(pendientes)
    base = (saldo / n).quantize(Q2, rounding=ROUND_HALF_UP)
    restante = saldo
    for i, q in enumerate(pendientes, start=1):
        parte = base if i < n else restante
        restante -= parte
        ya_pagado = q.monto_pagado or CERO
        q.amortizacion = parte
        q.monto_cuota = ya_pagado + parte
        q.capital = restante
        q.estado = m.EstadoCuotaEnum.parcial if ya_pagado > 0 else m.EstadoCuotaEnum.pendiente
    db.commit()

    await notificar_pago_registrado(contrato.id, contrato.id_proyecto, usuario.id_empresa)
    return {"mensaje": f"{n} cuota(s) recalculadas con un saldo de S/ {saldo:,.2f}"}


# ---------------------------------------------------------------- cancelar --

@router.post("/contratos/{id_contrato}/cancelar")
async def cancelar_contrato(
    id_contrato: int,
    usuario: m.Usuario = Depends(require_permiso("gestionar_cobranza")),
    db: Session = Depends(get_db),
):
    """Cierra el contrato cuando el cliente ya pagó todo el saldo."""
    contrato = _cargar_contrato(db, id_contrato, usuario)
    if contrato.estado in (m.EstadoContratoEnum.cancelado, m.EstadoContratoEnum.anulado):
        raise _conflicto("El contrato ya está cerrado")

    saldo = contrato.saldo_financiado - _total_pagado(db, contrato.id)
    if saldo > 0:
        raise _conflicto(f"Aún falta cobrar S/ {saldo:,.2f}. Registra el pago antes de cancelar el contrato")

    hoy = hoy_peru()
    for q in contrato.cronograma:
        if q.requiere_pago and q.estado != m.EstadoCuotaEnum.pagada:
            q.monto_cuota = q.monto_pagado or CERO
            q.estado = m.EstadoCuotaEnum.pagada
            q.fecha_pago_real = hoy
            q.observacion = "Cerrada por cancelación del contrato"
    contrato.estado = m.EstadoContratoEnum.cancelado
    db.commit()

    await notificar_pago_registrado(contrato.id, contrato.id_proyecto, usuario.id_empresa)
    return {"mensaje": "Contrato cancelado"}


# ------------------------------------------------------------- finalizar --

@router.post("/ventas/{id_venta}/finalizar", response_model=s.VentaOut)
async def finalizar_venta(
    id_venta: int,
    usuario: m.Usuario = Depends(require_permiso("gestionar_cobranza")),
    db: Session = Depends(get_db),
):
    """Según el PDF: solo con el depósito subido al sistema y el contrato cancelado."""
    venta = venta_svc.cargar_venta(db, id_venta, usuario)
    if venta.estado == m.EstadoVentaEnum.finalizada:
        raise _conflicto("La venta ya está finalizada")
    if venta.estado in (m.EstadoVentaEnum.cancelada, m.EstadoVentaEnum.anulada):
        raise _conflicto("La venta está anulada o cancelada")
    if not venta.id_contrato:
        raise _conflicto("La venta aún no tiene contrato registrado")

    contrato = db.query(m.Contrato).filter(m.Contrato.id == venta.id_contrato).first()
    if not contrato or contrato.estado != m.EstadoContratoEnum.cancelado:
        raise _conflicto("El contrato debe estar cancelado (pagado en su totalidad) para finalizar la venta")

    tiene_deposito = (
        db.query(m.Pago.id)
        .filter(m.Pago.id_contrato == contrato.id, m.Pago.comprobante_url.isnot(None))
        .first()
        is not None
    )
    if not tiene_deposito and venta.id_separacion:
        sep = db.query(m.Separacion).filter(m.Separacion.id == venta.id_separacion).first()
        tiene_deposito = bool(sep and sep.voucher_url)
    if not tiene_deposito:
        raise _conflicto("Falta subir el depósito (voucher) al sistema")

    venta.estado = m.EstadoVentaEnum.finalizada
    db.commit()

    await notificar_venta(
        "venta:actualizada",
        {"id": venta.id, "id_lote": venta.id_lote, "estado": "finalizada"},
        id_proyecto=venta.id_proyecto,
    )
    await notificar_pago_registrado(contrato.id, contrato.id_proyecto, usuario.id_empresa)
    return s.VentaOut.desde_venta(venta_svc.cargar_venta(db, id_venta, usuario))