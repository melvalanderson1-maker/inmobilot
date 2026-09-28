"""modulo separaciones y vinculacion a roles

Revision ID: d4e9a6b2c815
Revises: c3d8e5f1a742
Create Date: 2026-09-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd4e9a6b2c815'
down_revision: Union[str, None] = 'c3d8e5f1a742'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text(
        "INSERT INTO modulos (clave, nombre, ruta, listo) "
        "SELECT 'separaciones', 'Separaciones', '/separaciones', TRUE "
        "WHERE NOT EXISTS (SELECT 1 FROM modulos WHERE clave = 'separaciones')"
    ))
    op.execute(sa.text(
        "INSERT INTO rol_modulo (id_rol, id_modulo) "
        "SELECT r.id, mo.id FROM roles r, modulos mo "
        "WHERE mo.clave = 'separaciones' "
        "AND r.clave IN ('admin','gerencia','supervisor','ejecutivo_ventas',"
        "'caja','facturacion','contabilidad') "
        "AND NOT EXISTS (SELECT 1 FROM rol_modulo rm "
        "WHERE rm.id_rol = r.id AND rm.id_modulo = mo.id)"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "DELETE FROM rol_modulo WHERE id_modulo IN "
        "(SELECT id FROM modulos WHERE clave = 'separaciones')"
    ))
    op.execute(sa.text(
        "DELETE FROM usuario_modulo_permiso WHERE id_modulo IN "
        "(SELECT id FROM modulos WHERE clave = 'separaciones')"
    ))
    op.execute(sa.text("DELETE FROM modulos WHERE clave = 'separaciones'"))