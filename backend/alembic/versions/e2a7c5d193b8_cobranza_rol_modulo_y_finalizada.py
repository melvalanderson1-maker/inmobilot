"""rol y modulo de cobranza, estado finalizada de venta

Revision ID: e2a7c5d193b8
Revises: d9f3b61c824e
Create Date: 2026-10-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'e2a7c5d193b8'
down_revision: Union[str, None] = 'd9f3b61c824e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Un valor nuevo de enum no puede usarse dentro de la misma transacción: va aparte
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE estado_venta_enum ADD VALUE IF NOT EXISTS 'finalizada'")

    op.execute(
        "INSERT INTO modulos (clave, nombre, ruta, listo) "
        "SELECT 'cobranza', 'Cobranza', '/cobranza', true "
        "WHERE NOT EXISTS (SELECT 1 FROM modulos WHERE clave = 'cobranza')"
    )
    op.execute(
        "INSERT INTO roles (id_empresa, clave, nombre, descripcion) "
        "SELECT NULL, 'cobranza', 'Cobranza', 'Cobra el saldo de las ventas a crédito, recalcula cuotas y finaliza ventas' "
        "WHERE NOT EXISTS (SELECT 1 FROM roles WHERE id_empresa IS NULL AND clave = 'cobranza')"
    )
    op.execute(
        "INSERT INTO rol_modulo (id_rol, id_modulo) "
        "SELECT r.id, mo.id FROM roles r, modulos mo "
        "WHERE r.id_empresa IS NULL AND ("
        "  (r.clave = 'cobranza' AND mo.clave IN ('cobranza', 'contratos', 'pagos')) "
        "  OR (r.clave IN ('admin', 'gerencia', 'supervisor', 'contabilidad') AND mo.clave = 'cobranza')"
        ") AND NOT EXISTS (SELECT 1 FROM rol_modulo x WHERE x.id_rol = r.id AND x.id_modulo = mo.id)"
    )


def downgrade() -> None:
    op.execute("DELETE FROM rol_modulo WHERE id_modulo IN (SELECT id FROM modulos WHERE clave = 'cobranza')")
    op.execute("DELETE FROM modulos WHERE clave = 'cobranza'")
    # El valor 'finalizada' del enum y el rol 'cobranza' se dejan (PostgreSQL no permite quitar valores de un enum)