"""
Ejecutar con:  python -m scripts.seed_inicial
(desde la carpeta backend/, con el venv activado y las tablas ya creadas)

Crea:
- Plan básico
- Empresa Gruselva
- Proyecto Oro Verde + manzana B + lote B16 (de ejemplo)
- Asignación de módulos por rol (rol_modulo)
- Usuario admin: admin@gruselva.com / Admin123!
"""

import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import models as m


# Qué módulos ve cada rol (clave de rol -> lista de claves de módulo)
PERMISOS_POR_ROL = {
    "admin": ["proyectos", "lotes", "contratos", "pagos", "leads", "documentos", "reportes", "usuarios"],
    "gerencia": ["proyectos", "lotes", "contratos", "pagos", "leads", "documentos", "reportes"],
    "supervisor": ["proyectos", "lotes", "contratos", "pagos", "leads", "documentos", "reportes"],
    "ejecutivo_ventas": ["lotes", "leads"],
    "contabilidad": ["contratos", "pagos", "documentos", "reportes"],
}


def run():
    db = SessionLocal()
    try:
        # ---- Plan ----
        plan = db.query(m.Plan).filter(m.Plan.nombre == "Pro").first()
        if not plan:
            plan = m.Plan(nombre="Pro", max_proyectos=5, max_usuarios=20, precio_mensual=299)
            db.add(plan)
            db.flush()

        # ---- Empresa ----
        empresa = db.query(m.Empresa).filter(m.Empresa.slug == "gruselva").first()
        if not empresa:
            empresa = m.Empresa(
                razon_social="Gruselva Inmobiliaria S.A.C.",
                ruc="20123456789",
                nombre_comercial="Gruselva",
                slug="gruselva",
                id_plan=plan.id,
            )
            db.add(empresa)
            db.flush()

        # ---- Módulos base (se crean si no existen) ----
        MODULOS_BASE = {
            "proyectos": ("Proyectos", "/proyectos"),
            "lotes": ("Lotes", "/dashboard/lotes"),
            "contratos": ("Contratos", "/dashboard/contratos"),
            "pagos": ("Pagos", "/dashboard/pagos"),
            "leads": ("Leads", "/dashboard/leads"),
            "documentos": ("Documentos", "/dashboard/documentos"),
            "reportes": ("Reportes", "/dashboard/reportes"),
            "usuarios": ("Usuarios", "/dashboard/usuarios"),
        }
        for clave_mod, (nombre_mod, ruta_mod) in MODULOS_BASE.items():
            modulo = db.query(m.Modulo).filter(m.Modulo.clave == clave_mod).first()
            if not modulo:
                modulo = m.Modulo(clave=clave_mod, nombre=nombre_mod, ruta=ruta_mod, listo=True)
                db.add(modulo)

        db.flush()

        # ---- Roles y permisos de módulo ----
        for clave_rol, claves_modulo in PERMISOS_POR_ROL.items():
            rol = db.query(m.Rol).filter(m.Rol.id_empresa.is_(None), m.Rol.clave == clave_rol).first()
            if not rol:
                print(f"AVISO: no se encontró el rol global '{clave_rol}' (¿corriste el SQL con el seed base?)")
                continue

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

        # ---- Proyecto Oro Verde ----
        proyecto = (
            db.query(m.Proyecto)
            .filter(m.Proyecto.id_empresa == empresa.id, m.Proyecto.slug == "oro-verde")
            .first()
        )
        if not proyecto:
            proyecto = m.Proyecto(
                id_empresa=empresa.id,
                nombre="Oro Verde",
                slug="oro-verde",
                departamento="Junín",
                moneda="PEN",
            )
            db.add(proyecto)
            db.flush()

        manzana_b = db.query(m.Manzana).filter(m.Manzana.id_proyecto == proyecto.id, m.Manzana.nombre == "B").first()
        if not manzana_b:
            manzana_b = m.Manzana(id_proyecto=proyecto.id, nombre="B")
            db.add(manzana_b)
            db.flush()

        lote_b16 = db.query(m.Lote).filter(m.Lote.id_proyecto == proyecto.id, m.Lote.codigo == "B16").first()
        if not lote_b16:
            lote_b16 = m.Lote(
                id_proyecto=proyecto.id,
                id_manzana=manzana_b.id,
                codigo="B16",
                ubicacion_lote="INTERMEDIO",
                area_m2=180,
                precio_m2_base=250,
                precio_total_base=45000,
                precio_total_contado=42000,
                precio_total_financiado=48000,
                estado=m.EstadoLoteEnum.libre,
            )
            db.add(lote_b16)

        db.flush()

        # ---- Usuario admin ----
        rol_admin = db.query(m.Rol).filter(m.Rol.id_empresa.is_(None), m.Rol.clave == "admin").first()
        admin = db.query(m.Usuario).filter(m.Usuario.correo == "admin@gruselva.com").first()
        if not admin:
            admin = m.Usuario(
                nombre="Administrador Gruselva",
                correo="admin@gruselva.com",
                password_hash=hash_password("Admin123!"),
                id_rol=rol_admin.id,
                id_empresa=empresa.id,
            )
            db.add(admin)
            db.flush()
            db.add(m.UsuarioProyecto(id_usuario=admin.id, id_proyecto=proyecto.id))

        db.commit()
        print("Seed completado.")
        print(f"Empresa: {empresa.nombre_comercial} (slug={empresa.slug})")
        print(f"Proyecto: {proyecto.nombre} (slug={proyecto.slug})")
        print("Login admin -> admin@gruselva.com / Admin123!")

    finally:
        db.close()


if __name__ == "__main__":
    run()
