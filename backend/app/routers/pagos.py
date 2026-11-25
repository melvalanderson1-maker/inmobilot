from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from decimal import Decimal
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload, object_session, selectinload

from app.core.database import get_db
from app.deps import require_permiso
from app.models import models as m
from app.schemas import schemas as s
from app.services import separacion_service as sep_svc
from app.services import venta_service as venta_svc
from app.services import amortizacion_service as amort_svc
from app.services import auditoria as aud
from app.sockets import notificar_pago, notificar_pago_registrado

from datetime import date, datetime


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


def _n_pago(p: m.Pago, numero: Optional[int]) -> Optional[int]:
    """N° de cuota como lo ve el cliente. En crédito anual el N° interno es el del mes (13, 25...): se muestra 1, 2, 3..."""
    if numero is None:
        return None
    contrato = p.contrato
    db = object_session(p)
    if contrato is None or db is None or contrato.frecuencia_cuota != "anual":
        return numero
    total = (
        db.query(func.count(m.CronogramaPago.id))
        .filter(
            m.CronogramaPago.id_contrato == contrato.id,
            m.CronogramaPago.requiere_pago.is_(True),
            m.CronogramaPago.numero_cuota <= numero,
        )
        .scalar()
    )
    return total or numero


def _rango_cuotas(p: m.Pago) -> str:
    desde = _n_pago(p, p.cuota_desde)
    hasta = _n_pago(p, p.cuota_hasta or p.cuota_desde)
    return f"Cuotas {desde} a {hasta}" if hasta != desde else f"Cuota {desde}"


def _concepto(p: m.Pago) -> str:
    """Qué es este pago, en palabras que el usuario entienda."""
    if p.tipo == "inicial":
        return "Inicial"
    if p.tipo == "contado":
        return "Pago al contado"
    if p.tipo == "amortizacion":
        base = (
            "Amortización a capital (baja la cuota)"
            if p.modalidad == "amortizar_cuota"
            else "Amortización a capital (reduce el plazo)"
        )
        return f"{_rango_cuotas(p)} + {base}" if p.cuota_desde else base

    if p.tipo == "cancelacion":
        return f"{_rango_cuotas(p)} + Cancelación de crédito" if p.cuota_desde else "Cancelación de crédito"
    
    if p.tipo in ("cuota", "cuotas") and p.cuota_desde:
        return _rango_cuotas(p)
    if p.cuota:
        return f"Cuota {_n_pago(p, p.cuota.numero_cuota)}"
    return "Pago a cuenta"


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
        numero_cuota=_n_pago(p, p.cuota.numero_cuota) if p.cuota else None,
        monto=p.monto, fecha_pago=p.fecha_pago, metodo_pago=p.metodo_pago,
        numero_operacion=p.numero_operacion, comprobante_url=p.comprobante_url,
        estado=p.estado, motivo_rechazo=p.motivo_rechazo,
        factura_tipo=p.factura_tipo, factura_numero=p.factura_numero, factura_url=p.factura_url,
        registrado_por_nombre=p.registrador.nombre if p.registrador else None,
        validado_por_nombre=p.validador.nombre if p.validador else None,
        concepto=_concepto(p),
        detalle=p.observacion,
        forma_pago=c.forma_pago.value if c.forma_pago else None,
        created_at=p.created_at,
    )

async def _emitir(pago: m.Pago, contrato: m.Contrato, notifs: list):
    await notificar_pago(
        "pago:actualizado",
        {
            "id": pago.id,
            "id_contrato": contrato.id,
            "estado": pago.estado,
            "concepto": _concepto(pago),
            "numero_contrato": contrato.numero_contrato,
        },
        contrato.id_proyecto,
        sep_svc.notificaciones_a_dict(notifs),
        contrato.id_empresa,
    )
    # Tiempo real: cronogramas y pagos abiertos (Contratos, Cobranza, Venta) se refrescan al instante
    await notificar_pago_registrado(contrato.id, contrato.id_proyecto, contrato.id_empresa)


# ---------------------------------------------------------------- lectura --

def _filas_separaciones(db: Session, usuario: m.Usuario, id_proyecto: int, estado: Optional[str]) -> list[s.PagoColaOut]:
    """Las separaciones también pasan por Caja y Facturación: se muestran en la misma cola."""
    mapa = {
        "pendiente_caja": "pendiente_caja", "pendiente_facturacion": "pendiente_facturacion",
        "rechazada": "rechazado", "devuelta": "anulado", "anulada": "anulado",
    }
    q = (
        db.query(m.Separacion)
        .options(
            joinedload(m.Separacion.cliente),
            joinedload(m.Separacion.lote),
            joinedload(m.Separacion.ejecutivo),
            joinedload(m.Separacion.validador),
            selectinload(m.Separacion.comprobantes),
        )
        .filter(m.Separacion.id_empresa == usuario.id_empresa, m.Separacion.id_proyecto == id_proyecto)
    )
    if usuario.rol.clave == "ejecutivo_ventas":
        q = q.filter(m.Separacion.id_ejecutivo == usuario.id)
    filas = []
    for x in q.order_by(m.Separacion.created_at.desc()).limit(300).all():
        est = x.estado.value if hasattr(x.estado, "value") else str(x.estado)
        est_cola = mapa.get(est, "validado")
        # Convertida sin comprobante: vuelve a la cola de Facturación para que lo suba
        if est == "convertida" and not x.comprobantes:
            est_cola = "pendiente_facturacion"
        if estado and est_cola != estado:
            continue
        c = x.cliente
        nombre, documento = "", ""
        if c:
            nombre = (c.razon_social if c.tipo_persona == "juridica" else f"{c.nombres} {c.apellidos}") or ""
            documento = (c.ruc if c.tipo_persona == "juridica" else c.numero_documento) or ""
        comp = x.comprobantes[-1] if x.comprobantes else None
        filas.append(s.PagoColaOut(
            id=x.id, id_contrato=0, id_proyecto=x.id_proyecto,
            numero_contrato=f"Separación #{x.id}",
            lote_codigo=x.lote.codigo if x.lote else None,
            cliente_nombre=nombre, cliente_documento=documento,
            numero_cuota=None,
            monto=x.importe, fecha_pago=x.fecha_inicio, metodo_pago=x.medio_pago,
            numero_operacion=x.voucher_numero, comprobante_url=x.voucher_url,
            estado=est_cola, motivo_rechazo=x.motivo_rechazo if est_cola == "rechazado" else None,
            factura_tipo=comp.tipo if comp else None,
            factura_numero=comp.numero if comp else None,
            factura_url=comp.archivo_url if comp else None,
            registrado_por_nombre=x.ejecutivo.nombre if x.ejecutivo else None,
            validado_por_nombre=x.validador.nombre if x.validador else None,
            concepto="Separación de lote", detalle=x.notas, forma_pago=None,
            created_at=x.created_at,
            origen="separacion", id_separacion=x.id,
            convertida=(est == "convertida"),
        ))
    return filas



def _filas_devoluciones(db: Session, usuario: m.Usuario, id_proyecto: int, estado: Optional[str]) -> list[s.PagoColaOut]:
    """Las devoluciones de separación pasan por Caja (voucher) y Facturación (nota de crédito)."""
    mapa = {"pendiente_caja": "pendiente_caja", "pendiente_facturacion": "pendiente_facturacion", "completada": "validado"}
    q = (
        db.query(m.Devolucion)
        .join(m.Separacion, m.Separacion.id == m.Devolucion.id_separacion)
        .options(
            joinedload(m.Devolucion.separacion).joinedload(m.Separacion.cliente),
            joinedload(m.Devolucion.separacion).joinedload(m.Separacion.lote),
            joinedload(m.Devolucion.separacion).joinedload(m.Separacion.ejecutivo),
            joinedload(m.Devolucion.separacion).selectinload(m.Separacion.comprobantes),
        )
        .filter(
            m.Separacion.id_empresa == usuario.id_empresa,
            m.Separacion.id_proyecto == id_proyecto,
            m.Devolucion.estado.in_(list(mapa)),
        )
    )
    if usuario.rol.clave == "ejecutivo_ventas":
        q = q.filter(m.Separacion.id_ejecutivo == usuario.id)
    filas = []
    for d in q.order_by(m.Devolucion.created_at.desc()).limit(300).all():
        est_cola = mapa[d.estado]
        if estado and est_cola != estado:
            continue
        sep = d.separacion
        comp_sep = sep.comprobantes[-1] if sep.comprobantes else None
        c = sep.cliente
        nombre, documento = "", ""
        if c:
            nombre = (c.razon_social if c.tipo_persona == "juridica" else f"{c.nombres} {c.apellidos}") or ""
            documento = (c.ruc if c.tipo_persona == "juridica" else c.numero_documento) or ""
        filas.append(s.PagoColaOut(
            id=d.id, id_contrato=0, id_proyecto=sep.id_proyecto,
            numero_contrato=f"Separación #{sep.id}",
            lote_codigo=sep.lote.codigo if sep.lote else None,
            cliente_nombre=nombre, cliente_documento=documento,
            monto=d.monto, fecha_pago=d.fecha_solicitud or date.today(),
            metodo_pago=d.metodo_pago, numero_operacion=d.numero_operacion,
            comprobante_url=d.voucher_url,
            estado=est_cola, motivo_rechazo=None,
            factura_tipo="nota_credito" if d.nota_credito_numero else None,
            factura_numero=d.nota_credito_numero, factura_url=d.nota_credito_url,
            registrado_por_nombre=sep.ejecutivo.nombre if sep.ejecutivo else None,
            concepto="Devolución de separación", detalle=d.sustento, forma_pago=None,
            created_at=d.created_at or datetime.utcnow(),
            origen="devolucion", id_separacion=sep.id,
            sep_comprobante_tipo=comp_sep.tipo if comp_sep else None,
            sep_comprobante_numero=comp_sep.numero if comp_sep else None,
            sep_comprobante_url=comp_sep.archivo_url if comp_sep else None,
        ))
    return filas


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
            joinedload(m.Pago.validador),
        )
        .filter(m.Contrato.id_empresa == usuario.id_empresa, m.Contrato.id_proyecto == id_proyecto)
    )
    if estado:
        query = query.filter(m.Pago.estado == estado)
    filas = [_a_fila(p) for p in query.order_by(m.Pago.created_at.desc()).limit(300).all()]
    filas += _filas_separaciones(db, usuario, id_proyecto, estado)
    filas += _filas_devoluciones(db, usuario, id_proyecto, estado)
    
    filas.sort(key=lambda f: f.created_at.replace(tzinfo=None) if f.created_at else datetime.min, reverse=True)
    return filas


# ----------------------------------------------------------------- editar --

ROLES_EDITAR_PAGO = ("admin", "gerencia", "supervisor", "cobranza", "contabilidad", "caja")
ESTADOS_EDITABLES_PAGO = ("pendiente_caja", "pendiente_facturacion", "rechazado")
# Si cambia alguno de estos, Caja debe volver a validar
CAMPOS_QUE_REVALIDAN = {"monto", "fecha_pago", "metodo_pago", "numero_operacion", "comprobante_url"}


@router.patch("/{id_pago}", response_model=s.PagoOut)
async def editar_pago(
    id_pago: int,
    payload: s.PagoUpdate,
    usuario: m.Usuario = Depends(require_permiso("ver_pagos")),
    db: Session = Depends(get_db),
):
    pago = _cargar_pago(db, id_pago, usuario)
    es_responsable = pago.registrado_por == usuario.id or pago.contrato.id_usuario_registro == usuario.id
    if usuario.rol.clave not in ROLES_EDITAR_PAGO and not es_responsable:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permiso para editar pagos")
    if pago.estado not in ESTADOS_EDITABLES_PAGO:
        raise _conflicto("Este pago ya fue aplicado a las cuotas y no se puede editar")

    datos = payload.model_dump(exclude_unset=True)
    # Obligatorios: no se pueden dejar vacíos
    for campo in ("monto", "fecha_pago", "comprobante_url"):
        if campo in datos and datos[campo] is None:
            datos.pop(campo)
    if "numero_operacion" in datos and datos["numero_operacion"] is not None:
        datos["numero_operacion"] = datos["numero_operacion"].strip() or None

    if "monto" in datos and pago.tipo in ("amortizacion", "cancelacion"):
        raise HTTPException(
            status_code=422,
            detail="El monto de una amortización o cancelación lo calcula el sistema y no se puede editar",
        )

    cambios = aud.diferencias({c: getattr(pago, c) for c in datos}, datos)
    if not cambios:
        if pago.estado == "rechazado":
            raise HTTPException(
                status_code=422,
                detail="Corrige lo observado (comprobante, monto, fecha u operación) antes de reenviar",
            )
        return pago

    accion = "corregir_rechazo" if pago.estado == "rechazado" else "editar"
    aud.registrar(
        db, usuario, "pago", pago.id, accion,
        {"id_contrato": pago.id_contrato, "motivo_rechazo_previo": pago.motivo_rechazo, **cambios},
    )
    for campo, valor in datos.items():
        setattr(pago, campo, valor)

    contrato = pago.contrato
    notifs = []
    if pago.estado != "pendiente_caja" and (pago.estado == "rechazado" or CAMPOS_QUE_REVALIDAN & cambios.keys()):
        pago.estado = "pendiente_caja"
        pago.motivo_rechazo = None
        pago.validado_por = None
        pago.fecha_validacion = None
        destinatarios = sep_svc.usuarios_por_roles(
            db, contrato.id_empresa, contrato.id_proyecto, ["caja", "admin"], excluir_id=usuario.id
        )
        notifs = sep_svc.crear_notificaciones(
            db, contrato.id_empresa, destinatarios,
            "pago_pendiente_caja",
            f"{_concepto(pago)} corregido: validar de nuevo",
            f"{usuario.nombre} corrigió {_concepto(pago)} de S/ {pago.monto:,.2f} del contrato {contrato.numero_contrato}.",
            {"id_pago": pago.id, "id_contrato": contrato.id, "id_proyecto": contrato.id_proyecto, "estado": "pendiente_caja"},
        )

    db.commit()
    await _emitir(pago, contrato, notifs)
    return pago


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
    aud.registrar(db, usuario, "pago", pago.id, "validar_caja", {"id_contrato": contrato.id, "monto": str(pago.monto)})

    destinatarios = sep_svc.unicos(
        sep_svc.usuarios_por_roles(db, contrato.id_empresa, contrato.id_proyecto, ["facturacion", "admin"])
        + [pago.registrador],
        excluir_id=usuario.id,
    )
    notifs = sep_svc.crear_notificaciones(
        db, contrato.id_empresa, destinatarios,
        "pago_pendiente_facturacion",
        f"{_concepto(pago)} validada: emitir comprobante",
        f"Caja validó {_concepto(pago)} de S/ {pago.monto:,.2f} del contrato {contrato.numero_contrato}. Falta emitir el comprobante.",
        {"id_pago": pago.id, "id_contrato": contrato.id, "id_proyecto": contrato.id_proyecto, "estado": "pendiente_facturacion"},
    )
    db.commit()
    await _emitir(pago, contrato, notifs)
    return pago


async def _rechazar_comun(
    db: Session, usuario: m.Usuario, pago: m.Pago, motivo_raw: str,
    etapa: str, estado_requerido: str, mensaje_estado: str,
):
    """Rechazo desde Caja o Facturación: guarda motivo, audita y avisa a quien registró el pago y al ejecutivo del contrato."""
    if pago.estado != estado_requerido:
        raise _conflicto(mensaje_estado)
    motivo = (motivo_raw or "").strip()
    if not motivo:
        raise HTTPException(status_code=422, detail="Debes indicar el motivo del rechazo")
    contrato = pago.contrato

    pago.estado = "rechazado"
    pago.motivo_rechazo = motivo
    if etapa == "caja":
        pago.validado_por = usuario.id
        pago.fecha_validacion = sep_svc.ahora_utc()

    aud.registrar(
        db, usuario, "pago", pago.id, f"rechazar_{etapa}",
        {"id_contrato": contrato.id, "motivo": motivo, "monto": str(pago.monto)},
    )

    responsables = [u for u in (pago.registrador, contrato.registrador) if u]
    area = "Caja" if etapa == "caja" else "Facturación"
    notifs = sep_svc.crear_notificaciones(
        db, contrato.id_empresa, sep_svc.unicos(responsables, excluir_id=usuario.id),
        "pago_rechazado",
        f"{_concepto(pago)} rechazado por {area}: corregir",
        f"Contrato {contrato.numero_contrato} ({_concepto(pago)}, S/ {pago.monto:,.2f}). Motivo: {motivo}. Corrígelo desde Ventas y contratos.",
        {"id_pago": pago.id, "id_contrato": contrato.id, "id_proyecto": contrato.id_proyecto, "estado": "rechazado"},
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
    return await _rechazar_comun(
        db, usuario, pago, payload.motivo, "caja", "pendiente_caja",
        "Este pago no está pendiente de validación de Caja",
    )


@router.post("/{id_pago}/rechazar-facturacion", response_model=s.PagoOut)
async def rechazar_pago_facturacion(
    id_pago: int,
    payload: s.PagoRechazo,
    usuario: m.Usuario = Depends(require_permiso("facturar_pago")),
    db: Session = Depends(get_db),
):
    pago = _cargar_pago(db, id_pago, usuario)
    return await _rechazar_comun(
        db, usuario, pago, payload.motivo, "facturacion", "pendiente_facturacion",
        "Este pago no está pendiente de comprobante",
    )


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
    aud.registrar(
        db, usuario, "pago", pago.id, "facturar",
        {"id_contrato": contrato.id, "tipo": tipo, "numero": numero, "monto": str(pago.monto)},
    )
    # Recién ahora el pago cuenta en las cuotas (una o varias, en orden). La inicial y el contado no tocan cuotas.
    if pago.tipo in ("cuota", "cuotas") and pago.cuota_desde:
        cuotas = (
            db.query(m.CronogramaPago)
            .filter(
                m.CronogramaPago.id_contrato == contrato.id,
                m.CronogramaPago.requiere_pago.is_(True),
                m.CronogramaPago.estado != m.EstadoCuotaEnum.pagada,
                m.CronogramaPago.numero_cuota >= pago.cuota_desde,
                m.CronogramaPago.numero_cuota <= (pago.cuota_hasta or pago.cuota_desde),
            )
            .order_by(m.CronogramaPago.numero_cuota)
            .all()
        )
        total_falta = sum((q.monto_cuota - (q.monto_pagado or Decimal("0")) for q in cuotas), Decimal("0"))
        if pago.monto > total_falta:
            raise _conflicto(f"El pago (S/ {pago.monto:,.2f}) supera lo que falta cobrar (S/ {total_falta:,.2f})")
        restante = pago.monto
        for cuota in cuotas:
            if restante <= 0:
                break
            falta = cuota.monto_cuota - (cuota.monto_pagado or Decimal("0"))
            aplicar = min(restante, falta)
            cuota.monto_pagado = (cuota.monto_pagado or Decimal("0")) + aplicar
            restante -= aplicar
            if cuota.monto_pagado >= cuota.monto_cuota:
                cuota.estado = m.EstadoCuotaEnum.pagada
                cuota.fecha_pago_real = pago.fecha_pago
            else:
                cuota.estado = m.EstadoCuotaEnum.parcial

    elif pago.tipo == "cancelacion":
        # Cancelación total: deja el crédito en cero y cierra el contrato (si algo no cuadra no se guarda nada)
        amort_svc.aplicar_cancelacion(db, m, contrato, pago)


    elif pago.tipo == "amortizacion":
        # Abono a capital: aquí se reescribe el cronograma pendiente.
        # Si algo no cuadra lanza error y NO se guarda nada.
        amort_svc.aplicar_amortizacion(db, m, contrato, pago)


    
    # Contado con saldo: al pagarse la última cuota, el contrato queda cancelado
    if contrato.forma_pago == m.FormaPagoEnum.contado and contrato.estado == m.EstadoContratoEnum.vigente:
        db.flush()
        faltan = (
            db.query(m.CronogramaPago.id)
            .filter(
                m.CronogramaPago.id_contrato == contrato.id,
                m.CronogramaPago.requiere_pago.is_(True),
                m.CronogramaPago.estado != m.EstadoCuotaEnum.pagada,
            )
            .first()
        )
        if faltan is None:
            contrato.estado = m.EstadoContratoEnum.cancelado

    destinatarios = sep_svc.unicos(
        sep_svc.usuarios_por_roles(db, contrato.id_empresa, contrato.id_proyecto, ["cobranza", "admin"])
        + [pago.registrador],
        excluir_id=usuario.id,
    )
    notifs = sep_svc.crear_notificaciones(
        db, contrato.id_empresa, destinatarios,
        "pago_aplicado",
        f"{_concepto(pago)} con comprobante emitido",
        f"Contrato {contrato.numero_contrato}: {tipo} {numero} por S/ {pago.monto:,.2f} ({_concepto(pago)}).",
        {"id_pago": pago.id, "id_contrato": contrato.id, "id_proyecto": contrato.id_proyecto, "estado": "validado"},
    )
    db.commit()

    await _emitir(pago, contrato, notifs)
    # Refresca los cronogramas abiertos en Contratos y Cobranza
    await notificar_pago_registrado(contrato.id, contrato.id_proyecto, contrato.id_empresa)
    return pago