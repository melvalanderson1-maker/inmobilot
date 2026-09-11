from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.models import models as m
from app.schemas import schemas as s
from app.sockets import notificar_nuevo_lead

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/proyectos/{empresa_slug}/{proyecto_slug}/lotes", response_model=list[s.LotePublicoOut])
def listar_lotes_publicos(empresa_slug: str, proyecto_slug: str, db: Session = Depends(get_db)):
    """Catálogo público, sin login. Nunca expone partida_registral, sunarp_url, ni datos de clientes."""
    empresa = db.query(m.Empresa).filter(m.Empresa.slug == empresa_slug, m.Empresa.activo.is_(True)).first()
    if not empresa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Empresa no encontrada")

    proyecto = (
        db.query(m.Proyecto)
        .filter(m.Proyecto.id_empresa == empresa.id, m.Proyecto.slug == proyecto_slug, m.Proyecto.activo.is_(True))
        .first()
    )
    if not proyecto:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proyecto no encontrado")

    lotes = (
        db.query(m.Lote)
        .options(joinedload(m.Lote.imagenes))
        .filter(m.Lote.id_proyecto == proyecto.id, m.Lote.activo.is_(True))
        .order_by(m.Lote.orden.asc().nulls_last(), m.Lote.codigo.asc())
        .all()
    )
    return lotes


@router.get("/proyectos/{empresa_slug}", response_model=list[s.ProyectoOut])
def listar_proyectos_publicos(empresa_slug: str, db: Session = Depends(get_db)):
    empresa = db.query(m.Empresa).filter(m.Empresa.slug == empresa_slug, m.Empresa.activo.is_(True)).first()
    if not empresa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Empresa no encontrada")

    return db.query(m.Proyecto).filter(m.Proyecto.id_empresa == empresa.id, m.Proyecto.activo.is_(True)).all()


@router.post("/leads", response_model=s.LeadOut, status_code=status.HTTP_201_CREATED)
async def crear_lead_publico(payload: s.LeadCreatePublic, db: Session = Depends(get_db)):
    """Se dispara cuando alguien hace click en 'Me interesa' en el sitio público."""
    proyecto = db.query(m.Proyecto).filter(m.Proyecto.id == payload.id_proyecto).first()
    if not proyecto:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proyecto no encontrado")

    if payload.id_lote:
        lote = db.query(m.Lote).filter(m.Lote.id == payload.id_lote, m.Lote.id_proyecto == proyecto.id).first()
        if not lote:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lote no encontrado")

    # Asignación simple: round-robin por el ejecutivo con menos leads activos en el proyecto.
    ejecutivo = _asignar_ejecutivo(db, proyecto.id)

    lead = m.Lead(
        id_empresa=proyecto.id_empresa,
        id_proyecto=proyecto.id,
        id_lote=payload.id_lote,
        nombre=payload.nombre,
        telefono=payload.telefono,
        correo=payload.correo,
        mensaje=payload.mensaje,
        origen=payload.origen,
        id_ejecutivo_asignado=ejecutivo.id if ejecutivo else None,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    notif = m.Notificacion(
        id_empresa=proyecto.id_empresa,
        id_usuario_destino=ejecutivo.id if ejecutivo else None,
        tipo="nuevo_lead",
        titulo="Nuevo lead recibido",
        mensaje=f"{lead.nombre} está interesado en el lote {payload.id_lote or ''}".strip(),
        data={"id_lead": lead.id, "id_lote": payload.id_lote},
    )
    db.add(notif)
    db.commit()

    await notificar_nuevo_lead(
        s.LeadOut.model_validate(lead).model_dump(mode="json"),
        id_proyecto=proyecto.id,
        id_empresa=proyecto.id_empresa,
        id_usuario_destino=ejecutivo.id if ejecutivo else None,
    )

    
    return lead


def _asignar_ejecutivo(db: Session, id_proyecto: int) -> m.Usuario | None:
    ejecutivos = (
        db.query(m.Usuario)
        .join(m.UsuarioProyecto, m.UsuarioProyecto.id_usuario == m.Usuario.id)
        .join(m.Rol, m.Rol.id == m.Usuario.id_rol)
        .filter(
            m.UsuarioProyecto.id_proyecto == id_proyecto,
            m.Rol.clave == "ejecutivo_ventas",
            m.Usuario.activo.is_(True),
        )
        .all()
    )
    if not ejecutivos:
        return None

    conteos = {
        e.id: db.query(m.Lead)
        .filter(m.Lead.id_ejecutivo_asignado == e.id, m.Lead.estado.notin_(["convertido", "descartado"]))
        .count()
        for e in ejecutivos
    }
    return min(ejecutivos, key=lambda e: conteos[e.id])
