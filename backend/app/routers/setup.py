from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from app.core.database import get_db
from app.core.security import hash_password
from app.core.config import settings
from app.models import models as m

router = APIRouter(prefix="/setup", tags=["setup"])


class CrearAdminInicial(BaseModel):
    clave_bootstrap: str
    nombre: str
    correo: EmailStr
    password: str


@router.post("/admin-inicial")
def crear_admin_inicial(payload: CrearAdminInicial, db: Session = Depends(get_db)):
    """
    Endpoint de un solo uso: crea el primer usuario admin de esta instancia.
    Protegido por una clave secreta compartida (BOOTSTRAP_SECRET), no por login,
    porque se llama ANTES de que exista ningún usuario en el sistema.
    Se bloquea solo si ya existe al menos un usuario.
    """
    if payload.clave_bootstrap != settings.BOOTSTRAP_SECRET:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Clave de bootstrap incorrecta")

    ya_existe_usuario = db.query(m.Usuario).first()
    if ya_existe_usuario:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Esta instancia ya tiene usuarios, bootstrap ya no está disponible")

    empresa = db.query(m.Empresa).filter(m.Empresa.slug == settings.EMPRESA_SLUG).first()
    if not empresa:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No existe la empresa base — corre el seed primero")

    rol_admin = db.query(m.Rol).filter(m.Rol.id_empresa.is_(None), m.Rol.clave == "admin").first()
    if not rol_admin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No existe el rol 'admin' — corre el seed primero")

    admin = m.Usuario(
        nombre=payload.nombre,
        correo=payload.correo,
        password_hash=hash_password(payload.password),
        id_rol=rol_admin.id,
        id_empresa=empresa.id,
    )
    db.add(admin)
    db.commit()

    return {"mensaje": "Admin creado correctamente", "correo": admin.correo}