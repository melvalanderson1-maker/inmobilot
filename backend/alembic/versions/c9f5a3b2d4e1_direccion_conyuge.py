"""agregar direccion al conyuge del cliente

Revision ID: c9f5a3b2d4e1
Revises: b8e4f2a1c9d3
"""
from alembic import op
import sqlalchemy as sa

revision = "c9f5a3b2d4e1"
down_revision = "b8e4f2a1c9d3"
branch_labels = None
depends_on = None

TABLA = "cliente_conyuge"


def upgrade() -> None:
    op.add_column(TABLA, sa.Column("direccion", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column(TABLA, "direccion")