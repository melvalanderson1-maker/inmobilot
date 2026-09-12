from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from app.core.database import get_db
from app.core.security import hash_password
from app.core.config import settings
from app.models import models as m

router = APIRouter(prefix="/setup", tags=["setup"])


MODULOS_BASE = {
    "proyectos": ("Proyectos", "/proyectos"),
    "lotes": ("Lotes", "/lotes"),
    "contratos": ("Contratos", "/contratos"),
    "pagos": ("Pagos", "/pagos"),
    "leads": ("Leads / CRM", "/leads"),
    "documentos": ("Documentos", "/documentos"),
    "reportes": ("Reportes", "/reportes"),
    "usuarios": ("Usuarios", "/usuarios"),
}


class CrearAdminInicial(BaseModel):
    clave_bootstrap: str
    nombre: str
    correo: EmailStr
    password: str


@router.post("/admin-inicial")
def crear_admin_inicial(payload: CrearAdminInicial, db: Session = Depends(get_db)):
    """
    Endpoint de un solo uso: crea (si hace falta) la empresa, el catálogo de
    módulos, el rol admin CON TODOS los módulos vinculados, y el primer
    usuario admin. Protegido por BOOTSTRAP_SECRET (no por login, porque se
    llama antes de que exista ningún usuario). Se bloquea solo si ya existe
    al menos un usuario.
    """
    if payload.clave_bootstrap != settings.BOOTSTRAP_SECRET:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Clave de bootstrap incorrecta")

    ya_existe_usuario = db.query(m.Usuario).first()
    if ya_existe_usuario:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Esta instancia ya tiene usuarios, bootstrap ya no está disponible")

    # 1. Empresa base
    empresa = db.query(m.Empresa).filter(m.Empresa.slug == settings.EMPRESA_SLUG).first()
    if not empresa:
        empresa = m.Empresa(
            razon_social=settings.EMPRESA_NOMBRE,
            nombre_comercial=settings.EMPRESA_NOMBRE,
            slug=settings.EMPRESA_SLUG,
            activo=True,
        )
        db.add(empresa)
        db.flush()

    # 2. Catálogo de módulos (idempotente — no duplica si ya existen)
    for clave_mod, (nombre_mod, ruta_mod) in MODULOS_BASE.items():
        modulo = db.query(m.Modulo).filter(m.Modulo.clave == clave_mod).first()
        if not modulo:
            modulo = m.Modulo(clave=clave_mod, nombre=nombre_mod, ruta=ruta_mod, listo=True)
            db.add(modulo)
    db.flush()

    # 3. Rol admin global
    rol_admin = db.query(m.Rol).filter(m.Rol.id_empresa.is_(None), m.Rol.clave == "admin").first()
    if not rol_admin:
        rol_admin = m.Rol(
            id_empresa=None,
            clave="admin",
            nombre="Administrador",
            descripcion="Rol con acceso total al sistema",
        )
        db.add(rol_admin)
        db.flush()

    # 4. Vincular TODOS los módulos al rol admin (esto es lo que faltaba)
    for clave_mod in MODULOS_BASE.keys():
        modulo = db.query(m.Modulo).filter(m.Modulo.clave == clave_mod).first()
        if not modulo:
            continue
        existe = (
            db.query(m.RolModulo)
            .filter(m.RolModulo.id_rol == rol_admin.id, m.RolModulo.id_modulo == modulo.id)
            .first()
        )
        if not existe:
            db.add(m.RolModulo(id_rol=rol_admin.id, id_modulo=modulo.id))
    db.flush()

    # 5. Usuario admin
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