"""modulo de menu: configuracion legal (solo admin)

Revision ID: e6a1c9b37d52
Revises: d4b8f1a26c73
Create Date: 2026-10-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'e6a1c9b37d52'
down_revision: Union[str, None] = 'd4b8f1a26c73'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Opción del menú lateral (el enlace final es '/dashboard' + ruta)
    op.execute(
        "INSERT INTO modulos (clave, nombre, ruta, listo) "
        "VALUES ('configuracion_legal', 'Configuración legal', '/configuracion/empresa', true) "
        "ON CONFLICT (clave) DO NOTHING"
    )
    # Visible para todos los roles admin
    op.execute(
        "INSERT INTO rol_modulo (id_rol, id_modulo) "
        "SELECT r.id, mo.id FROM roles r, modulos mo "
        "WHERE r.clave = 'admin' AND mo.clave = 'configuracion_legal' "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM rol_modulo WHERE id_modulo IN "
        "(SELECT id FROM modulos WHERE clave = 'configuracion_legal')"
    )
    op.execute(
        "DELETE FROM usuario_modulo_permiso WHERE id_modulo IN "
        "(SELECT id FROM modulos WHERE clave = 'configuracion_legal')"
    )
    op.execute("DELETE FROM modulos WHERE clave = 'configuracion_legal'")