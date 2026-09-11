from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user, require_roles, get_ids_proyectos_usuario
from app.models import models as m
from app.schemas import schemas as s

router = APIRouter(prefix="/proyectos", tags=["proyectos"])


@router.get("", response_model=list[s.ProyectoOut])
def listar_proyectos(
    usuario: m.Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(m.Proyecto).filter(m.Proyecto.id_empresa == usuario.id_empresa)

    ids_permitidos = get_ids_proyectos_usuario(db, usuario)
    if ids_permitidos is not None:
        query = query.filter(m.Proyecto.id.in_(ids_permitidos))

    return query.order_by(m.Proyecto.nombre.asc()).all()


@router.post("", response_model=s.ProyectoOut, status_code=status.HTTP_201_CREATED)
def crear_proyecto(
    payload: s.ProyectoCreate,
    usuario: m.Usuario = Depends(require_roles("admin", "gerencia")),
    db: Session = Depends(get_db),
):
    existe = (
        db.query(m.Proyecto)
        .filter(m.Proyecto.id_empresa == usuario.id_empresa, m.Proyecto.slug == payload.slug)
        .first()
    )
    if existe:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya existe un proyecto con ese slug")

    proyecto = m.Proyecto(id_empresa=usuario.id_empresa, **payload.model_dump())
    db.add(proyecto)
    db.commit()
    db.refresh(proyecto)
    return proyecto


@router.get("/{id_proyecto}/manzanas", response_model=list[s.ManzanaOut])
def listar_manzanas(
    id_proyecto: int,
    usuario: m.Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    proyecto = db.query(m.Proyecto).filter(m.Proyecto.id == id_proyecto, m.Proyecto.id_empresa == usuario.id_empresa).first()
    if not proyecto:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proyecto no encontrado")

    return db.query(m.Manzana).filter(m.Manzana.id_proyecto == id_proyecto).order_by(m.Manzana.nombre.asc()).all()


@router.post("/manzanas", response_model=s.ManzanaOut, status_code=status.HTTP_201_CREATED)
def crear_manzana(
    payload: s.ManzanaCreate,
    usuario: m.Usuario = Depends(require_roles("admin", "gerencia", "supervisor")),
    db: Session = Depends(get_db),
):
    proyecto = db.query(m.Proyecto).filter(m.Proyecto.id == payload.id_proyecto, m.Proyecto.id_empresa == usuario.id_empresa).first()
    if not proyecto:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proyecto no encontrado")

    manzana = m.Manzana(**payload.model_dump())
    db.add(manzana)
    db.commit()
    db.refresh(manzana)
    return manzana
