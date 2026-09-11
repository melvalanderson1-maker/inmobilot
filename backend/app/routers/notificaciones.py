from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.deps import get_current_user
from app.models import models as m
from app.schemas import schemas as s

router = APIRouter(prefix="/notificaciones", tags=["notificaciones"])


@router.get("", response_model=list[s.NotificacionOut])
def listar_notificaciones(
    solo_no_leidas: bool = False,
    usuario: m.Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(m.Notificacion).filter(
        (m.Notificacion.id_usuario_destino == usuario.id) | (m.Notificacion.id_usuario_destino.is_(None)),
        m.Notificacion.id_empresa == usuario.id_empresa,
    )
    if solo_no_leidas:
        query = query.filter(m.Notificacion.leido.is_(False))

    return query.order_by(m.Notificacion.created_at.desc()).limit(100).all()


@router.patch("/{id_notificacion}/leido", response_model=s.NotificacionOut)
def marcar_leido(
    id_notificacion: int,
    usuario: m.Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notif = db.query(m.Notificacion).filter(m.Notificacion.id == id_notificacion).first()
    if not notif:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notificación no encontrada")
    if notif.id_usuario_destino not in (usuario.id, None):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No puedes modificar esta notificación")

    notif.leido = True
    db.commit()
    db.refresh(notif)
    return notif
