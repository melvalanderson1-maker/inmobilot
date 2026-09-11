from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.deps import require_modulo, get_ids_proyectos_usuario
from app.models import models as m
from app.schemas import schemas as s

router = APIRouter(prefix="/leads", tags=["leads"])


def _validar_acceso_proyecto(db: Session, usuario: m.Usuario, id_proyecto: int):
    ids_permitidos = get_ids_proyectos_usuario(db, usuario)
    if ids_permitidos is not None and id_proyecto not in ids_permitidos:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes acceso a este proyecto")


@router.get("", response_model=list[s.LeadOut])
def listar_leads(
    id_proyecto: int,
    estado: str | None = None,
    solo_mios: bool = False,
    usuario: m.Usuario = Depends(require_modulo("leads")),
    db: Session = Depends(get_db),
):
    _validar_acceso_proyecto(db, usuario, id_proyecto)

    query = db.query(m.Lead).filter(m.Lead.id_proyecto == id_proyecto)
    if estado:
        query = query.filter(m.Lead.estado == estado)
    if solo_mios or usuario.rol.clave == "ejecutivo_ventas":
        query = query.filter(m.Lead.id_ejecutivo_asignado == usuario.id)

    return query.order_by(m.Lead.created_at.desc()).all()


@router.get("/{id_lead}", response_model=s.LeadOut)
def obtener_lead(
    id_lead: int,
    usuario: m.Usuario = Depends(require_modulo("leads")),
    db: Session = Depends(get_db),
):
    lead = db.query(m.Lead).filter(m.Lead.id == id_lead).first()
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead no encontrado")
    _validar_acceso_proyecto(db, usuario, lead.id_proyecto)
    return lead


@router.patch("/{id_lead}", response_model=s.LeadOut)
def actualizar_lead(
    id_lead: int,
    payload: s.LeadUpdate,
    usuario: m.Usuario = Depends(require_modulo("leads")),
    db: Session = Depends(get_db),
):
    lead = db.query(m.Lead).filter(m.Lead.id == id_lead).first()
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead no encontrado")
    _validar_acceso_proyecto(db, usuario, lead.id_proyecto)

    for campo, valor in payload.model_dump(exclude_unset=True).items():
        setattr(lead, campo, valor)

    db.commit()
    db.refresh(lead)
    return lead


@router.get("/{id_lead}/seguimientos", response_model=list[s.LeadSeguimientoOut])
def listar_seguimientos(
    id_lead: int,
    usuario: m.Usuario = Depends(require_modulo("leads")),
    db: Session = Depends(get_db),
):
    lead = db.query(m.Lead).filter(m.Lead.id == id_lead).first()
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead no encontrado")
    _validar_acceso_proyecto(db, usuario, lead.id_proyecto)

    return (
        db.query(m.LeadSeguimiento)
        .filter(m.LeadSeguimiento.id_lead == id_lead)
        .order_by(m.LeadSeguimiento.created_at.desc())
        .all()
    )


@router.post("/{id_lead}/seguimientos", response_model=s.LeadSeguimientoOut, status_code=status.HTTP_201_CREATED)
def crear_seguimiento(
    id_lead: int,
    payload: s.LeadSeguimientoCreate,
    usuario: m.Usuario = Depends(require_modulo("leads")),
    db: Session = Depends(get_db),
):
    lead = db.query(m.Lead).filter(m.Lead.id == id_lead).first()
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead no encontrado")
    _validar_acceso_proyecto(db, usuario, lead.id_proyecto)

    seguimiento = m.LeadSeguimiento(id_lead=id_lead, id_usuario=usuario.id, nota=payload.nota)
    db.add(seguimiento)

    if lead.estado == m.EstadoLeadEnum.nuevo:
        lead.estado = m.EstadoLeadEnum.contactado

    db.commit()
    db.refresh(seguimiento)
    return seguimiento
