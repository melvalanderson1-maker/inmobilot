"""pagos: modalidad y detalle de amortizacion a capital

Revision ID: a7d3e1f58c20
Revises: f2c8d5a91b64
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a7d3e1f58c20"
down_revision = "f2c8d5a91b64"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pagos",
        sa.Column("modalidad", sa.String(20), nullable=False, server_default="adelanto"),
    )
    op.add_column(
        "pagos",
        sa.Column("detalle_amortizacion", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pagos", "detalle_amortizacion")
    op.drop_column("pagos", "modalidad")