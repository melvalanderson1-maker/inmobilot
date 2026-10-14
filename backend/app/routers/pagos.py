from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from decimal import Decimal
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.database import get_db
from app.deps import require_permiso
from app.models import models as m
from app.schemas import schemas as s
from app.services import separacion_service as sep_svc
from app.services import venta_service as venta_svc
from app.sockets import notificar_pago, notificar_pago_registrado

router = APIRouter(prefix="/pagos", tags=["pagos"])


def _conflicto(detalle: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detalle)


def _cargar_pago(db: Session, id_pago: int, usuario: m.Usuario) -> m.Pago:
    pago = (
        db.query(m.Pago)
        .join(m.Contrato, m.Contrato.id == m.Pago.id_contrato)
        .options(joinedload(m.Pago.contrato), joinedload(m.Pago.registrador), joinedload(m.Pago.cuota))
        .filter(m.Pago.id == id_pago, m.Contrato.id_empresa == usuario.id_empresa)
        .first()
    )
    if not pago:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pago no encontrado")
    venta_svc.validar_acceso_proyecto(db, usuario, pago.contrato.id_proyecto)
    return pago


def _a_fila(p: m.Pago) -> s.PagoColaOut:
    c = p.contrato
    titular = next((vc.cliente for vc in c.clientes_rel if vc.rol == m.RolClienteContratoEnum.titular), None)
    if titular is None and c.clientes_rel:
        titular = c.clientes_rel[0].cliente
    nombre, documento = "", ""
    if titular:
        nombre = (titular.razon_social if titular.tipo_persona == "juridica" else f"{titular.nombres} {titular.apellidos}") or ""
        documento = (titular.ruc if titular.tipo_persona == "juridica" else titular.numero_documento) or ""
    return s.PagoColaOut(
        id=p.id, id_contrato=c.id, id_proyecto=c.id_proyecto, numero_contrato=c.numero_contrato,
        lote_codigo=c.lote.codigo if c.lote else None,
        cliente_nombre=nombre, cliente_documento=documento,
        numero_cuota=p.cuota.numero_cuota if p.cuota else None,
        monto=p.monto, fecha_pago=p.fecha_pago, metodo_pago=p.metodo_pago,
        numero_operacion=p.numero_operacion, comprobante_url=p.comprobante_url,
        estado=p.estado, motivo_rechazo=p.motivo_rechazo,
        factura_tipo=p.factura_tipo, factura_numero=p.factura_numero, factura_url=p.factura_url,
        registrado_por_nombre=p.registrador.nombre if p.registrador else None,
        created_at=p.created_at,
    )


async def _emitir(pago: m.Pago, contrato: m.Contrato, notifs: list):
    await notificar_pago(
        "pago:actualizado",
        {"id": pago.id, "id_contrato": contrato.id, "estado": pago.estado},
        contrato.id_proyecto,
        sep_svc.notificaciones_a_dict(notifs),
    )


# ---------------------------------------------------------------- lectura --

@router.get("", response_model=list[s.PagoColaOut])
def listar_pagos(
    id_proyecto: int,
    estado: Optional[str] = None,
    usuario: m.Usuario = Depends(require_permiso("ver_pagos")),
    db: Session = Depends(get_db),
):
    venta_svc.validar_acceso_proyecto(db, usuario, id_proyecto)
    query = (
        db.query(m.Pago)
        .join(m.Contrato, m.Contrato.id == m.Pago.id_contrato)
        .options(
            joinedload(m.Pago.contrato).joinedload(m.Contrato.lote),
            joinedload(m.Pago.contrato).selectinload(m.Contrato.clientes_rel).joinedload(m.ContratoCliente.cliente),
            joinedload(m.Pago.cuota),
            joinedload(m.Pago.registrador),
        )
        .filter(m.Contrato.id_empresa == usuario.id_empresa, m.Contrato.id_proyecto == id_proyecto)
    )
    if estado:
        query = query.filter(m.Pago.estado == estado)
    return [_a_fila(p) for p in query.order_by(m.Pago.created_at.desc()).limit(300).all()]


# ------------------------------------------------------------------- caja --

@router.post("/{id_pago}/validar", response_model=s.PagoOut)
async def validar_pago(
    id_pago: int,
    usuario: m.Usuario = Depends(require_permiso("validar_pago")),
    db: Session = Depends(get_db),
):
    pago = _cargar_pago(db, id_pago, usuario)
    if pago.estado != "pendiente_caja":
        raise _conflicto("Este pago no está pendiente de validación de Caja")
    contrato = pago.contrato

    pago.estado = "pendiente_facturacion"
    pago.validado_por = usuario.id
    pago.fecha_validacion = sep_svc.ahora_utc()
    pago.motivo_rechazo = None

    destinatarios = sep_svc.unicos(
        sep_svc.usuarios_por_roles(db, contrato.id_empresa, contrato.id_proyecto, ["facturacion", "admin"])
        + [pago.registrador],
        excluir_id=usuario.id,
    )
    notifs = sep_svc.crear_notificaciones(
        db, contrato.id_empresa, destinatarios,
        "pago_pendiente_facturacion",
        "Pago validado: emitir comprobante",
        f"Caja validó S/ {pago.monto:,.2f} del contrato {contrato.numero_contrato}. Falta emitir el comprobante.",
        {"id_pago": pago.id, "id_contrato": contrato.id, "id_proyecto": contrato.id_proyecto, "estado": "pendiente_facturacion"},
    )
    db.commit()
    await _emitir(pago, contrato, notifs)
    return pago


@router.post("/{id_pago}/rechazar", response_model=s.PagoOut)
async def rechazar_pago(
    id_pago: int,
    payload: s.PagoRechazo,
    usuario: m.Usuario = Depends(require_permiso("validar_pago")),
    db: Session = Depends(get_db),
):
    pago = _cargar_pago(db, id_pago, usuario)
    if pago.estado != "pendiente_caja":
        raise _conflicto("Este pago no está pendiente de validación de Caja")
    motivo = payload.motivo.strip()
    if not motivo:
        raise HTTPException(status_code=422, detail="Debes indicar el motivo del rechazo")
    contrato = pago.contrato

    pago.estado = "rechazado"
    pago.motivo_rechazo = motivo
    pago.validado_por = usuario.id
    pago.fecha_validacion = sep_svc.ahora_utc()

    notifs = sep_svc.crear_notificaciones(
        db, contrato.id_empresa, sep_svc.unicos([pago.registrador], excluir_id=usuario.id),
        "pago_rechazado",
        "Pago rechazado por Caja",
        f"Contrato {contrato.numero_contrato}: {motivo}",
        {"id_pago": pago.id, "id_contrato": contrato.id, "id_proyecto": contrato.id_proyecto, "estado": "rechazado"},
    )
    db.commit()
    await _emitir(pago, contrato, notifs)
    return pago


# ------------------------------------------------------------ facturación --

@router.post("/{id_pago}/comprobante", response_model=s.PagoOut)
async def subir_comprobante_pago(
    id_pago: int,
    payload: s.PagoComprobanteIn,
    usuario: m.Usuario = Depends(require_permiso("facturar_pago")),
    db: Session = Depends(get_db),
):
    """Con el comprobante el pago queda validado y recién ahí se aplica a la cuota."""
    pago = _cargar_pago(db, id_pago, usuario)
    if pago.estado != "pendiente_facturacion":
        raise _conflicto("Este pago no está pendiente de comprobante")
    tipo = payload.tipo.strip().lower()
    if tipo not in ("boleta", "factura", "recibo"):
        raise HTTPException(status_code=422, detail="El tipo debe ser boleta, factura o recibo")
    numero = payload.numero.strip()
    if not numero:
        raise HTTPException(status_code=422, detail="El número de comprobante es obligatorio")
    contrato = pago.contrato

    pago.factura_tipo = tipo
    pago.factura_numero = numero
    pago.factura_url = payload.archivo_url
    pago.facturado_por = usuario.id
    pago.fecha_facturacion = sep_svc.ahora_utc()
    pago.estado = "validado"

    # Recién ahora el pago cuenta en la cuota
    if pago.id_cuota:
        cuota = db.query(m.CronogramaPago).filter(m.CronogramaPago.id == pago.id_cuota).first()
        if cuota:
            cuota.monto_pagado = (cuota.monto_pagado or Decimal("0")) + pago.monto
            if cuota.monto_pagado >= cuota.monto_cuota:
                cuota.estado = m.EstadoCuotaEnum.pagada
                cuota.fecha_pago_real = pago.fecha_pago
            else:
                cuota.estado = m.EstadoCuotaEnum.parcial

    destinatarios = sep_svc.unicos(
        sep_svc.usuarios_por_roles(db, contrato.id_empresa, contrato.id_proyecto, ["cobranza", "admin"])
        + [pago.registrador],
        excluir_id=usuario.id,
    )
    notifs = sep_svc.crear_notificaciones(
        db, contrato.id_empresa, destinatarios,
        "pago_aplicado",
        "Pago aplicado",
        f"Contrato {contrato.numero_contrato}: {tipo} {numero} por S/ {pago.monto:,.2f}. El pago ya se aplicó a la cuota.",
        {"id_pago": pago.id, "id_contrato": contrato.id, "id_proyecto": contrato.id_proyecto, "estado": "validado"},
    )
    db.commit()

    await _emitir(pago, contrato, notifs)
    # Refresca los cronogramas abiertos en Contratos y Cobranza
    await notificar_pago_registrado(contrato.id, contrato.id_proyecto, contrato.id_empresa)
    return pago