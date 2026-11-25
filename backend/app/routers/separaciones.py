from datetime import date
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.database import get_db
from app.deps import require_permiso
from app.models import models as m
from app.schemas import schemas as s
from app.services import separacion_service as svc
from app.sockets import notificar_separacion, notificar_cambio_estado_lote

from app.services import auditoria as aud

router = APIRouter(prefix="/separaciones", tags=["separaciones"])

E = m.EstadoSeparacionEnum
LOTE = m.EstadoLoteEnum

# Estados de una devolución que ya comprometen el dinero a devolver
DEV_APROBADAS = ("aprobada", "pendiente_caja", "pendiente_facturacion", "completada")


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
        sep.id_empresa,
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

    if lote.estado != LOTE.libre and not svc.PERMITIR_SEPARAR_LOTES_OCUPADOS:
        raise _conflicto(f"El lote {lote.codigo} no está libre (estado actual: {lote.estado.value})")

    # Validación de precio deshabilitada: se permite precio mayor o menor al de lista
    # svc.validar_precio_descontado(lote, payload.precio_descontado, payload.tipo_pago)

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
        **payload.model_dump(exclude={"id_lote", "id_cliente", "id_proforma"}),
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

    # Si viene de una proforma rápida: queda vinculada y su documento pasa a ser la proforma de la separación
    if payload.id_proforma:
        pf = (
            db.query(m.Proforma)
            .filter(m.Proforma.id == payload.id_proforma, m.Proforma.id_empresa == usuario.id_empresa)
            .with_for_update()
            .first()
        )
        if not pf or pf.id_lote != lote.id:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La proforma no corresponde a este lote")
        if pf.estado == "convertida":
            db.rollback()
            raise _conflicto("Esa proforma ya se usó en otra separación")
        pf.estado = "convertida"
        pf.id_separacion = sep.id
        if not sep.proforma_url:
            sep.proforma_url = pf.documento_url

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

CAMPOS_BASICOS = {
    "fecha_vencimiento", "tipo_pago", "notas", "agenda_fecha", "proforma_url",
    "contrato_firmado_url", "precio_valido_hasta", "precio_descontado",
}
CAMPOS_OBLIGATORIOS = ("fecha_inicio", "fecha_vencimiento", "importe", "dni_frente_url", "voucher_url")

# Si el ejecutivo corrige alguno de estos en una separación rechazada, vuelve a Caja
CAMPOS_QUE_REVALIDAN_SEP = {
    "importe", "fecha_inicio", "voucher_url", "voucher_numero", "medio_pago",
    "dni_frente_url", "dni_reverso_url", "id_cliente", "id_lote",
}


@router.patch("/{id_separacion}", response_model=s.SeparacionOut)
async def actualizar_separacion(
    id_separacion: int,
    payload: s.SeparacionUpdate,
    usuario: m.Usuario = Depends(require_permiso("editar_separacion")),
    db: Session = Depends(get_db),
):
    sep = svc.cargar_separacion(db, id_separacion, usuario)
    estado_previo = sep.estado
    if sep.estado in svc.ESTADOS_CERRADOS and not svc.PERMITIR_EDITAR_TODO:
        raise _conflicto("La separación ya está cerrada y no se puede modificar")

    datos = payload.model_dump(exclude_unset=True)

    # Con la edición total apagada, solo se aceptan los campos de siempre
    if not svc.PERMITIR_EDITAR_TODO:
        datos = {k: v for k, v in datos.items() if k in CAMPOS_BASICOS}

    # Los campos obligatorios no se pueden dejar vacíos
    for campo in CAMPOS_OBLIGATORIOS:
        if campo in datos and datos[campo] is None:
            datos.pop(campo)

    # --- cambio de lote ---
    nuevo_lote = None
    lote_ant = None
    if "id_lote" in datos and datos["id_lote"] == sep.id_lote:
        datos.pop("id_lote")
    if "id_lote" in datos:
        tiene_venta = db.query(m.Venta.id).filter(
            m.Venta.id_separacion == sep.id,
            m.Venta.estado.notin_([m.EstadoVentaEnum.cancelada, m.EstadoVentaEnum.anulada]),
        ).first() is not None
        if tiene_venta:
            raise _conflicto("Esta separación ya tiene una venta iniciada: no se puede cambiar el lote")

        nuevo_lote = db.query(m.Lote).filter(m.Lote.id == datos["id_lote"]).with_for_update().first()
        if not nuevo_lote or not nuevo_lote.activo:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lote no encontrado")
        svc.validar_acceso_proyecto(db, usuario, nuevo_lote.id_proyecto)
        if nuevo_lote.estado != LOTE.libre and not svc.PERMITIR_SEPARAR_LOTES_OCUPADOS:
            raise _conflicto(f"El lote {nuevo_lote.codigo} no está libre (estado actual: {nuevo_lote.estado.value})")
        otra = (
            db.query(m.Separacion.id)
            .filter(
                m.Separacion.id_lote == nuevo_lote.id,
                m.Separacion.id != sep.id,
                m.Separacion.estado.in_(svc.ESTADOS_ACTIVOS),
            )
            .first()
        )
        if otra:
            raise _conflicto(f"El lote {nuevo_lote.codigo} ya tiene una separación en curso")
        lote_ant = sep.lote
        datos["id_proyecto"] = nuevo_lote.id_proyecto


    # --- cambio de cliente ---
    if "id_cliente" in datos and (datos["id_cliente"] is None or datos["id_cliente"] == sep.id_cliente):
        datos.pop("id_cliente")
    if "id_cliente" in datos:
        tiene_venta_cli = db.query(m.Venta.id).filter(
            m.Venta.id_separacion == sep.id,
            m.Venta.estado.notin_([m.EstadoVentaEnum.cancelada, m.EstadoVentaEnum.anulada]),
        ).first() is not None
        if tiene_venta_cli:
            raise _conflicto("Esta separación ya tiene una venta iniciada: no se puede cambiar el cliente")
        nuevo_cliente = (
            db.query(m.Cliente)
            .filter(m.Cliente.id == datos["id_cliente"], m.Cliente.id_empresa == usuario.id_empresa)
            .first()
        )
        if not nuevo_cliente:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado")
        # El DNI de la separación pasa a ser el del cliente nuevo (si lo tiene y no se envió otro)
        if nuevo_cliente.dni_frente_url and "dni_frente_url" not in datos:
            datos["dni_frente_url"] = nuevo_cliente.dni_frente_url
            datos["dni_reverso_url"] = nuevo_cliente.dni_reverso_url
    

    if {"fecha_inicio", "fecha_vencimiento", "precio_valido_hasta"} & datos.keys():
        fecha_ini = datos.get("fecha_inicio", sep.fecha_inicio)
        fecha_ven = datos.get("fecha_vencimiento", sep.fecha_vencimiento)
        fecha_pv = datos.get("precio_valido_hasta", sep.precio_valido_hasta)
        if fecha_ven < fecha_ini:
            raise HTTPException(status_code=422, detail="El vencimiento no puede ser anterior a la fecha inicial")
        if fecha_pv and fecha_pv < fecha_ini:
            raise HTTPException(status_code=422, detail="La validez del precio no puede ser anterior a la fecha inicial")



    cambios = aud.diferencias({c: getattr(sep, c) for c in datos}, datos)
    if cambios:
        aud.registrar(db, usuario, "separacion", sep.id, "editar", cambios)

    for campo, valor in datos.items():
        setattr(sep, campo, valor)

    # Si la separación ya tenía el lote anterior como 'separado' y el nuevo está libre, se traspasa el estado
    cambio_lotes = False
    id_lote_ant = None
    if nuevo_lote is not None:
        id_lote_ant = lote_ant.id
        if (
            sep.estado not in svc.ESTADOS_CERRADOS
            and lote_ant.estado == LOTE.separado
            and nuevo_lote.estado == LOTE.libre
        ):
            svc.cambiar_estado_lote(db, nuevo_lote, LOTE.separado, usuario, f"Separación #{sep.id}: lote asignado")
            svc.cambiar_estado_lote(db, lote_ant, LOTE.libre, usuario, f"Separación #{sep.id}: pasó a otro lote")
            cambio_lotes = True

    # Corrección de una separación rechazada: vuelve a Caja y se notifica
    notifs = []
    if estado_previo == E.rechazada and (CAMPOS_QUE_REVALIDAN_SEP & cambios.keys()):
        lote_rev = nuevo_lote or sep.lote
        otra_rev = (
            db.query(m.Separacion.id)
            .filter(
                m.Separacion.id_lote == lote_rev.id,
                m.Separacion.id != sep.id,
                m.Separacion.estado.in_(svc.ESTADOS_ACTIVOS),
            )
            .first()
        )
        if otra_rev:
            raise _conflicto(f"El lote {lote_rev.codigo} ya tiene otra separación en curso")
        if lote_rev.estado != LOTE.libre and not svc.PERMITIR_SEPARAR_LOTES_OCUPADOS:
            raise _conflicto(f"El lote {lote_rev.codigo} ya no está libre (estado: {lote_rev.estado.value})")
        sep.estado = E.pendiente_caja
        sep.motivo_rechazo = None
        sep.validado_por = None
        sep.fecha_validacion = None
        destinatarios = svc.usuarios_por_roles(
            db, sep.id_empresa, sep.id_proyecto, ["caja", "admin"], excluir_id=usuario.id
        )
        notifs = svc.crear_notificaciones(
            db, sep.id_empresa, destinatarios,
            "separacion_pendiente_caja",
            "Separación corregida: validar de nuevo",
            f"{usuario.nombre} corrigió la separación del lote {lote_rev.codigo} por S/ {sep.importe:,.2f}",
            {"id_separacion": sep.id, "id_proyecto": sep.id_proyecto, "id_lote": sep.id_lote, "estado": "pendiente_caja"},
        )


    nueva_venc = datos.get("fecha_vencimiento")
    # Prórroga: una separación vencida con el lote aún separado vuelve a vigente
    if (
        sep.estado == E.vencida
        and nueva_venc is not None
        and nueva_venc >= svc.hoy_peru()
        and (nuevo_lote or sep.lote).estado == LOTE.separado
    ):
        sep.estado = E.vigente

    db.commit()
    await _emitir(db, sep, usuario, notifs, cambio_lote=cambio_lotes)
    if cambio_lotes:
        await notificar_cambio_estado_lote(
            svc.lote_out_dict(db, id_lote_ant),
            id_proyecto=lote_ant.id_proyecto,
            id_empresa=usuario.id_empresa,
        )
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
    if sep.lote.estado != LOTE.libre and not svc.PERMITIR_SEPARAR_LOTES_OCUPADOS:
        raise _conflicto(
            f"El lote {sep.lote.codigo} ya no está libre (estado: {sep.lote.estado.value}). Rechaza esta separación."
        )
    sep.estado = E.pendiente_facturacion
    sep.validado_por = usuario.id
    sep.fecha_validacion = svc.ahora_utc()
    sep.motivo_rechazo = None


    aud.registrar(
        db, usuario, "separacion", sep.id, "validar_caja",
        {"id_lote": sep.id_lote, "importe": str(sep.importe), "voucher_numero": sep.voucher_numero},
    )
    # Lote libre → pasa a separado. Si es carga histórica sobre un lote ocupado, conserva su estado.
    cambio = False
    if sep.lote.estado == LOTE.libre:
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

    


    aud.registrar(
        db, usuario, "separacion", sep.id, "rechazar_caja",
        {"id_lote": sep.id_lote, "importe": str(sep.importe), "motivo": motivo},
    )


    # La proforma que originó esta separación vuelve a quedar disponible
    db.query(m.Proforma).filter(m.Proforma.id_separacion == sep.id).update(
        {m.Proforma.estado: "emitida", m.Proforma.id_separacion: None}, synchronize_session=False
    )
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
    usuario: m.Usuario = Depends(require_permiso("facturar_pago")),
    db: Session = Depends(get_db),
):
    sep = svc.cargar_separacion(db, id_separacion, usuario)
    # Facturación puede subir el comprobante mientras esté pendiente, o después
    # si la separación ya fue convertida y quedó sin comprobante.
    sin_comprobante = not sep.comprobantes
    if sep.estado != E.pendiente_facturacion and not (sep.estado == E.convertida and sin_comprobante):
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
    ya_convertida = sep.estado == E.convertida
    if not ya_convertida:
        sep.estado = E.vigente

    aud.registrar(
        db, usuario, "separacion", sep.id, "facturar",
        {"id_lote": sep.id_lote, "tipo": tipo, "numero": numero, "importe": str(sep.importe)},
    )

    estado_notif = "convertida" if ya_convertida else "vigente"
    notifs = svc.crear_notificaciones(
        db, sep.id_empresa, svc.unicos([sep.ejecutivo], excluir_id=usuario.id),
        "separacion_vigente",
        "Comprobante emitido",
        f"Lote {sep.lote.codigo}: {tipo} {numero}."
        + ("" if ya_convertida else " La separación está vigente."),
        {"id_separacion": sep.id, "id_proyecto": sep.id_proyecto, "id_lote": sep.id_lote, "estado": estado_notif},
    )
    db.commit()

    await _emitir(db, sep, usuario, notifs)
    return _detalle(db, id_separacion, usuario)




@router.post("/{id_separacion}/rechazar-facturacion", response_model=s.SeparacionOut)
async def rechazar_facturacion(
    id_separacion: int,
    payload: s.SeparacionRechazo,
    usuario: m.Usuario = Depends(require_permiso("facturar_pago")),
    db: Session = Depends(get_db),
):
    sep = svc.cargar_separacion(db, id_separacion, usuario)
    if sep.estado != E.pendiente_facturacion:
        raise _conflicto("Esta separación no está pendiente de comprobante")
    motivo = payload.motivo.strip()
    if not motivo:
        raise HTTPException(status_code=422, detail="Debes indicar el motivo del rechazo")

    sep.estado = E.rechazada
    sep.motivo_rechazo = motivo

    aud.registrar(
        db, usuario, "separacion", sep.id, "rechazar_facturacion",
        {"id_lote": sep.id_lote, "importe": str(sep.importe), "motivo": motivo},
    )


    db.query(m.Proforma).filter(m.Proforma.id_separacion == sep.id).update(
        {m.Proforma.estado: "emitida", m.Proforma.id_separacion: None}, synchronize_session=False
    )
    # Caja ya lo había puesto 'separado': se libera; al reenviar y revalidar Caja vuelve a separarlo
    cambio = False
    if sep.lote.estado == LOTE.separado:
        cambio = svc.cambiar_estado_lote(
            db, sep.lote, LOTE.libre, usuario, f"Separación #{sep.id} rechazada por Facturación"
        )
    notifs = svc.crear_notificaciones(
        db, sep.id_empresa, svc.unicos([sep.ejecutivo], excluir_id=usuario.id),
        "separacion_rechazada",
        "Separación rechazada por Facturación",
        f"Lote {sep.lote.codigo}: {motivo}. Corrígela y reenvíala a Caja.",
        {"id_separacion": sep.id, "id_proyecto": sep.id_proyecto, "id_lote": sep.id_lote, "estado": "rechazada"},
    )
    db.commit()
    await _emitir(db, sep, usuario, notifs, cambio_lote=cambio)
    return _detalle(db, id_separacion, usuario)


CAMPOS_REENVIO = {
    "fecha_inicio", "fecha_vencimiento", "importe", "motivo", "tipo_pago", "notas", "agenda_fecha",
    "dni_frente_url", "dni_reverso_url", "voucher_url", "voucher_numero", "medio_pago",
    "proforma_url", "precio_valido_hasta", "precio_descontado",
}


@router.post("/{id_separacion}/reenviar", response_model=s.SeparacionOut)
async def reenviar_separacion(
    id_separacion: int,
    payload: s.SeparacionUpdate,
    usuario: m.Usuario = Depends(require_permiso("editar_separacion")),
    db: Session = Depends(get_db),
):
    """Corrige una separación rechazada (Caja o Facturación) y la devuelve a Caja."""
    sep = svc.cargar_separacion(db, id_separacion, usuario)
    if sep.estado != E.rechazada:
        raise _conflicto("Solo se puede reenviar una separación rechazada")
    if sep.id_ejecutivo != usuario.id and usuario.rol.clave not in ("admin", "gerencia", "supervisor"):
        raise HTTPException(status_code=403, detail="Solo quien registró la separación puede corregirla")

    datos = {
        k: v for k, v in payload.model_dump(exclude_unset=True).items()
        if k in CAMPOS_REENVIO and not (v is None and k in CAMPOS_OBLIGATORIOS)
    }
    cambios = aud.diferencias({c: getattr(sep, c) for c in datos}, datos)
    if not cambios:
        raise HTTPException(status_code=422, detail="Corrige lo observado (voucher, importe, fechas, etc.) antes de reenviar")

    lote = db.query(m.Lote).filter(m.Lote.id == sep.id_lote).with_for_update().first()
    if lote.estado != LOTE.libre and not svc.PERMITIR_SEPARAR_LOTES_OCUPADOS:
        raise _conflicto(f"El lote {lote.codigo} ya no está libre (estado: {lote.estado.value})")
    otra = (
        db.query(m.Separacion.id)
        .filter(m.Separacion.id_lote == lote.id, m.Separacion.id != sep.id, m.Separacion.estado.in_(svc.ESTADOS_ACTIVOS))
        .first()
    )
    if otra:
        raise _conflicto("Este lote ya tiene otra separación en curso")

    aud.registrar(db, usuario, "separacion", sep.id, "corregir_rechazo",
                  {"motivo_rechazo_previo": sep.motivo_rechazo, **cambios})
    for campo, valor in datos.items():
        setattr(sep, campo, valor)
    sep.estado = E.pendiente_caja
    sep.motivo_rechazo = None
    sep.validado_por = None
    sep.fecha_validacion = None

    destinatarios = svc.usuarios_por_roles(
        db, sep.id_empresa, sep.id_proyecto, ["caja", "admin"], excluir_id=usuario.id
    )
    notifs = svc.crear_notificaciones(
        db, sep.id_empresa, destinatarios,
        "separacion_pendiente_caja",
        "Separación corregida: validar de nuevo",
        f"{usuario.nombre} corrigió la separación del lote {lote.codigo} por S/ {sep.importe:,.2f}",
        {"id_separacion": sep.id, "id_proyecto": sep.id_proyecto, "id_lote": sep.id_lote, "estado": "pendiente_caja"},
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _conflicto("Este lote ya tiene una separación en curso")
    await _emitir(db, sep, usuario, notifs)
    return _detalle(db, id_separacion, usuario)


class ComprobanteUpdate(BaseModel):
    tipo: Optional[str] = None
    numero: Optional[str] = None
    archivo_url: Optional[str] = None


@router.patch("/{id_separacion}/comprobante/{id_comprobante}", response_model=s.SeparacionOut)
async def editar_comprobante(
    id_separacion: int,
    id_comprobante: int,
    payload: ComprobanteUpdate,
    usuario: m.Usuario = Depends(require_permiso("emitir_comprobante")),
    db: Session = Depends(get_db),
):
    if not svc.PERMITIR_EDITAR_TODO:
        raise _conflicto("La edición de comprobantes está deshabilitada")
    sep = svc.cargar_separacion(db, id_separacion, usuario)
    comp = next((c for c in sep.comprobantes if c.id == id_comprobante), None)
    if not comp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comprobante no encontrado")

    datos = payload.model_dump(exclude_unset=True)
    if "tipo" in datos:
        datos["tipo"] = (datos["tipo"] or "").strip().lower()
        if datos["tipo"] not in ("boleta", "factura", "recibo"):
            raise HTTPException(status_code=422, detail="El tipo debe ser boleta, factura o recibo")
    if "numero" in datos:
        datos["numero"] = (datos["numero"] or "").strip()
        if not datos["numero"]:
            raise HTTPException(status_code=422, detail="El número de comprobante es obligatorio")


    cambios = aud.diferencias({c: getattr(comp, c) for c in datos}, datos)
    if cambios:
        aud.registrar(db, usuario, "comprobante", comp.id, "editar", {"id_separacion": sep.id, **cambios})   

    for campo, valor in datos.items():
        setattr(comp, campo, valor)
    db.commit()

    await _emitir(db, sep, usuario, [])
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
    estado_anterior = sep.estado

    if svc.PERMITIR_EDITAR_TODO:
        # Carga de data histórica: se puede convertir desde cualquier estado previo a la venta
        permitidos = (E.pendiente_caja, E.pendiente_facturacion, E.vigente, E.vencida)
        if sep.estado not in permitidos:
            raise _conflicto("Esta separación ya no se puede convertir en compra")
    elif sep.estado == E.vencida:
        # Operación normal: una vencida solo la convierte admin/gerencia y con el lote aún separado
        if usuario.rol.clave not in ("admin", "gerencia"):
            raise _conflicto("Solo admin o gerencia pueden convertir una separación vencida")
        if sep.lote.estado != LOTE.separado:
            raise _conflicto(
                f"El lote {sep.lote.codigo} ya no está separado (estado: {sep.lote.estado.value}). "
                "No se puede convertir esta separación vencida"
            )
    elif sep.estado != E.vigente:
        raise _conflicto("Solo una separación vigente o vencida puede convertirse en compra")

    if not sep.contrato_firmado_url:
        raise _conflicto("Debes subir el contrato de separación firmado antes de convertir la separación en venta")
    if estado_anterior == E.pendiente_facturacion and not sep.comprobantes:
        raise _conflicto("Facturación debe subir el comprobante antes de convertir la separación en venta")

    sep.estado = E.convertida
    sep.fecha_conversion = fecha_conversion or svc.hoy_peru()
    aud.registrar(
        db, usuario, "separacion", sep.id,
        "convertir_historica" if estado_anterior != E.vigente else "convertir",
        {"estado_anterior": estado_anterior.value, "id_lote": sep.id_lote},
    )
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
    if sep.estado in svc.ESTADOS_CERRADOS and not svc.PERMITIR_EDITAR_TODO:
        raise _conflicto("La separación ya está cerrada, no se puede generar la proforma")

    sep.proforma_url = svc.generar_documento(db, sep, con_clausulas=False)
    db.commit()

    await _emitir(db, sep, usuario, [])
    return _detalle(db, id_separacion, usuario)


@router.post("/{id_separacion}/contrato", response_model=s.SeparacionOut)
async def generar_contrato(
    id_separacion: int,
    usuario: m.Usuario = Depends(require_permiso("facturar_pago")),
    db: Session = Depends(get_db),
):
    sep = svc.cargar_separacion(db, id_separacion, usuario)
    if sep.estado in svc.ESTADOS_CERRADOS and not svc.PERMITIR_EDITAR_TODO:
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
    ya_devuelto = sum((d.monto for d in sep.devoluciones if d.estado in DEV_APROBADAS), Decimal("0"))
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


    aud.registrar(
        db, usuario, "separacion", sep.id, "solicitar_devolucion",
        {"monto": str(payload.monto), "sustento": sustento, "continua_venta": payload.continua_venta},
    )


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

    aud.registrar(
        db, usuario, "separacion", sep.id, "resolver_devolucion",
        {"id_devolucion": dev.id, "aprobada": payload.aprobar, "monto": str(dev.monto), "respuesta": payload.respuesta},
    )

    # Compatibilidad: separaciones que quedaron en 'devolucion_pendiente' con el flujo anterior
    if sep.estado == E.devolucion_pendiente:
        sep.estado = E.vencida if sep.fecha_vencimiento < svc.hoy_peru() else E.vigente

    cambio = False
    if payload.aprobar:
        dev.estado = "pendiente_caja"
        total_devuelto = sum((d.monto for d in sep.devoluciones if d.estado in DEV_APROBADAS), Decimal("0"))
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

    if payload.aprobar:
        notifs += svc.crear_notificaciones(
            db, sep.id_empresa,
            svc.usuarios_por_roles(db, sep.id_empresa, sep.id_proyecto, ["caja", "admin"], excluir_id=usuario.id),
            "devolucion_pendiente_caja",
            "Devolución por ejecutar",
            f"Lote {sep.lote.codigo}: devolver S/ {dev.monto:,.2f} al cliente y registrar el voucher.",
            {"id_separacion": sep.id, "id_devolucion": dev.id, "id_proyecto": sep.id_proyecto,
                "id_lote": sep.id_lote, "estado": "pendiente_caja"},
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
    total_devuelto = sum((d.monto for d in sep.devoluciones if d.estado in DEV_APROBADAS), Decimal("0"))
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

    aud.registrar(
        db, usuario, "separacion", sep.id, "liberar_lote",
        {"id_lote": sep.id_lote, "devuelta_por_completo": ya_devuelta},
    )
        
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


# ------------------------------------- devolución: Caja y Facturación --

def _cargar_devolucion(db: Session, id_devolucion: int, usuario: m.Usuario):
    dev = db.query(m.Devolucion).filter(m.Devolucion.id == id_devolucion).first()
    if not dev:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Devolución no encontrada")
    sep = svc.cargar_separacion(db, dev.id_separacion, usuario)  # valida empresa y proyecto
    return dev, sep


@router.post("/devoluciones/{id_devolucion}/ejecutar", response_model=s.SeparacionOut)
async def ejecutar_devolucion(
    id_devolucion: int,
    payload: s.DevolucionEjecutar,
    usuario: m.Usuario = Depends(require_permiso("validar_pago")),
    db: Session = Depends(get_db),
):
    """Caja devolvió el dinero al cliente: registra N° de operación y voucher."""
    dev, sep = _cargar_devolucion(db, id_devolucion, usuario)
    if dev.estado != "pendiente_caja":
        raise _conflicto("Esta devolución no está pendiente de Caja")
    numero = payload.numero_operacion.strip()
    if not numero or not payload.voucher_url:
        raise HTTPException(status_code=422, detail="Indica el N° de operación y sube el voucher de la devolución")

    dev.estado = "pendiente_facturacion"
    dev.numero_operacion = numero
    dev.voucher_url = payload.voucher_url
    dev.metodo_pago = (payload.metodo_pago or "").strip() or None
    dev.ejecutado_por = usuario.id
    dev.fecha_ejecucion = svc.ahora_utc()
    aud.registrar(
        db, usuario, "devolucion", dev.id, "ejecutar_caja",
        {"id_separacion": sep.id, "monto": str(dev.monto), "numero_operacion": numero, "voucher_url": payload.voucher_url},
    )
    destinatarios = svc.unicos(
        svc.usuarios_por_roles(db, sep.id_empresa, sep.id_proyecto, ["facturacion", "admin"]) + [sep.ejecutivo],
        excluir_id=usuario.id,
    )
    notifs = svc.crear_notificaciones(
        db, sep.id_empresa, destinatarios,
        "devolucion_pendiente_facturacion",
        "Devolución realizada: emitir nota de crédito",
        f"Lote {sep.lote.codigo}: Caja devolvió S/ {dev.monto:,.2f}. Falta la nota de crédito.",
        {"id_separacion": sep.id, "id_devolucion": dev.id, "id_proyecto": sep.id_proyecto,
         "id_lote": sep.id_lote, "estado": "pendiente_facturacion"},
    )
    db.commit()
    await _emitir(db, sep, usuario, notifs)
    return _detalle(db, sep.id, usuario)


@router.post("/devoluciones/{id_devolucion}/nota-credito", response_model=s.SeparacionOut)
async def nota_credito_devolucion(
    id_devolucion: int,
    payload: s.DevolucionNotaCredito,
    usuario: m.Usuario = Depends(require_permiso("facturar_pago")),
    db: Session = Depends(get_db),
):
    """Facturación sube la nota de crédito: la devolución queda completada."""
    dev, sep = _cargar_devolucion(db, id_devolucion, usuario)
    if dev.estado != "pendiente_facturacion":
        raise _conflicto("Esta devolución no está pendiente de nota de crédito")
    numero = payload.numero.strip()
    if not numero or not payload.archivo_url:
        raise HTTPException(status_code=422, detail="Indica el número y sube el archivo de la nota de crédito")

    dev.estado = "completada"
    dev.nota_credito_numero = numero
    dev.nota_credito_url = payload.archivo_url
    dev.nota_credito_por = usuario.id
    dev.fecha_nota_credito = svc.ahora_utc()
    aud.registrar(
        db, usuario, "devolucion", dev.id, "emitir_nota_credito",
        {"id_separacion": sep.id, "monto": str(dev.monto), "numero": numero},
    )
    destinatarios = svc.unicos(
        [sep.ejecutivo] + svc.usuarios_por_roles(db, sep.id_empresa, sep.id_proyecto, ["gerencia", "admin"]),
        excluir_id=usuario.id,
    )
    notifs = svc.crear_notificaciones(
        db, sep.id_empresa, destinatarios,
        "devolucion_completada",
        "Devolución completada",
        f"Lote {sep.lote.codigo}: S/ {dev.monto:,.2f} devueltos. Nota de crédito {numero}.",
        {"id_separacion": sep.id, "id_devolucion": dev.id, "id_proyecto": sep.id_proyecto,
         "id_lote": sep.id_lote, "estado": "completada"},
    )
    db.commit()
    await _emitir(db, sep, usuario, notifs)
    return _detalle(db, sep.id, usuario)