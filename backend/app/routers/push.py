from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.deps import get_current_user
from app.models import models as m

router = APIRouter(prefix="/push", tags=["push"])


class SuscripcionIn(BaseModel):
    endpoint: str
    keys: dict[str, str]


class DesuscribirIn(BaseModel):
    endpoint: str


@router.get("/clave-publica")
def clave_publica(usuario: m.Usuario = Depends(get_current_user)):
    return {"clave": settings.VAPID_PUBLIC_KEY}


@router.post("/suscribir", status_code=204)
def suscribir(payload: SuscripcionIn, usuario: m.Usuario = Depends(get_current_user), db: Session = Depends(get_db)):
    p256dh, auth = payload.keys.get("p256dh"), payload.keys.get("auth")
    if not p256dh or not auth:
        raise HTTPException(status_code=422, detail="Suscripción incompleta")
    sub = db.query(m.PushSuscripcion).filter(m.PushSuscripcion.endpoint == payload.endpoint).first()
    if sub:
        sub.id_usuario, sub.p256dh, sub.auth = usuario.id, p256dh, auth  # el navegador pasa al usuario que inició sesión
    else:
        db.add(m.PushSuscripcion(id_usuario=usuario.id, endpoint=payload.endpoint, p256dh=p256dh, auth=auth))
    db.commit()


@router.post("/desuscribir", status_code=204)
def desuscribir(payload: DesuscribirIn, usuario: m.Usuario = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(m.PushSuscripcion).filter(
        m.PushSuscripcion.endpoint == payload.endpoint, m.PushSuscripcion.id_usuario == usuario.id
    ).delete()
    db.commit()