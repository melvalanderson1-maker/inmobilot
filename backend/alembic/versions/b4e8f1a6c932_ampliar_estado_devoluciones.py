"""ampliar estado de devoluciones a 30 caracteres

Revision ID: b4e8f1a6c932
Revises: a7d3e9c2b154
Create Date: 2026-11-25
"""
from alembic import op
import sqlalchemy as sa

revision = "b4e8f1a6c932"
down_revision = "a7d3e9c2b154"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 'pendiente_facturacion' tiene 21 caracteres y la columna solo admitía 20
    op.alter_column(
        "devoluciones",
        "estado",
        existing_type=sa.String(20),
        type_=sa.String(30),
        existing_nullable=False,
    )


def downgrade() -> None:
    # No se reduce: ya puede haber filas con 'pendiente_facturacion'
    pass