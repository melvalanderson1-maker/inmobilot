"""registrar el modulo de auditoria en el menu

Revision ID: d6a1b3c8e024
Revises: c5f9a2b7d013
Create Date: 2026-11-27
"""
from alembic import op

revision = "d6a1b3c8e024"
down_revision = "c5f9a2b7d013"
branch_labels = None
depends_on = None

RUTA = "/auditoria"   # <- igual de formato que las otras filas de `modulos`


def upgrade() -> None:
    op.execute(f"""
        INSERT INTO modulos (clave, nombre, ruta, listo)
        VALUES ('auditoria', 'Auditoría', '{RUTA}', true)
        ON CONFLICT (clave) DO NOTHING
    """)
    op.execute("""
        INSERT INTO rol_modulo (id_rol, id_modulo)
        SELECT r.id, mo.id FROM roles r, modulos mo
        WHERE mo.clave = 'auditoria' AND r.clave IN ('admin', 'gerencia')
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM rol_modulo WHERE id_modulo IN (SELECT id FROM modulos WHERE clave = 'auditoria')")
    op.execute("DELETE FROM modulos WHERE clave = 'auditoria'")