"""
Seed base genérico: se ejecuta en CADA arranque del contenedor, para
CUALQUIER inmobiliaria. Es idempotente — si los datos ya existen, no
hace nada. Crea:
- La Empresa de esta instancia (usando EMPRESA_NOMBRE / EMPRESA_SLUG)
- El catálogo completo de módulos del sistema
- Los roles base y qué módulos ve cada uno
"""

from app.core.database import SessionLocal
from app.core.config import settings
from app.models import models as m

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

PERMISOS_POR_ROL = {
    "admin": list(MODULOS_BASE.keys()),
    "gerencia": ["proyectos", "lotes", "contratos", "pagos", "leads", "documentos", "reportes"],
    "supervisor": ["proyectos", "lotes", "contratos", "pagos", "leads", "documentos", "reportes"],
    "ejecutivo_ventas": ["lotes", "leads"],
    "contabilidad": ["contratos", "pagos", "documentos", "reportes"],
}

NOMBRES_ROLES = {
    "admin": "Administrador",
    "gerencia": "Gerencia",
    "supervisor": "Supervisor",
    "ejecutivo_ventas": "Ejecutivo de Ventas",
    "contabilidad": "Contabilidad",
}


def run():
    db = SessionLocal()
    try:
        # ---- Módulos (catálogo global del sistema) ----
        for clave_mod, (nombre_mod, ruta_mod) in MODULOS_BASE.items():
            modulo = db.query(m.Modulo).filter(m.Modulo.clave == clave_mod).first()
            if not modulo:
                modulo = m.Modulo(clave=clave_mod, nombre=nombre_mod, ruta=ruta_mod, listo=True)
                db.add(modulo)
        db.flush()

        # ---- Roles globales (id_empresa=None) ----
        for clave_rol, nombre_rol in NOMBRES_ROLES.items():
            rol = db.query(m.Rol).filter(m.Rol.id_empresa.is_(None), m.Rol.clave == clave_rol).first()
            if not rol:
                rol = m.Rol(id_empresa=None, clave=clave_rol, nombre=nombre_rol)
                db.add(rol)
        db.flush()

        # ---- Vínculo rol -> módulos ----
        for clave_rol, claves_modulo in PERMISOS_POR_ROL.items():
            rol = db.query(m.Rol).filter(m.Rol.id_empresa.is_(None), m.Rol.clave == clave_rol).first()
            for clave_mod in claves_modulo:
                modulo = db.query(m.Modulo).filter(m.Modulo.clave == clave_mod).first()
                if not modulo:
                    continue
                existe = (
                    db.query(m.RolModulo)
                    .filter(m.RolModulo.id_rol == rol.id, m.RolModulo.id_modulo == modulo.id)
                    .first()
                )
                if not existe:
                    db.add(m.RolModulo(id_rol=rol.id, id_modulo=modulo.id))
        db.flush()

        # ---- Empresa de ESTA instancia (usa las env vars del tenant) ----
        empresa = db.query(m.Empresa).filter(m.Empresa.slug == settings.EMPRESA_SLUG).first()
        if not empresa:
            empresa = m.Empresa(
                razon_social=settings.EMPRESA_NOMBRE,
                nombre_comercial=settings.EMPRESA_NOMBRE,
                slug=settings.EMPRESA_SLUG,
            )
            db.add(empresa)

        db.commit()
        print(f"Seed base OK — empresa: {settings.EMPRESA_NOMBRE} ({settings.EMPRESA_SLUG})")
    finally:
        db.close()


if __name__ == "__main__":
    run()