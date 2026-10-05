"""linderos del lote, pagos previos y datos de crédito en venta

Revision ID: d9f3b61c824e
Revises: c7d4e82a5f19
Create Date: 2026-10-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd9f3b61c824e'
down_revision: Union[str, None] = 'c7d4e82a5f19'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- Linderos del lote ----
    op.add_column('lotes', sa.Column('frente_colindante', sa.String(150)))
    op.add_column('lotes', sa.Column('frente_medida', sa.Numeric(10, 2)))
    op.add_column('lotes', sa.Column('derecha_colindante', sa.String(150)))
    op.add_column('lotes', sa.Column('derecha_medida', sa.Numeric(10, 2)))
    op.add_column('lotes', sa.Column('izquierda_colindante', sa.String(150)))
    op.add_column('lotes', sa.Column('izquierda_medida', sa.Numeric(10, 2)))
    op.add_column('lotes', sa.Column('fondo_colindante', sa.String(150)))
    op.add_column('lotes', sa.Column('fondo_medida', sa.Numeric(10, 2)))

    # ---- Pagos previos (Minuta/contado) y datos de crédito (Preparatorio) ----
    op.add_column('ventas', sa.Column('pagos_previos', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('ventas', sa.Column('datos_credito', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('ventas', 'datos_credito')
    op.drop_column('ventas', 'pagos_previos')
    op.drop_column('lotes', 'fondo_medida')
    op.drop_column('lotes', 'fondo_colindante')
    op.drop_column('lotes', 'izquierda_medida')
    op.drop_column('lotes', 'izquierda_colindante')
    op.drop_column('lotes', 'derecha_medida')
    op.drop_column('lotes', 'derecha_colindante')
    op.drop_column('lotes', 'frente_medida')
    op.drop_column('lotes', 'frente_colindante')