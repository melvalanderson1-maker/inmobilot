"""Lógica de negocio del módulo de separaciones."""
import io
import os
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException, status
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.config import settings
from app.deps import get_ids_proyectos_usuario
from app.models import models as m
from app.schemas import schemas as s

E = m.EstadoSeparacionEnum

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/app
DIR_PROFORMAS = os.path.join(_BASE_DIR, "static", "proformas")
os.makedirs(DIR_PROFORMAS, exist_ok=True)

ESTADOS_ACTIVOS = (
    E.pendiente_caja,
    E.pendiente_facturacion,
    E.vigente,
    E.devolucion_pendiente,
)
ESTADOS_CERRADOS = (E.convertida, E.devuelta, E.rechazada)

_ZONA_PERU = timezone(timedelta(hours=-5))  # Perú no tiene horario de verano


def hoy_peru() -> date:
    return datetime.now(_ZONA_PERU).date()


def ahora_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def validar_acceso_proyecto(db: Session, usuario: m.Usuario, id_proyecto: int):
    ids_permitidos = get_ids_proyectos_usuario(db, usuario)
    if ids_permitidos is not None and id_proyecto not in ids_permitidos:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a este proyecto")


def cargar_separacion(db: Session, id_separacion: int, usuario: m.Usuario) -> m.Separacion:
    sep = (
        db.query(m.Separacion)
        .options(
            joinedload(m.Separacion.cliente),
            joinedload(m.Separacion.lote),
            joinedload(m.Separacion.ejecutivo),
            joinedload(m.Separacion.validador),
            selectinload(m.Separacion.comprobantes),
            selectinload(m.Separacion.devoluciones),
        )
        .filter(m.Separacion.id == id_separacion, m.Separacion.id_empresa == usuario.id_empresa)
        .first()
    )
    if not sep:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Separación no encontrada")
    validar_acceso_proyecto(db, usuario, sep.id_proyecto)
    if usuario.rol.clave == "ejecutivo_ventas" and sep.id_ejecutivo != usuario.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Esta separación pertenece a otro ejecutivo")
    return sep


# ------------------------------------------------------- notificaciones ---

def unicos(usuarios, excluir_id: int | None = None) -> list[m.Usuario]:
    vistos: set[int] = set()
    resultado = []
    for u in usuarios:
        if u is None or u.id == excluir_id or u.id in vistos:
            continue
        vistos.add(u.id)
        resultado.append(u)
    return resultado


def usuarios_por_roles(
    db: Session, id_empresa: int, id_proyecto: int, claves_roles: list[str], excluir_id: int | None = None
) -> list[m.Usuario]:
    """Usuarios activos de la empresa con alguno de esos roles y acceso al proyecto."""
    usuarios = (
        db.query(m.Usuario)
        .join(m.Rol, m.Usuario.id_rol == m.Rol.id)
        .filter(
            m.Usuario.id_empresa == id_empresa,
            m.Usuario.activo.is_(True),
            m.Rol.clave.in_(claves_roles),
        )
        .all()
    )
    ids_con_acceso = {
        f[0]
        for f in db.query(m.UsuarioProyecto.id_usuario)
        .filter(m.UsuarioProyecto.id_proyecto == id_proyecto)
        .all()
    }
    resultado = []
    for u in usuarios:
        if excluir_id is not None and u.id == excluir_id:
            continue
        if u.rol.clave in ("admin", "gerencia") or u.id in ids_con_acceso:
            resultado.append(u)
    return resultado


def crear_notificaciones(
    db: Session, id_empresa: int, destinatarios: list[m.Usuario],
    tipo: str, titulo: str, mensaje: str, data: dict,
) -> list[m.Notificacion]:
    notifs = []
    for u in destinatarios:
        n = m.Notificacion(
            id_empresa=id_empresa,
            id_usuario_destino=u.id,
            tipo=tipo,
            titulo=titulo,
            mensaje=mensaje[:300],
            data=data,
        )
        db.add(n)
        notifs.append(n)
    return notifs


def notificaciones_a_dict(notifs: list[m.Notificacion]) -> list[dict]:
    """Llamar DESPUÉS del commit (necesita id y created_at)."""
    salida = []
    for n in notifs:
        d = s.NotificacionOut.model_validate(n).model_dump(mode="json")
        d["id_usuario_destino"] = n.id_usuario_destino
        salida.append(d)
    return salida


def resumen_socket(sep: m.Separacion) -> dict:
    """Datos mínimos para el evento en tiempo real (sin DNI, montos ni archivos)."""
    return {"id": sep.id, "id_lote": sep.id_lote, "estado": sep.estado.value}


# ----------------------------------------------------------------- lote ---

def cambiar_estado_lote(
    db: Session, lote: m.Lote, nuevo_estado: m.EstadoLoteEnum, usuario: m.Usuario, observacion: str
) -> bool:
    anterior = lote.estado
    if anterior == nuevo_estado:
        return False
    lote.estado = nuevo_estado
    lote.actualizado_por = usuario.id
    db.add(m.LoteEstadoHistorial(
        id_lote=lote.id,
        estado_anterior=anterior,
        estado_nuevo=nuevo_estado,
        id_usuario=usuario.id,
        observacion=observacion[:300],
    ))
    db.add(m.Notificacion(
        id_empresa=usuario.id_empresa,
        id_usuario_destino=None,
        tipo="cambio_estado_lote",
        titulo=f"Lote {lote.codigo} cambió a {nuevo_estado.value}",
        mensaje=observacion[:300],
        data={
            "id_lote": lote.id,
            "id_proyecto": lote.id_proyecto,
            "estado": nuevo_estado.value,
            "id_usuario_accion": usuario.id,
            "usuario_accion_nombre": usuario.nombre,
        },
    ))
    return True


def lote_out_dict(db: Session, id_lote: int) -> dict:
    lote = (
        db.query(m.Lote)
        .options(
            joinedload(m.Lote.imagenes),
            joinedload(m.Lote.usuario_creador),
            joinedload(m.Lote.usuario_actualizador),
        )
        .filter(m.Lote.id == id_lote)
        .first()
    )
    return s.LoteOut.desde_lote(lote).model_dump(mode="json")


# ------------------------------------------------------------- vencidas ---

def marcar_vencidas(db: Session, id_empresa: int, id_proyecto: int) -> None:
    """Pasa a 'vencida' las separaciones vigentes cuya fecha ya pasó.
    NO libera el lote: alguien debe confirmarlo (endpoint /liberar)."""
    vencidas = (
        db.query(m.Separacion)
        .options(joinedload(m.Separacion.lote), joinedload(m.Separacion.ejecutivo))
        .filter(
            m.Separacion.id_empresa == id_empresa,
            m.Separacion.id_proyecto == id_proyecto,
            m.Separacion.estado == E.vigente,
            m.Separacion.fecha_vencimiento < hoy_peru(),
        )
        .all()
    )
    if not vencidas:
        return
    for sep in vencidas:
        sep.estado = E.vencida
        destinatarios = unicos(
            [sep.ejecutivo] + usuarios_por_roles(db, id_empresa, id_proyecto, ["admin", "gerencia", "supervisor"])
        )
        crear_notificaciones(
            db, id_empresa, destinatarios,
            "separacion_vencida",
            f"Separación vencida: lote {sep.lote.codigo}",
            f"Venció el {sep.fecha_vencimiento:%d/%m/%Y}. El lote sigue separado hasta que se confirme su liberación.",
            {"id_separacion": sep.id, "id_proyecto": id_proyecto, "id_lote": sep.id_lote, "estado": "vencida"},
        )
    db.commit()



# --------------------------------------------------------------- proforma --

def generar_pdf_proforma(sep: m.Separacion) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    ancho, alto = A4
    y = alto - 3 * cm

    c.setFont("Helvetica-Bold", 16)
    c.drawString(2 * cm, y, "PROFORMA DE SEPARACIÓN DE LOTE")
    y -= 1.1 * cm
    c.setFont("Helvetica", 10)
    c.drawString(2 * cm, y, f"N° Separación: {sep.id}")
    y -= 0.6 * cm
    c.drawString(2 * cm, y, f"Fecha: {sep.fecha_inicio:%d/%m/%Y}")
    y -= 1 * cm

    c.setFont("Helvetica-Bold", 11)
    c.drawString(2 * cm, y, "Datos del cliente")
    y -= 0.7 * cm
    c.setFont("Helvetica", 10)
    cliente = sep.cliente
    nombre = cliente.razon_social if cliente.tipo_persona == "juridica" else f"{cliente.nombres} {cliente.apellidos}"
    doc = cliente.ruc if cliente.tipo_persona == "juridica" else cliente.numero_documento
    c.drawString(2 * cm, y, f"Cliente: {nombre}")
    y -= 0.6 * cm
    c.drawString(2 * cm, y, f"Documento: {doc or '-'}")
    y -= 0.6 * cm
    c.drawString(2 * cm, y, f"Teléfono: {cliente.telefono or '-'}")
    y -= 1 * cm

    c.setFont("Helvetica-Bold", 11)
    c.drawString(2 * cm, y, "Datos del lote")
    y -= 0.7 * cm
    c.setFont("Helvetica", 10)
    lote = sep.lote
    c.drawString(2 * cm, y, f"Lote: {lote.codigo}")
    y -= 0.6 * cm
    c.drawString(2 * cm, y, f"Área: {lote.area_m2} m²")
    y -= 0.6 * cm
    c.drawString(2 * cm, y, f"Partida registral: {lote.partida_registral or '-'}")
    y -= 1 * cm

    c.setFont("Helvetica-Bold", 11)
    c.drawString(2 * cm, y, "Detalle de la separación")
    y -= 0.7 * cm
    c.setFont("Helvetica", 10)
    c.drawString(2 * cm, y, f"Importe separado: S/ {sep.importe:,.2f}")
    y -= 0.6 * cm
    c.drawString(2 * cm, y, f"Vencimiento: {sep.fecha_vencimiento:%d/%m/%Y}")
    if sep.tipo_pago:
        y -= 0.6 * cm
        c.drawString(2 * cm, y, f"Tipo de pago previsto: {sep.tipo_pago.value}")
    if sep.agenda_fecha:
        y -= 0.6 * cm
        c.drawString(2 * cm, y, f"Agendamiento: {sep.agenda_fecha:%d/%m/%Y %H:%M}")

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()


def guardar_proforma_pdf(id_separacion: int, contenido: bytes) -> str:
    nombre = f"proforma_{id_separacion}_{uuid.uuid4().hex[:8]}.pdf"
    ruta = os.path.join(DIR_PROFORMAS, nombre)
    with open(ruta, "wb") as f:
        f.write(contenido)
    ruta_relativa = f"/static/proformas/{nombre}"
    if settings.PUBLIC_URL_BASE:
        return f"{settings.PUBLIC_URL_BASE}{ruta_relativa}"
    return ruta_relativa