from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.database import get_db
from app.deps import require_permiso
from app.models import models as m
from app.schemas import schemas as s
from app.services import separacion_service as svc
from app.sockets import notificar_separacion, notificar_cambio_estado_lote

router = APIRouter(prefix="/separaciones", tags=["separaciones"])

E = m.EstadoSeparacionEnum
LOTE = m.EstadoLoteEnum


def _conflicto(detalle: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detalle)


def _detalle(db: Session, id_separacion: int, usuario: m.Usuario) -> s.SeparacionOut:
    return s.SeparacionOut.desde_separacion(svc.cargar_separacion(db, id_separacion, usuario))


async def _emitir(db: Session, sep: m.Separacion, usuario: m.Usuario, notifs: list, cambio_lote: bool = False):
    await notificar_separacion(
        "separacion:actualizada",
        svc.resumen_socket(sep),
        sep.id_proyecto,
        svc.notificaciones_a_dict(notifs),
    )
    if cambio_lote:
        await notificar_cambio_estado_lote(
            svc.lote_out_dict(db, sep.id_lote),
            id_proyecto=sep.id_proyecto,
            id_empresa=usuario.id_empresa,
        )


# ---------------------------------------------------------------- lectura --

@router.get("", response_model=list[s.SeparacionOut])
def listar_separaciones(
    id_proyecto: int,
    estado: Optional[E] = None,
    usuario: m.Usuario = Depends(require_permiso("ver_separaciones")),
    db: Session = Depends(get_db),
):
    svc.validar_acceso_proyecto(db, usuario, id_proyecto)
    svc.marcar_vencidas(db, usuario.id_empresa, id_proyecto)

    query = (
        db.query(m.Separacion)
        .options(
            joinedload(m.Separacion.cliente),
            joinedload(m.Separacion.lote),
            joinedload(m.Separacion.ejecutivo),
            joinedload(m.Separacion.validador),
            selectinload(m.Separacion.comprobantes),
            selectinload(m.Separacion.devoluciones),
        )
        .filter(m.Separacion.id_empresa == usuario.id_empresa, m.Separacion.id_proyecto == id_proyecto)
    )
    if estado:
        query = query.filter(m.Separacion.estado == estado)
    if usuario.rol.clave == "ejecutivo_ventas":
        query = query.filter(m.Separacion.id_ejecutivo == usuario.id)

    return [s.SeparacionOut.desde_separacion(x) for x in query.order_by(m.Separacion.created_at.desc()).all()]


@router.get("/{id_separacion}", response_model=s.SeparacionOut)
def obtener_separacion(
    id_separacion: int,
    usuario: m.Usuario = Depends(require_permiso("ver_separaciones")),
    db: Session = Depends(get_db),
):
    return _detalle(db, id_separacion, usuario)


# ------------------------------------------------------------------ crear --

@router.post("", response_model=s.SeparacionOut, status_code=status.HTTP_201_CREATED)
async def crear_separacion(
    payload: s.SeparacionCreate,
    usuario: m.Usuario = Depends(require_permiso("crear_separacion")),
    db: Session = Depends(get_db),
):
    lote = db.query(m.Lote).filter(m.Lote.id == payload.id_lote).with_for_update().first()
    if not lote or not lote.activo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lote no encontrado")
    svc.validar_acceso_proyecto(db, usuario, lote.id_proyecto)

    if lote.estado != LOTE.libre:
        raise _conflicto(f"El lote {lote.codigo} no está libre (estado actual: {lote.estado.value})")

    if (
        payload.precio_descontado is not None
        and lote.precio_total_base is not None
        and payload.precio_descontado > lote.precio_total_base
    ):
        raise HTTPException(
            status_code=422,
            detail=f"El precio descontado no puede superar el precio regular (S/ {lote.precio_total_base:,.2f})",
        )

    cliente = (
        db.query(m.Cliente)
        .filter(m.Cliente.id == payload.id_cliente, m.Cliente.id_empresa == usuario.id_empresa)
        .first()
    )
    if not cliente:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado")

    activa = (
        db.query(m.Separacion.id)
        .filter(m.Separacion.id_lote == lote.id, m.Separacion.estado.in_(svc.ESTADOS_ACTIVOS))
        .first()
    )
    if activa:
        raise _conflicto("Este lote ya tiene una separación en curso")

    sep = m.Separacion(
        **payload.model_dump(exclude={"id_lote", "id_cliente"}),
        id_empresa=usuario.id_empresa,
        id_proyecto=lote.id_proyecto,
        id_lote=lote.id,
        id_cliente=cliente.id,
        id_ejecutivo=usuario.id,
        estado=E.pendiente_caja,
    )
    db.add(sep)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise _conflicto("Este lote ya tiene una separación en curso")

    destinatarios = svc.usuarios_por_roles(
        db, usuario.id_empresa, lote.id_proyecto, ["caja", "admin"], excluir_id=usuario.id
    )
    notifs = svc.crear_notificaciones(
        db, usuario.id_empresa, destinatarios,
        "separacion_pendiente_caja",
        "Separación por validar",
        f"{usuario.nombre} separó el lote {lote.codigo} por S/ {payload.importe:,.2f}",
        {"id_separacion": sep.id, "id_proyecto": lote.id_proyecto, "id_lote": lote.id, "estado": "pendiente_caja"},
    )
    db.commit()

    await _emitir(db, sep, usuario, notifs)
    return _detalle(db, sep.id, usuario)


# ----------------------------------------------------------------- editar --

@router.patch("/{id_separacion}", response_model=s.SeparacionOut)
async def actualizar_separacion(
    id_separacion: int,
    payload: s.SeparacionUpdate,
    usuario: m.Usuario = Depends(require_permiso("editar_separacion")),
    db: Session = Depends(get_db),
):
    sep = svc.cargar_separacion(db, id_separacion, usuario)
    if sep.estado in svc.ESTADOS_CERRADOS:
        raise _conflicto("La separación ya está cerrada y no se puede modificar")

    datos = payload.model_dump(exclude_unset=True)
    if datos.get("fecha_vencimiento") is None:
        datos.pop("fecha_vencimiento", None)
    nueva_venc = datos.get("fecha_vencimiento")
    if nueva_venc is not None and nueva_venc < sep.fecha_inicio:
        raise HTTPException(status_code=422, detail="El vencimiento no puede ser anterior a la fecha inicial")

    for campo, valor in datos.items():
        setattr(sep, campo, valor)

    # Prórroga: una separación vencida con el lote aún separado vuelve a vigente
    if (
        sep.estado == E.vencida
        and nueva_venc is not None
        and nueva_venc >= svc.hoy_peru()
        and sep.lote.estado == LOTE.separado
    ):
        sep.estado = E.vigente

    db.commit()
    await _emitir(db, sep, usuario, [])
    return _detalle(db, id_separacion, usuario)


# ------------------------------------------------------------------- caja --

@router.post("/{id_separacion}/validar", response_model=s.SeparacionOut)
async def validar_voucher(
    id_separacion: int,
    usuario: m.Usuario = Depends(require_permiso("validar_voucher")),
    db: Session = Depends(get_db),
):
    sep = svc.cargar_separacion(db, id_separacion, usuario)
    if sep.estado != E.pendiente_caja:
        raise _conflicto("Esta separación no está pendiente de validación de Caja")
    if sep.lote.estado != LOTE.libre:
        raise _conflicto(
            f"El lote {sep.lote.codigo} ya no está libre (estado: {sep.lote.estado.value}). Rechaza esta separación."
        )

    sep.estado = E.pendiente_facturacion
    sep.validado_por = usuario.id
    sep.fecha_validacion = svc.ahora_utc()
    sep.motivo_rechazo = None
    cambio = svc.cambiar_estado_lote(
        db, sep.lote, LOTE.separado, usuario, f"Separación #{sep.id} validada por Caja"
    )

    destinatarios = svc.unicos(
        svc.usuarios_por_roles(db, sep.id_empresa, sep.id_proyecto, ["facturacion", "admin"])
        + [sep.ejecutivo],
        excluir_id=usuario.id,
    )
    notifs = svc.crear_notificaciones(
        db, sep.id_empresa, destinatarios,
        "separacion_pendiente_facturacion",
        "Voucher validado: emitir comprobante",
        f"Caja validó el voucher del lote {sep.lote.codigo}. Falta emitir y subir el comprobante.",
        {"id_separacion": sep.id, "id_proyecto": sep.id_proyecto, "id_lote": sep.id_lote, "estado": "pendiente_facturacion"},
    )
    db.commit()

    await _emitir(db, sep, usuario, notifs, cambio_lote=cambio)
    return _detalle(db, id_separacion, usuario)


@router.post("/{id_separacion}/rechazar", response_model=s.SeparacionOut)
async def rechazar_voucher(
    id_separacion: int,
    payload: s.SeparacionRechazo,
    usuario: m.Usuario = Depends(require_permiso("validar_voucher")),
    db: Session = Depends(get_db),
):
    sep = svc.cargar_separacion(db, id_separacion, usuario)
    if sep.estado != E.pendiente_caja:
        raise _conflicto("Esta separación no está pendiente de validación de Caja")
    motivo = payload.motivo.strip()
    if not motivo:
        raise HTTPException(status_code=422, detail="Debes indicar el motivo del rechazo")

    sep.estado = E.rechazada
    sep.motivo_rechazo = motivo
    sep.validado_por = usuario.id
    sep.fecha_validacion = svc.ahora_utc()

    notifs = svc.crear_notificaciones(
        db, sep.id_empresa, svc.unicos([sep.ejecutivo], excluir_id=usuario.id),
        "separacion_rechazada",
        "Separación rechazada por Caja",
        f"Lote {sep.lote.codigo}: {motivo}",
        {"id_separacion": sep.id, "id_proyecto": sep.id_proyecto, "id_lote": sep.id_lote, "estado": "rechazada"},
    )
    db.commit()

    await _emitir(db, sep, usuario, notifs)
    return _detalle(db, id_separacion, usuario)


# ------------------------------------------------------------ facturación --

@router.post("/{id_separacion}/comprobante", response_model=s.SeparacionOut)
async def subir_comprobante(
    id_separacion: int,
    payload: s.ComprobanteCreate,
    usuario: m.Usuario = Depends(require_permiso("emitir_comprobante")),
    db: Session = Depends(get_db),
):
    sep = svc.cargar_separacion(db, id_separacion, usuario)
    if sep.estado != E.pendiente_facturacion:
        raise _conflicto("Esta separación no está pendiente de comprobante")

    tipo = payload.tipo.strip().lower()
    if tipo not in ("boleta", "factura", "recibo"):
        raise HTTPException(status_code=422, detail="El tipo debe ser boleta, factura o recibo")
    numero = payload.numero.strip()
    if not numero:
        raise HTTPException(status_code=422, detail="El número de comprobante es obligatorio")

    db.add(m.ComprobantePago(
        id_separacion=sep.id, tipo=tipo, numero=numero,
        archivo_url=payload.archivo_url, emitido_por=usuario.id,
    ))
    sep.estado = E.vigente

    notifs = svc.crear_notificaciones(
        db, sep.id_empresa, svc.unicos([sep.ejecutivo], excluir_id=usuario.id),
        "separacion_vigente",
        "Comprobante emitido",
        f"Lote {sep.lote.codigo}: {tipo} {numero}. La separación está vigente.",
        {"id_separacion": sep.id, "id_proyecto": sep.id_proyecto, "id_lote": sep.id_lote, "estado": "vigente"},
    )
    db.commit()

    await _emitir(db, sep, usuario, notifs)
    return _detalle(db, id_separacion, usuario)


# ------------------------------------------------------------- conversión --

@router.post("/{id_separacion}/convertir", response_model=s.SeparacionOut)
async def convertir_separacion(
    id_separacion: int,
    fecha_conversion: Optional[date] = None,
    usuario: m.Usuario = Depends(require_permiso("convertir_separacion")),
    db: Session = Depends(get_db),
):
    """El cliente llegó a comprar. El lote sigue 'separado' hasta que se registre la venta."""
    sep = svc.cargar_separacion(db, id_separacion, usuario)
    if sep.estado != E.vigente:
        raise _conflicto("Solo una separación vigente puede convertirse en compra")
    if not sep.contrato_firmado_url:
        raise _conflicto("Debes subir el contrato de separación firmado antes de convertir la separación en venta")

    sep.estado = E.convertida
    sep.fecha_conversion = fecha_conversion or svc.hoy_peru()
    db.commit()

    await _emitir(db, sep, usuario, [])
    return _detalle(db, id_separacion, usuario)


# --------------------------------------------------------------- proforma --
# ------------------------------------------------------------- documentos --

@router.post("/{id_separacion}/proforma", response_model=s.SeparacionOut)
async def generar_proforma(
    id_separacion: int,
    usuario: m.Usuario = Depends(require_permiso("editar_separacion")),
    db: Session = Depends(get_db),
):
    sep = svc.cargar_separacion(db, id_separacion, usuario)
    if sep.estado in svc.ESTADOS_CERRADOS:
        raise _conflicto("La separación ya está cerrada, no se puede generar la proforma")

    sep.proforma_url = svc.generar_documento(db, sep, con_clausulas=False)
    db.commit()

    await _emitir(db, sep, usuario, [])
    return _detalle(db, id_separacion, usuario)


@router.post("/{id_separacion}/contrato", response_model=s.SeparacionOut)
async def generar_contrato(
    id_separacion: int,
    usuario: m.Usuario = Depends(require_permiso("editar_separacion")),
    db: Session = Depends(get_db),
):
    sep = svc.cargar_separacion(db, id_separacion, usuario)
    if sep.estado in svc.ESTADOS_CERRADOS:
        raise _conflicto("La separación ya está cerrada, no se puede generar el contrato")
    if sep.estado in (E.pendiente_caja, E.rechazada):
        raise _conflicto("El contrato se genera una vez que Caja valide el voucher")

    sep.contrato_url = svc.generar_documento(db, sep, con_clausulas=True)
    db.commit()

    await _emitir(db, sep, usuario, [])
    return _detalle(db, id_separacion, usuario)


# ------------------------------------------------------------- devolución --

@router.post("/{id_separacion}/devolucion", response_model=s.SeparacionOut)
async def solicitar_devolucion(
    id_separacion: int,
    payload: s.DevolucionCreate,
    usuario: m.Usuario = Depends(require_permiso("solicitar_devolucion")),
    db: Session = Depends(get_db),
):
    sep = svc.cargar_separacion(db, id_separacion, usuario)
    if sep.estado not in (E.vigente, E.vencida, E.convertida):
        raise _conflicto("Solo se puede pedir devolución de una separación vigente, vencida o convertida")
    if any(d.estado == "pendiente" for d in sep.devoluciones):
        raise _conflicto("Ya hay una devolución pendiente para esta separación")
    tiene_venta_activa = db.query(m.Venta.id).filter(
        m.Venta.id_separacion == sep.id,
        m.Venta.estado.notin_([m.EstadoVentaEnum.cancelada, m.EstadoVentaEnum.anulada]),
    ).first() is not None
    if (tiene_venta_activa or sep.estado == E.convertida) and not payload.continua_venta:
        raise _conflicto("La venta ya está en marcha: la devolución debe registrarse indicando que el cliente continúa con la compra")
    ya_devuelto = sum((d.monto for d in sep.devoluciones if d.estado == "aprobada"), Decimal("0"))
    disponible = sep.importe - ya_devuelto
    if payload.monto > disponible:
        raise HTTPException(status_code=422, detail=f"El monto no puede superar lo disponible a devolver (S/ {disponible:,.2f})")
    sustento = payload.sustento.strip()
    if not sustento:
        raise HTTPException(status_code=422, detail="El sustento es obligatorio")

    db.add(m.Devolucion(
        id_separacion=sep.id, monto=payload.monto, sustento=sustento,
        solicitado_por=usuario.id, estado="pendiente", continua_venta=payload.continua_venta,
    ))


    destinatarios = svc.usuarios_por_roles(
        db, sep.id_empresa, sep.id_proyecto, ["gerencia", "admin"], excluir_id=usuario.id
    )
    notifs = svc.crear_notificaciones(
        db, sep.id_empresa, destinatarios,
        "devolucion_pendiente",
        "Devolución por aprobar",
        f"{usuario.nombre} solicita devolver S/ {payload.monto:,.2f} (lote {sep.lote.codigo})",
        {"id_separacion": sep.id, "id_proyecto": sep.id_proyecto, "id_lote": sep.id_lote, "estado": "devolucion_pendiente"},
    )
    db.commit()

    await _emitir(db, sep, usuario, notifs)
    return _detalle(db, id_separacion, usuario)


@router.post("/{id_separacion}/devolucion/resolver", response_model=s.SeparacionOut)
async def resolver_devolucion(
    id_separacion: int,
    payload: s.DevolucionResolver,
    usuario: m.Usuario = Depends(require_permiso("aprobar_devolucion")),
    db: Session = Depends(get_db),
):
    sep = svc.cargar_separacion(db, id_separacion, usuario)
    dev = next((d for d in sep.devoluciones if d.estado == "pendiente"), None)
    if not dev:
        raise _conflicto("Esta separación no tiene una devolución pendiente")

    dev.resuelto_por = usuario.id
    dev.fecha_resolucion = svc.ahora_utc()
    dev.respuesta = payload.respuesta

    # Compatibilidad: separaciones que quedaron en 'devolucion_pendiente' con el flujo anterior
    if sep.estado == E.devolucion_pendiente:
        sep.estado = E.vencida if sep.fecha_vencimiento < svc.hoy_peru() else E.vigente

    cambio = False
    if payload.aprobar:
        dev.estado = "aprobada"
        total_devuelto = sum((d.monto for d in sep.devoluciones if d.estado == "aprobada"), Decimal("0"))
        # Si el cliente continúa con la compra, solo se registra el pago: el lote y la separación NO cambian
        if dev.continua_venta:
            total_devuelto = Decimal("0")
        tiene_venta = db.query(m.Venta.id).filter(
            m.Venta.id_separacion == sep.id,
            m.Venta.estado.notin_([m.EstadoVentaEnum.cancelada, m.EstadoVentaEnum.anulada]),
        ).first() is not None
        if sep.estado in (E.vigente, E.vencida) and not tiene_venta and total_devuelto >= sep.importe:
            sep.estado = E.devuelta
            if sep.lote.estado == LOTE.separado:
                cambio = svc.cambiar_estado_lote(
                    db, sep.lote, LOTE.libre, usuario, f"Devolución aprobada de la separación #{sep.id}"
                )
        titulo = "Devolución aprobada"
    else:
        dev.estado = "rechazada"
        titulo = "Devolución rechazada"

    notifs = svc.crear_notificaciones(
        db, sep.id_empresa, svc.unicos([sep.ejecutivo], excluir_id=usuario.id),
        "devolucion_resuelta",
        titulo,
        f"Lote {sep.lote.codigo}" + (f": {payload.respuesta}" if payload.respuesta else ""),
        {"id_separacion": sep.id, "id_proyecto": sep.id_proyecto, "id_lote": sep.id_lote, "estado": sep.estado.value},
    )
    db.commit()

    await _emitir(db, sep, usuario, notifs, cambio_lote=cambio)
    return _detalle(db, id_separacion, usuario)


# ------------------------------------------------------------ liberación --

@router.post("/{id_separacion}/liberar", response_model=s.SeparacionOut)
async def liberar_lote(
    id_separacion: int,
    usuario: m.Usuario = Depends(require_permiso("liberar_lote")),
    db: Session = Depends(get_db),
):
    """Libera el lote de una separación vencida, o de una vigente ya devuelta por completo
    cuyo cliente finalmente no continúa con la compra."""
    sep = svc.cargar_separacion(db, id_separacion, usuario)
    total_devuelto = sum((d.monto for d in sep.devoluciones if d.estado == "aprobada"), Decimal("0"))
    ya_devuelta = total_devuelto >= sep.importe

    if not (sep.estado == E.vencida or (sep.estado == E.vigente and ya_devuelta)):
        raise _conflicto("Solo se libera el lote de una separación vencida, o vigente ya devuelta por completo")
    tiene_venta = db.query(m.Venta.id).filter(
        m.Venta.id_separacion == sep.id,
        m.Venta.estado.notin_([m.EstadoVentaEnum.cancelada, m.EstadoVentaEnum.anulada]),
    ).first() is not None
    if tiene_venta:
        raise _conflicto("Esta separación ya tiene una venta iniciada")
    if sep.lote.estado != LOTE.separado:
        raise _conflicto("El lote ya no está en estado separado")

    cambio = svc.cambiar_estado_lote(
        db, sep.lote, LOTE.libre, usuario, f"Separación #{sep.id}: lote liberado"
    )
    if ya_devuelta:
        sep.estado = E.devuelta
    notifs = svc.crear_notificaciones(
        db, sep.id_empresa, svc.unicos([sep.ejecutivo], excluir_id=usuario.id),
        "lote_liberado",
        "Lote liberado",
        f"El lote {sep.lote.codigo} volvió a libre.",
        {"id_separacion": sep.id, "id_proyecto": sep.id_proyecto, "id_lote": sep.id_lote, "estado": sep.estado.value},
    )
    db.commit()

    await _emitir(db, sep, usuario, notifs, cambio_lote=cambio)
    return _detalle(db, id_separacion, usuario)