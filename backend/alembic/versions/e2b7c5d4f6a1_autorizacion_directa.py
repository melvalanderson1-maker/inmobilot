"""autorizaciones de venta directa (sin separacion)

Revision ID: e2b7c5d4f6a1
Revises: d1a6b4c3e2f5
"""
from alembic import op
import sqlalchemy as sa

revision = "e2b7c5d4f6a1"
down_revision = "d1a6b4c3e2f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("autorizaciones_venta", "id_separacion", existing_type=sa.Integer(), nullable=True)
    op.add_column("autorizaciones_venta", sa.Column("id_lote", sa.Integer(), sa.ForeignKey("lotes.id"), nullable=True))
    op.create_index("idx_autorizaciones_venta_lote", "autorizaciones_venta", ["id_lote", "estado"])


def downgrade() -> None:
    op.drop_index("idx_autorizaciones_venta_lote", table_name="autorizaciones_venta")
    op.execute("DELETE FROM autorizaciones_venta WHERE id_separacion IS NULL")
    op.drop_column("autorizaciones_venta", "id_lote")
    op.alter_column("autorizaciones_venta", "id_separacion", existing_type=sa.Integer(), nullable=False)