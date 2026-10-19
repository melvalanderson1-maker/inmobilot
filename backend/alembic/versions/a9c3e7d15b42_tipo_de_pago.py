"""tipo de pago: inicial, contado, cuota, cuotas

Revision ID: a9c3e7d15b42
Revises: c7f2a9d4e813
Create Date: 2026-10-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a9c3e7d15b42'
down_revision: Union[str, None] = 'c7f2a9d4e813'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('pagos', sa.Column('tipo', sa.String(20), nullable=False, server_default='cuota'))
    op.add_column('pagos', sa.Column('cuota_desde', sa.Integer()))
    op.add_column('pagos', sa.Column('cuota_hasta', sa.Integer()))

    # --- Datos existentes ---
    # 1) Iniciales de venta (contado o crédito)
    op.execute(
        "UPDATE pagos p SET tipo = CASE WHEN c.forma_pago::text = 'contado' THEN 'contado' ELSE 'inicial' END "
        "FROM contratos c "
        "WHERE c.id = p.id_contrato AND p.observacion LIKE 'Inicial de la venta%'"
    )
    # 2) Pagos de varias cuotas
    op.execute(
        "UPDATE pagos SET tipo = 'cuotas', "
        "cuota_desde = CAST(substring(observacion from 'Pago de cuotas ([0-9]+) a') AS INTEGER), "
        "cuota_hasta = CAST(substring(observacion from 'Pago de cuotas [0-9]+ a ([0-9]+)') AS INTEGER) "
        "WHERE observacion LIKE 'Pago de cuotas%'"
    )
    # 3) Sin cuota y sin tipo reconocido
    op.execute("UPDATE pagos SET tipo = 'otro' WHERE id_cuota IS NULL AND tipo = 'cuota'")
    # 4) Pagos de una cuota: guardar su número
    op.execute(
        "UPDATE pagos p SET cuota_desde = q.numero_cuota, cuota_hasta = q.numero_cuota "
        "FROM cronograma_pagos q WHERE q.id = p.id_cuota AND p.tipo = 'cuota'"
    )

    op.create_index('idx_pagos_contrato_tipo', 'pagos', ['id_contrato', 'tipo'])


def downgrade() -> None:
    op.drop_index('idx_pagos_contrato_tipo', table_name='pagos')
    for col in ('cuota_hasta', 'cuota_desde', 'tipo'):
        op.drop_column('pagos', col)