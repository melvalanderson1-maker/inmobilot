from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from decimal import Decimal
from sqlalchemy import func, or_
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


def _es_contado_con_saldo(p: m.Pago) -> bool:
    """Venta al contado que todavía tiene saldo por pagar (el cliente paga en partes)."""
    c = p.contrato
    return bool(c and c.forma_pago == m.FormaPagoEnum.contado and (c.saldo_financiado or 0) > 0)


def _orden_pago_contado(p: m.Pago) -> int:
    """Posición cronológica de este pago entre los pagos del contrato (sin contar anulados)."""
    db = object_session(p)
    if db is None:
        return 1
    return (
        db.query(func.count(m.Pago.id))
        .filter(m.Pago.id_contrato == p.id_contrato, m.Pago.estado != "anulado", m.Pago.id <= p.id)
        .scalar()
    ) or 1


def _rango_cuotas(p: m.Pago) -> str:
    desde = _n_pago(p, p.cuota_desde)
    hasta = _n_pago(p, p.cuota_hasta or p.cuota_desde)
    return f"Cuotas {desde} a {hasta}" if hasta != desde else f"Cuota {desde}"


def _concepto(p: m.Pago) -> str:
    """Qué es este pago, en palabras que el usuario entienda."""
    if p.tipo == "inicial":
        return "Inicial"

    # Contado con saldo: el primer pago es la Inicial y los demás son 1° pago, 2° pago...
    if _es_contado_con_saldo(p) and p.tipo in ("contado", "cuota", "cuotas"):
        orden = _orden_pago_contado(p)
        return "Inicial" if (p.tipo == "contado" and orden == 1) else f"{max(orden - 1, 1)}° pago"

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

def _comprador(cli, rol=None) -> s.PagoCompradorOut:
    """Nombre + documento + archivos DNI de un comprador (persona natural o jurídica)."""
    if cli.tipo_persona == "juridica":
        nombre = cli.razon_social or ""
        documento = cli.ruc or ""
    else:
        nombre = f"{cli.nombres} {cli.apellidos}"
        documento = cli.numero_documento or ""
    rol_txt = None
    if rol is not None:
        rol_txt = rol.value if hasattr(rol, "value") else str(rol)
    return s.PagoCompradorOut(
        nombre=nombre,
        documento=documento,
        rol=rol_txt,
        dni_frente_url=cli.dni_frente_url,
        dni_reverso_url=cli.dni_reverso_url,
    )


def _a_fila(p: m.Pago, facturadores: Optional[dict] = None, correctores: Optional[dict] = None,
            editores: Optional[dict] = None, editores_voucher: Optional[dict] = None) -> s.PagoColaOut:
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
        facturado_por_nombre=(facturadores or {}).get(p.facturado_por),
        corregido_por_nombre=(correctores or {}).get(p.id),
        editado_por_nombre=(editores or {}).get(p.id),
        voucher_editado_por_nombre=(editores_voucher or {}).get(p.id),
        concepto=_concepto(p),
        detalle=p.observacion,
        lote_partida=c.lote.partida_registral if c.lote else None,
        compradores=[
            _comprador(vc.cliente, vc.rol)
            for vc in sorted(c.clientes_rel, key=lambda vc: vc.rol != m.RolClienteContratoEnum.titular)
            if vc.cliente
        ],
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


def _nombres_usuarios(db: Session, ids) -> dict:
    """id de usuario -> nombre, en una sola consulta."""
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict(db.query(m.Usuario.id, m.Usuario.nombre).filter(m.Usuario.id.in_(ids)).all())


def _ultima_correccion(db: Session, entidad: str, ids, acciones: tuple, campos: Optional[tuple] = None) -> dict:
    """id de la entidad -> nombre del último usuario que la corrigió (según auditoría).
    Si se indican `campos`, solo cuentan las ediciones que tocaron alguno de esos campos."""
    ids = {i for i in ids if i}
    if not ids:
        return {}
    q = (
        db.query(m.Auditoria.id_entidad, m.Usuario.nombre)
        .join(m.Usuario, m.Usuario.id == m.Auditoria.id_usuario)
        .filter(
            m.Auditoria.entidad == entidad,
            m.Auditoria.id_entidad.in_(ids),
            m.Auditoria.accion.in_(acciones),
        )
    )
    if campos:
        q = q.filter(or_(*[m.Auditoria.cambios.has_key(c) for c in campos]))
    filas = q.order_by(m.Auditoria.created_at.asc(), m.Auditoria.id.asc()).all()
    return {i: n for i, n in filas}  # en orden ascendente, queda el último

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
    sepes = q.order_by(m.Separacion.created_at.desc()).limit(300).all()
    nombres = _nombres_usuarios(db, [x.comprobantes[-1].emitido_por for x in sepes if x.comprobantes])
    correcciones = _ultima_correccion(
        db, "separacion", [x.id for x in sepes], ("corregir_comprobante", "editar_comprobante")
    )
    ediciones = _ultima_correccion(
        db, "separacion", [x.id for x in sepes], ("editar", "corregir_rechazo"),
        ("importe", "fecha_inicio", "medio_pago", "voucher_numero", "id_cliente", "id_lote"),
    )
    ediciones_voucher = _ultima_correccion(
        db, "separacion", [x.id for x in sepes], ("editar", "corregir_rechazo"), ("voucher_url",)
    )
    for x in sepes:
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
            facturado_por_nombre=nombres.get(comp.emitido_por) if comp else None,
            corregido_por_nombre=correcciones.get(x.id) if comp else None,
            editado_por_nombre=ediciones.get(x.id),
            voucher_editado_por_nombre=ediciones_voucher.get(x.id),
            concepto="Separación de lote", detalle=x.notas, forma_pago=None,
            lote_partida=x.lote.partida_registral if x.lote else None,
            compradores=[_comprador(c)] if c else [],
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
    devs = q.order_by(m.Devolucion.created_at.desc()).limit(300).all()
    nombres = _nombres_usuarios(db, [d.ejecutado_por for d in devs] + [d.nota_credito_por for d in devs])
    corr_nota = _ultima_correccion(db, "devolucion", [d.id for d in devs], ("corregir_nota_credito",))
    corr_voucher = _ultima_correccion(db, "devolucion", [d.id for d in devs], ("corregir_voucher",))
    for d in devs:
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
            validado_por_nombre=nombres.get(d.ejecutado_por),
            facturado_por_nombre=nombres.get(d.nota_credito_por),
            corregido_por_nombre=corr_nota.get(d.id),
            voucher_corregido_por_nombre=corr_voucher.get(d.id),
            concepto="Devolución de separación", detalle=d.sustento, forma_pago=None,
            lote_partida=sep.lote.partida_registral if sep.lote else None,
            compradores=[_comprador(c)] if c else [],
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
    pagos = query.order_by(m.Pago.created_at.desc()).limit(300).all()
    ids_fact = {p.facturado_por for p in pagos if p.facturado_por}
    facturadores = (
        dict(db.query(m.Usuario.id, m.Usuario.nombre).filter(m.Usuario.id.in_(ids_fact)).all())
        if ids_fact else {}
    )
    correctores = _ultima_correccion(db, "pago", [p.id for p in pagos], ("corregir_comprobante",))
    ids_pagos = [p.id for p in pagos]
    editores = _ultima_correccion(
        db, "pago", ids_pagos, ("editar", "corregir_rechazo"),
        ("monto", "fecha_pago", "metodo_pago", "numero_operacion", "observacion"),
    )
    editores_voucher = _ultima_correccion(
        db, "pago", ids_pagos, ("editar", "corregir_rechazo"), ("comprobante_url",)
    )
    filas = [_a_fila(p, facturadores, correctores, editores, editores_voucher) for p in pagos]
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


# ------------------------------------------------------------ correcciones --
# Caja y Facturación corrigen lo que subieron. Siempre con motivo, auditado,
# notificado (socket + push, mismo mecanismo que validar/rechazar) y refrescado en vivo.

def _exigir_rol(usuario: m.Usuario, roles: tuple, area: str) -> None:
    if usuario.rol.clave not in roles:
        raise HTTPException(status_code=403, detail=f"Solo {area} puede hacer esta corrección")


def _avisar_correccion(
    db: Session, usuario: m.Usuario, id_empresa: int, id_proyecto: int,
    roles: list, extra: list, tipo: str, titulo: str, mensaje: str, data: dict,
):
    destinatarios = sep_svc.unicos(
        sep_svc.usuarios_por_roles(db, id_empresa, id_proyecto, roles) + [u for u in extra if u],
        excluir_id=usuario.id,
    )
    return sep_svc.crear_notificaciones(db, id_empresa, destinatarios, tipo, titulo, mensaje, data)


def _nuevos_comprobante(payload: s.CorreccionComprobanteIn, con_tipo: bool) -> dict:
    nuevo: dict = {}
    if con_tipo and payload.tipo is not None:
        tipo = payload.tipo.strip().lower()
        if tipo not in ("boleta", "factura", "recibo"):
            raise HTTPException(status_code=422, detail="El tipo debe ser boleta, factura o recibo")
        nuevo["tipo"] = tipo
    if payload.numero is not None:
        numero = payload.numero.strip()
        if not numero:
            raise HTTPException(status_code=422, detail="El número no puede quedar vacío")
        nuevo["numero"] = numero
    if payload.archivo_url:
        nuevo["archivo_url"] = payload.archivo_url
    return nuevo


@router.post("/{id_pago}/corregir-comprobante", response_model=s.PagoOut)
async def corregir_comprobante_pago(
    id_pago: int,
    payload: s.CorreccionComprobanteIn,
    usuario: m.Usuario = Depends(require_permiso("facturar_pago")),
    db: Session = Depends(get_db),
):
    _exigir_rol(usuario, ("admin", "facturacion"), "Facturación")
    pago = _cargar_pago(db, id_pago, usuario)
    if pago.estado != "validado" or not pago.factura_numero:
        raise _conflicto("Solo se puede corregir un comprobante ya emitido")
    nuevo = _nuevos_comprobante(payload, True)
    actual = {"tipo": pago.factura_tipo, "numero": pago.factura_numero, "archivo_url": pago.factura_url}
    cambios = aud.diferencias({k: actual[k] for k in nuevo}, nuevo)
    if not cambios:
        raise HTTPException(status_code=422, detail="No hay cambios que guardar")

    contrato = pago.contrato
    motivo = payload.motivo.strip()
    aud.registrar(
        db, usuario, "pago", pago.id, "corregir_comprobante",
        {"id_contrato": contrato.id, "motivo": motivo, **cambios},
    )
    if "tipo" in nuevo:
        pago.factura_tipo = nuevo["tipo"]
    if "numero" in nuevo:
        pago.factura_numero = nuevo["numero"]
    if "archivo_url" in nuevo:
        pago.factura_url = nuevo["archivo_url"]

    notifs = _avisar_correccion(
        db, usuario, contrato.id_empresa, contrato.id_proyecto,
        ["cobranza", "caja", "admin"], [pago.registrador, contrato.registrador],
        "pago_comprobante_corregido",
        f"Comprobante corregido: {_concepto(pago)}",
        f"{usuario.nombre} corrigió el comprobante del contrato {contrato.numero_contrato} "
        f"({_concepto(pago)}, S/ {pago.monto:,.2f}). Motivo: {motivo}.",
        {"id_pago": pago.id, "id_contrato": contrato.id, "id_proyecto": contrato.id_proyecto, "estado": pago.estado},
    )
    db.commit()
    await _emitir(pago, contrato, notifs)
    return pago


@router.post("/corregir-separacion/{id_separacion}/comprobante")
async def corregir_comprobante_separacion(
    id_separacion: int,
    payload: s.CorreccionComprobanteIn,
    usuario: m.Usuario = Depends(require_permiso("facturar_pago")),
    db: Session = Depends(get_db),
):
    _exigir_rol(usuario, ("admin", "facturacion"), "Facturación")
    sep = (
        db.query(m.Separacion)
        .options(selectinload(m.Separacion.comprobantes), joinedload(m.Separacion.ejecutivo), joinedload(m.Separacion.lote))
        .filter(m.Separacion.id == id_separacion, m.Separacion.id_empresa == usuario.id_empresa)
        .first()
    )
    if not sep:
        raise HTTPException(status_code=404, detail="Separación no encontrada")
    venta_svc.validar_acceso_proyecto(db, usuario, sep.id_proyecto)
    comp = sep.comprobantes[-1] if sep.comprobantes else None
    if comp is None:
        raise _conflicto("Esta separación aún no tiene comprobante que corregir")

    nuevo = _nuevos_comprobante(payload, True)
    actual = {"tipo": comp.tipo, "numero": comp.numero, "archivo_url": comp.archivo_url}
    cambios = aud.diferencias({k: actual[k] for k in nuevo}, nuevo)
    if not cambios:
        raise HTTPException(status_code=422, detail="No hay cambios que guardar")

    motivo = payload.motivo.strip()
    aud.registrar(
        db, usuario, "separacion", sep.id, "corregir_comprobante",
        {"id_comprobante": comp.id, "motivo": motivo, **cambios},
    )
    for k, v in nuevo.items():
        setattr(comp, k, v)

    est = sep.estado.value if hasattr(sep.estado, "value") else str(sep.estado)
    notifs = _avisar_correccion(
        db, usuario, sep.id_empresa, sep.id_proyecto,
        ["caja", "admin"], [sep.ejecutivo],
        "separacion_comprobante_corregido",
        f"Comprobante de Separación #{sep.id} corregido",
        f"{usuario.nombre} corrigió el comprobante de la separación #{sep.id} (lote {sep.lote.codigo if sep.lote else '—'}). Motivo: {motivo}.",
        {"id_separacion": sep.id, "id_proyecto": sep.id_proyecto, "estado": est},
    )
    db.commit()
    await notificar_pago(
        "separacion:actualizada", {"id": sep.id, "estado": est}, sep.id_proyecto,
        sep_svc.notificaciones_a_dict(notifs), sep.id_empresa,
    )
    return {"ok": True}


def _cargar_devolucion(db: Session, id_devolucion: int, usuario: m.Usuario) -> m.Devolucion:
    d = (
        db.query(m.Devolucion)
        .join(m.Separacion, m.Separacion.id == m.Devolucion.id_separacion)
        .options(joinedload(m.Devolucion.separacion).joinedload(m.Separacion.ejecutivo))
        .filter(m.Devolucion.id == id_devolucion, m.Separacion.id_empresa == usuario.id_empresa)
        .first()
    )
    if not d:
        raise HTTPException(status_code=404, detail="Devolución no encontrada")
    venta_svc.validar_acceso_proyecto(db, usuario, d.separacion.id_proyecto)
    return d


@router.post("/corregir-devolucion/{id_devolucion}/nota-credito")
async def corregir_nota_credito(
    id_devolucion: int,
    payload: s.CorreccionComprobanteIn,
    usuario: m.Usuario = Depends(require_permiso("facturar_pago")),
    db: Session = Depends(get_db),
):
    _exigir_rol(usuario, ("admin", "facturacion"), "Facturación")
    d = _cargar_devolucion(db, id_devolucion, usuario)
    if not d.nota_credito_numero:
        raise _conflicto("Esta devolución aún no tiene nota de crédito que corregir")
    nuevo = _nuevos_comprobante(payload, False)
    mapa = {"numero": "nota_credito_numero", "archivo_url": "nota_credito_url"}
    cambios = aud.diferencias({mapa[k]: getattr(d, mapa[k]) for k in nuevo}, {mapa[k]: v for k, v in nuevo.items()})
    if not cambios:
        raise HTTPException(status_code=422, detail="No hay cambios que guardar")

    sep = d.separacion
    motivo = payload.motivo.strip()
    aud.registrar(db, usuario, "devolucion", d.id, "corregir_nota_credito", {"id_separacion": sep.id, "motivo": motivo, **cambios})
    for k, v in nuevo.items():
        setattr(d, mapa[k], v)

    notifs = _avisar_correccion(
        db, usuario, sep.id_empresa, sep.id_proyecto,
        ["caja", "admin", "gerencia"], [sep.ejecutivo],
        "devolucion_nota_credito_corregida",
        f"Nota de crédito corregida (Separación #{sep.id})",
        f"{usuario.nombre} corrigió la nota de crédito de la devolución de la separación #{sep.id}. Motivo: {motivo}.",
        {"id_separacion": sep.id, "id_devolucion": d.id, "id_proyecto": sep.id_proyecto},
    )
    db.commit()
    await notificar_pago(
        "separacion:actualizada", {"id": sep.id}, sep.id_proyecto,
        sep_svc.notificaciones_a_dict(notifs), sep.id_empresa,
    )
    return {"ok": True}


@router.post("/corregir-devolucion/{id_devolucion}/voucher")
async def corregir_voucher_devolucion(
    id_devolucion: int,
    payload: s.CorreccionVoucherDevolucionIn,
    usuario: m.Usuario = Depends(require_permiso("validar_pago")),
    db: Session = Depends(get_db),
):
    _exigir_rol(usuario, ("admin", "caja"), "Caja")
    d = _cargar_devolucion(db, id_devolucion, usuario)
    if not d.voucher_url:
        raise _conflicto("Esta devolución aún no fue ejecutada por Caja")
    nuevo: dict = {}
    if payload.metodo_pago is not None and payload.metodo_pago.strip():
        nuevo["metodo_pago"] = payload.metodo_pago.strip()
    if payload.numero_operacion is not None:
        if not payload.numero_operacion.strip():
            raise HTTPException(status_code=422, detail="El N° de operación no puede quedar vacío")
        nuevo["numero_operacion"] = payload.numero_operacion.strip()
    if payload.voucher_url:
        nuevo["voucher_url"] = payload.voucher_url
    cambios = aud.diferencias({k: getattr(d, k) for k in nuevo}, nuevo)
    if not cambios:
        raise HTTPException(status_code=422, detail="No hay cambios que guardar")

    sep = d.separacion
    motivo = payload.motivo.strip()
    aud.registrar(db, usuario, "devolucion", d.id, "corregir_voucher", {"id_separacion": sep.id, "motivo": motivo, **cambios})
    for k, v in nuevo.items():
        setattr(d, k, v)

    notifs = _avisar_correccion(
        db, usuario, sep.id_empresa, sep.id_proyecto,
        ["facturacion", "admin", "gerencia"], [sep.ejecutivo],
        "devolucion_voucher_corregido",
        f"Voucher de devolución corregido (Separación #{sep.id})",
        f"{usuario.nombre} corrigió el voucher/operación de la devolución de la separación #{sep.id}. Motivo: {motivo}.",
        {"id_separacion": sep.id, "id_devolucion": d.id, "id_proyecto": sep.id_proyecto},
    )
    db.commit()
    await notificar_pago(
        "separacion:actualizada", {"id": sep.id}, sep.id_proyecto,
        sep_svc.notificaciones_a_dict(notifs), sep.id_empresa,
    )
    return {"ok": True}



@router.post("/{id_pago}/revertir-validacion", response_model=s.PagoOut)
async def revertir_validacion_caja(
    id_pago: int,
    payload: s.ReversionValidacionIn,
    usuario: m.Usuario = Depends(require_permiso("validar_pago")),
    db: Session = Depends(get_db),
):
    """Caja se equivocó al validar: el pago vuelve a su cola, solo si Facturación aún no emitió comprobante."""
    _exigir_rol(usuario, ("admin", "caja"), "Caja")
    pago = _cargar_pago(db, id_pago, usuario)
    if pago.estado != "pendiente_facturacion" or pago.factura_numero:
        raise _conflicto("Solo se puede revertir mientras Facturación no haya emitido el comprobante")

    contrato = pago.contrato
    motivo = payload.motivo.strip()
    aud.registrar(
        db, usuario, "pago", pago.id, "revertir_validacion_caja",
        {
            "id_contrato": contrato.id,
            "motivo": motivo,
            "monto": str(pago.monto),
            "validado_por_previo": pago.validado_por,
            "fecha_validacion_previa": str(pago.fecha_validacion) if pago.fecha_validacion else None,
        },
    )
    pago.estado = "pendiente_caja"
    pago.validado_por = None
    pago.fecha_validacion = None
    pago.motivo_rechazo = None

    notifs = _avisar_correccion(
        db, usuario, contrato.id_empresa, contrato.id_proyecto,
        ["facturacion", "caja", "admin"], [pago.registrador],
        "pago_validacion_revertida",
        f"Validación revertida: {_concepto(pago)}",
        f"{usuario.nombre} revirtió la validación de Caja del contrato {contrato.numero_contrato} "
        f"({_concepto(pago)}, S/ {pago.monto:,.2f}). Motivo: {motivo}. Vuelve a Caja.",
        {"id_pago": pago.id, "id_contrato": contrato.id, "id_proyecto": contrato.id_proyecto, "estado": "pendiente_caja"},
    )
    db.commit()
    await _emitir(pago, contrato, notifs)
    return pago



