import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.deps import require_permiso
from app.models import models as m
from app.schemas import schemas as s
from app.services import reglas_venta as reglas
from app.services import separacion_service as sep_svc
from app.services import venta_service as svc
from app.sockets import (
    notificar_venta,
    notificar_cambio_estado_lote,
    notificar_nuevo_contrato,
    notificar_usuarios,
    notificar_pago,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ventas", tags=["ventas"])


def _resumen_socket(venta: m.Venta) -> dict:
    return {"id": venta.id, "id_lote": venta.id_lote, "estado": venta.estado.value}


async def _emitir_contrato_creado(db: Session, id_contrato: int, venta: m.Venta, usuario: m.Usuario):
    """Tiempo real: venta nueva + contrato nuevo + lote vendido. Si falla, NO rompe la operación."""
    try:
        contrato = (
            db.query(m.Contrato)
            .options(
                joinedload(m.Contrato.lote),
                joinedload(m.Contrato.clientes_rel).joinedload(m.ContratoCliente.cliente),
            )
            .filter(m.Contrato.id == id_contrato)
            .first()
        )
        await notificar_venta("venta:nueva", _resumen_socket(venta), id_proyecto=venta.id_proyecto)
        await notificar_nuevo_contrato(
            s.ContratoOut.desde_contrato(contrato).model_dump(mode="json"),
            id_proyecto=venta.id_proyecto, id_empresa=usuario.id_empresa,
        )
        await notificar_cambio_estado_lote(
            sep_svc.lote_out_dict(db, venta.id_lote),
            id_proyecto=venta.id_proyecto, id_empresa=usuario.id_empresa,
        )
        if venta.forma_pago == m.FormaPagoEnum.credito:
            await _avisar_roles(
                db, usuario, venta, ["cobranza", "admin"],
                "venta_credito_nueva", "Nuevo contrato a crédito",
                f"Lote {venta.lote.codigo if venta.lote else ''}: ya puedes iniciar el seguimiento de cobranza.",
            )
        # La inicial (crédito) o el pago al contado lo debe validar Caja
        concepto_ini = "Pago al contado" if venta.forma_pago == m.FormaPagoEnum.contado else "Inicial"
        await _avisar_roles(
            db, usuario, venta, ["caja", "admin"],
            "pago_pendiente_caja", f"{concepto_ini} por validar",
            f"Contrato {contrato.numero_contrato}, lote {venta.lote.codigo if venta.lote else ''}: "
            f"{concepto_ini.lower()} pendiente de validación de Caja.",
        )
        await notificar_pago(
            "pago:actualizado",
            {
                "id_contrato": id_contrato,
                "estado": "pendiente_caja",
                "concepto": concepto_ini,
                "numero_contrato": contrato.numero_contrato,
            },
            venta.id_proyecto,
            [],
        )
    except Exception:
        logger.exception("No se pudo emitir el aviso en tiempo real del contrato %s", id_contrato)


async def _avisar_roles(db: Session, usuario: m.Usuario, venta: m.Venta, roles: list[str],
                        tipo: str, titulo: str, mensaje: str):
    """Notificación (campana + sonido) a los usuarios de esos roles. Si falla no rompe la operación."""
    try:
        destinatarios = sep_svc.usuarios_por_roles(
            db, usuario.id_empresa, venta.id_proyecto, roles, excluir_id=usuario.id
        )
        notifs = sep_svc.crear_notificaciones(
            db, usuario.id_empresa, destinatarios, tipo, titulo, mensaje,
            {"id_venta": venta.id, "id_proyecto": venta.id_proyecto, "id_lote": venta.id_lote},
        )
        db.commit()
        await notificar_usuarios(sep_svc.notificaciones_a_dict(notifs))
    except Exception:
        db.rollback()
        logger.exception("No se pudo notificar a %s por la venta %s", roles, venta.id)


# ----------------------------------------------------------------- helpers --

def _exigir_inicial_validada(db: Session, venta: m.Venta):
    """No se genera Minuta / Contrato Preparatorio hasta que Caja y Facturación validen la inicial."""
    if not venta.id_contrato:
        return
    estados = [
        e for (e,) in db.query(m.Pago.estado)
        .filter(
            m.Pago.id_contrato == venta.id_contrato,
            m.Pago.tipo.in_(["inicial", "contado"]),
        )
        .all()
    ]
    if not estados:
        return  # ventas antiguas sin pagos de inicial registrados
    if any(e in ("pendiente_caja", "pendiente_facturacion") for e in estados) or "validado" not in estados:
        raise HTTPException(
            status_code=409,
            detail="La inicial aún no está validada por Caja y Facturación. No se puede generar el documento.",
        )


def _separacion_convertida(db: Session, usuario: m.Usuario, id_separacion: int) -> m.Separacion:
    sep = sep_svc.cargar_separacion(db, id_separacion, usuario)
    if sep.estado != m.EstadoSeparacionEnum.convertida:
        raise HTTPException(status_code=409, detail="La separación debe estar convertida antes de iniciar la venta")
    return sep


def _datos_credito(payload: s.VentaCreate) -> dict | None:
    return payload.datos_credito.model_dump(mode="json") if payload.datos_credito else None


def _evaluar(sep: m.Separacion, payload: s.VentaCreate) -> dict:
    dc = _datos_credito(payload)
    reglas.validar_estructura(payload.forma_pago, payload.precio_total, dc)
    return reglas.evaluar(payload.precio_total, payload.forma_pago, dc, sep.lote, sep.precio_descontado)


async def _crear_venta(db: Session, usuario: m.Usuario, sep: m.Separacion, payload: s.VentaCreate) -> m.Venta:
    """Crea la venta, sus compradores y el contrato (con cronograma). No evalúa reglas."""
    if db.query(m.Venta).filter(m.Venta.id_separacion == sep.id).first():
        raise HTTPException(status_code=409, detail="Esta separación ya tiene una venta iniciada")

    clientes_in = payload.clientes or [s.VentaClienteIn(id_cliente=sep.id_cliente)]
    if len(clientes_in) > 4:
        raise HTTPException(status_code=422, detail="Una venta admite como máximo 4 compradores")
    ids = [i.id_cliente for i in clientes_in if i.id_cliente]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail="Un mismo cliente no puede figurar dos veces como comprador")

    venta = m.Venta(
        id_empresa=usuario.id_empresa,
        id_proyecto=sep.id_proyecto,
        id_lote=sep.id_lote,
        id_separacion=sep.id,
        forma_pago=payload.forma_pago,
        precio_total=payload.precio_total,
        id_usuario_registro=usuario.id,
        pagos_previos=[p.model_dump(mode="json") for p in payload.pagos_previos] if payload.pagos_previos else None,
        datos_credito=_datos_credito(payload),
    )
    db.add(venta)
    db.flush()

    for item in clientes_in:
        if item.id_cliente:
            cliente = db.query(m.Cliente).filter(
                m.Cliente.id == item.id_cliente, m.Cliente.id_empresa == usuario.id_empresa
            ).first()
            if not cliente:
                raise HTTPException(status_code=404, detail=f"Cliente {item.id_cliente} no encontrado")
        elif item.cliente_nuevo:
            cliente = m.Cliente(id_empresa=usuario.id_empresa, **item.cliente_nuevo.model_dump(exclude={"conyuge"}))
            db.add(cliente)
            db.flush()
        else:
            raise HTTPException(status_code=422, detail="Cada comprador requiere id_cliente o cliente_nuevo")
        db.add(m.VentaCliente(id_venta=venta.id, id_cliente=cliente.id, rol=item.rol))

    db.flush()  # sin commit todavía: venta y contrato se guardan juntos o no se guarda nada

    # El contrato se crea ahora: aparece en Ventas y Contratos y el lote pasa a vendido
    venta_completa = svc.cargar_venta(db, venta.id, usuario)
    contrato = svc.generar_contrato_desde_venta(db, venta_completa, usuario)
    db.commit()

    venta_completa = svc.cargar_venta(db, venta.id, usuario)
    await _emitir_contrato_creado(db, contrato.id, venta_completa, usuario)
    return venta_completa


def _cargar_autorizacion(db: Session, usuario: m.Usuario, id_autorizacion: int) -> m.AutorizacionVenta:
    aut = (
        db.query(m.AutorizacionVenta)
        .options(joinedload(m.AutorizacionVenta.solicitante), joinedload(m.AutorizacionVenta.resolutor))
        .filter(m.AutorizacionVenta.id == id_autorizacion, m.AutorizacionVenta.id_empresa == usuario.id_empresa)
        .first()
    )
    if not aut:
        raise HTTPException(status_code=404, detail="Autorización no encontrada")
    svc.validar_acceso_proyecto(db, usuario, aut.id_proyecto)
    return aut


# ------------------------------------------------------- evaluar / crear ----

@router.post("/evaluar/{id_separacion}", response_model=s.EvaluacionVentaOut)
def evaluar_venta(
    id_separacion: int,
    payload: s.VentaCreate,
    usuario: m.Usuario = Depends(require_permiso("crear_venta")),
    db: Session = Depends(get_db),
):
    """Vista previa: reglas incumplidas, cuotas, interés y cuota estimada. No guarda nada."""
    sep = _separacion_convertida(db, usuario, id_separacion)
    return s.EvaluacionVentaOut(**_evaluar(sep, payload))


@router.post("/desde-separacion/{id_separacion}", response_model=s.VentaOut, status_code=status.HTTP_201_CREATED)
async def crear_venta_desde_separacion(
    id_separacion: int,
    payload: s.VentaCreate,
    usuario: m.Usuario = Depends(require_permiso("crear_venta")),
    db: Session = Depends(get_db),
):
    sep = _separacion_convertida(db, usuario, id_separacion)
    evaluacion = _evaluar(sep, payload)
    if evaluacion["motivos"]:
        detalle = "; ".join(mo["mensaje"] for mo in evaluacion["motivos"])
        raise HTTPException(status_code=409, detail=f"Estas condiciones requieren autorización de gerencia: {detalle}")

    venta = await _crear_venta(db, usuario, sep, payload)
    return s.VentaOut.desde_venta(venta)


# ---------------------------------------------------------- autorizaciones --

@router.post("/solicitar-autorizacion/{id_separacion}", response_model=s.AutorizacionVentaOut, status_code=status.HTTP_201_CREATED)
async def solicitar_autorizacion(
    id_separacion: int,
    payload: s.VentaCreate,
    usuario: m.Usuario = Depends(require_permiso("crear_venta")),
    db: Session = Depends(get_db),
):
    sep = _separacion_convertida(db, usuario, id_separacion)
    if db.query(m.Venta).filter(m.Venta.id_separacion == sep.id).first():
        raise HTTPException(status_code=409, detail="Esta separación ya tiene una venta iniciada")

    evaluacion = _evaluar(sep, payload)
    if not evaluacion["motivos"]:
        raise HTTPException(status_code=422, detail="Estas condiciones no requieren autorización: inicia la venta directamente")

    pendiente = db.query(m.AutorizacionVenta).filter(
        m.AutorizacionVenta.id_separacion == sep.id, m.AutorizacionVenta.estado == "pendiente"
    ).first()
    if pendiente:
        raise HTTPException(status_code=409, detail="Ya hay una solicitud de autorización pendiente para esta separación")

    aut = m.AutorizacionVenta(
        id_empresa=usuario.id_empresa,
        id_proyecto=sep.id_proyecto,
        id_separacion=sep.id,
        solicitado_por=usuario.id,
        estado="pendiente",
        motivos=evaluacion["motivos"],
        propuesta=payload.model_dump(mode="json"),
    )
    db.add(aut)
    db.flush()

    destinatarios = sep_svc.usuarios_por_roles(
        db, usuario.id_empresa, sep.id_proyecto, ["gerencia", "admin"], excluir_id=usuario.id
    )
    notifs = sep_svc.crear_notificaciones(
        db, usuario.id_empresa, destinatarios,
        "autorizacion_pendiente",
        "Autorización de venta por aprobar",
        f"{usuario.nombre} solicita autorización para el lote {sep.lote.codigo}: "
        + "; ".join(mo["mensaje"] for mo in evaluacion["motivos"]),
        {"id_separacion": sep.id, "id_proyecto": sep.id_proyecto, "id_autorizacion": aut.id},
    )
    db.commit()

    await notificar_venta("autorizacion:actualizada", {"id_separacion": sep.id, "estado": "pendiente"}, id_proyecto=sep.id_proyecto)
    await notificar_usuarios(sep_svc.notificaciones_a_dict(notifs))
    return s.AutorizacionVentaOut.desde_autorizacion(_cargar_autorizacion(db, usuario, aut.id))


@router.get("/autorizaciones", response_model=list[s.AutorizacionVentaOut])
def listar_autorizaciones(
    id_separacion: int,
    usuario: m.Usuario = Depends(require_permiso("ver_ventas")),
    db: Session = Depends(get_db),
):
    sep_svc.cargar_separacion(db, id_separacion, usuario)  # valida acceso
    lista = (
        db.query(m.AutorizacionVenta)
        .options(joinedload(m.AutorizacionVenta.solicitante), joinedload(m.AutorizacionVenta.resolutor))
        .filter(m.AutorizacionVenta.id_separacion == id_separacion, m.AutorizacionVenta.id_empresa == usuario.id_empresa)
        .order_by(m.AutorizacionVenta.created_at.desc())
        .all()
    )
    return [s.AutorizacionVentaOut.desde_autorizacion(a) for a in lista]


@router.post("/autorizaciones/{id_autorizacion}/resolver", response_model=s.AutorizacionVentaOut)
async def resolver_autorizacion(
    id_autorizacion: int,
    payload: s.AutorizacionResolver,
    usuario: m.Usuario = Depends(require_permiso("aprobar_autorizacion")),
    db: Session = Depends(get_db),
):
    aut = _cargar_autorizacion(db, usuario, id_autorizacion)
    if aut.estado != "pendiente":
        raise HTTPException(status_code=409, detail="Esta solicitud ya fue resuelta")

    aut.estado = "aprobada" if payload.aprobar else "rechazada"
    aut.respuesta = (payload.respuesta or "").strip() or None
    aut.resuelto_por = usuario.id
    aut.resuelto_at = sep_svc.ahora_utc()

    sep = db.query(m.Separacion).options(joinedload(m.Separacion.lote)).filter(m.Separacion.id == aut.id_separacion).first()
    notifs = sep_svc.crear_notificaciones(
        db, usuario.id_empresa, sep_svc.unicos([aut.solicitante], excluir_id=usuario.id),
        "autorizacion_resuelta",
        "Autorización aprobada" if payload.aprobar else "Autorización rechazada",
        f"Lote {sep.lote.codigo if sep and sep.lote else ''}"
        + (f": {aut.respuesta}" if aut.respuesta else (". Ya puedes crear la venta." if payload.aprobar else ".")),
        {"id_separacion": aut.id_separacion, "id_proyecto": aut.id_proyecto, "id_autorizacion": aut.id},
    )
    db.commit()

    await notificar_venta("autorizacion:actualizada", {"id_separacion": aut.id_separacion, "estado": aut.estado}, id_proyecto=aut.id_proyecto)
    await notificar_usuarios(sep_svc.notificaciones_a_dict(notifs))
    return s.AutorizacionVentaOut.desde_autorizacion(_cargar_autorizacion(db, usuario, id_autorizacion))


@router.post("/autorizaciones/{id_autorizacion}/crear-venta", response_model=s.VentaOut, status_code=status.HTTP_201_CREATED)
async def crear_venta_autorizada(
    id_autorizacion: int,
    usuario: m.Usuario = Depends(require_permiso("crear_venta")),
    db: Session = Depends(get_db),
):
    """Crea la venta con EXACTAMENTE las condiciones que gerencia aprobó."""
    aut = _cargar_autorizacion(db, usuario, id_autorizacion)
    if aut.estado != "aprobada":
        raise HTTPException(status_code=409, detail="Esta autorización no está aprobada o ya fue utilizada")
    if aut.solicitado_por != usuario.id and usuario.rol.clave not in ("admin", "gerencia"):
        raise HTTPException(status_code=403, detail="Solo quien solicitó la autorización puede crear la venta")

    sep = _separacion_convertida(db, usuario, aut.id_separacion)
    venta = await _crear_venta(db, usuario, sep, s.VentaCreate(**aut.propuesta))

    aut.estado = "usada"
    aut.id_venta = venta.id
    db.commit()
    return s.VentaOut.desde_venta(venta)


# ----------------------------------------------------------------- consultas --

@router.get("/por-separacion/{id_separacion}")
def venta_de_separacion(
    id_separacion: int,
    usuario: m.Usuario = Depends(require_permiso("ver_ventas")),
    db: Session = Depends(get_db),
):
    venta = db.query(m.Venta).filter(
        m.Venta.id_separacion == id_separacion,
        m.Venta.id_empresa == usuario.id_empresa,
    ).first()
    return {"id_venta": venta.id if venta else None}


@router.get("/por-contrato/{id_contrato}")
def venta_de_contrato(
    id_contrato: int,
    usuario: m.Usuario = Depends(require_permiso("ver_ventas")),
    db: Session = Depends(get_db),
):
    venta = db.query(m.Venta).filter(
        m.Venta.id_contrato == id_contrato,
        m.Venta.id_empresa == usuario.id_empresa,
    ).first()
    return {"id_venta": venta.id if venta else None}


@router.get("/{id_venta}", response_model=s.VentaOut)
def obtener_venta(
    id_venta: int,
    usuario: m.Usuario = Depends(require_permiso("ver_ventas")),
    db: Session = Depends(get_db),
):
    return s.VentaOut.desde_venta(svc.cargar_venta(db, id_venta, usuario))


# ----------------------------------------------------------------- documentos --

@router.post("/{id_venta}/generar-documento", response_model=s.VentaOut)
async def generar_documento(
    id_venta: int,
    usuario: m.Usuario = Depends(require_permiso("crear_venta")),
    db: Session = Depends(get_db),
):
    venta = svc.cargar_venta(db, id_venta, usuario)
    _exigir_inicial_validada(db, venta)
    pdf_bytes = svc.generar_documento_venta(db, venta)
    venta.documento_generado_url = svc.guardar_documento_pdf(venta.id, pdf_bytes)
    venta.estado = m.EstadoVentaEnum.documento_generado
    db.commit()
    await _avisar_roles(
        db, usuario, venta, ["legal"], "venta_documento_generado", "Documento generado",
        f"Se generó el documento de la venta del lote {venta.lote.codigo if venta.lote else ''}.",
    )
    venta_completa = svc.cargar_venta(db, id_venta, usuario)
    await notificar_venta("venta:actualizada", _resumen_socket(venta_completa), id_proyecto=venta.id_proyecto)
    return s.VentaOut.desde_venta(venta_completa)


@router.post("/{id_venta}/documento-firmado", response_model=s.VentaOut)
async def subir_documento_firmado(
    id_venta: int,
    payload: s.DocumentoFirmadoIn,
    usuario: m.Usuario = Depends(require_permiso("crear_venta")),
    db: Session = Depends(get_db),
):
    venta = svc.cargar_venta(db, id_venta, usuario)
    venta.documento_firmado_url = payload.url
    venta.estado = m.EstadoVentaEnum.documento_firmado
    db.commit()
    await _avisar_roles(
        db, usuario, venta, ["legal"], "venta_documento_firmado", "Documento firmado",
        f"El documento de la venta del lote {venta.lote.codigo if venta.lote else ''} ya está firmado.",
    )
    venta_completa = svc.cargar_venta(db, id_venta, usuario)
    await notificar_venta("venta:actualizada", _resumen_socket(venta_completa), id_proyecto=venta.id_proyecto)
    return s.VentaOut.desde_venta(venta_completa)


@router.post("/{id_venta}/ubicacion-documento", response_model=s.DocumentoUbicacionOut, status_code=status.HTTP_201_CREATED)
async def registrar_ubicacion_documento(
    id_venta: int,
    payload: s.DocumentoUbicacionCreate,
    usuario: m.Usuario = Depends(require_permiso("gestionar_rrpp")),
    db: Session = Depends(get_db),
):
    venta = svc.cargar_venta(db, id_venta, usuario)
    registro = m.DocumentoUbicacion(
        id_venta=venta.id, actualizado_por=usuario.id,
        **payload.model_dump(),
    )
    db.add(registro)
    db.commit()
    db.refresh(registro)
    await notificar_venta("venta:actualizada", _resumen_socket(venta), id_proyecto=venta.id_proyecto)
    return registro


@router.post("/{id_venta}/registrar-contrato", response_model=s.VentaOut)
async def registrar_contrato(
    id_venta: int,
    usuario: m.Usuario = Depends(require_permiso("crear_venta")),
    db: Session = Depends(get_db),
):
    """Para ventas antiguas que quedaron sin contrato."""
    venta = svc.cargar_venta(db, id_venta, usuario)
    contrato = svc.generar_contrato_desde_venta(db, venta, usuario)
    db.commit()

    venta_completa = svc.cargar_venta(db, id_venta, usuario)
    await _emitir_contrato_creado(db, contrato.id, venta_completa, usuario)
    return s.VentaOut.desde_venta(venta_completa)