"""crear tabla proformas (proforma rápida sin separación)

Revision ID: b8e4f2a1c9d3
Revises: a7d3e1f58c20
"""
from alembic import op
import sqlalchemy as sa

revision = "b8e4f2a1c9d3"
down_revision = "a7d3e1f58c20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "proformas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("id_empresa", sa.Integer(), sa.ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("id_proyecto", sa.Integer(), sa.ForeignKey("proyectos.id"), nullable=False),
        sa.Column("id_lote", sa.Integer(), sa.ForeignKey("lotes.id"), nullable=False),
        sa.Column("id_cliente", sa.Integer(), sa.ForeignKey("clientes.id"), nullable=True),
        sa.Column("id_ejecutivo", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
        sa.Column("prospecto_nombre", sa.String(150)),
        sa.Column("prospecto_documento", sa.String(20)),
        sa.Column("prospecto_telefono", sa.String(20)),
        sa.Column("tipo_pago", sa.String(10)),
        sa.Column("precio_descontado", sa.Numeric(12, 2)),
        sa.Column("precio_valido_hasta", sa.Date(), nullable=False),
        sa.Column("importe", sa.Numeric(12, 2)),
        sa.Column("fecha_emision", sa.Date(), nullable=False),
        sa.Column("documento_url", sa.String(300)),
        sa.Column("estado", sa.String(20), nullable=False, server_default="emitida"),
        sa.Column("id_separacion", sa.Integer(), sa.ForeignKey("separaciones.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("idx_proformas_proyecto", "proformas", ["id_proyecto", "estado"])
    op.create_index("idx_proformas_separacion", "proformas", ["id_separacion"])


def downgrade() -> None:
    op.drop_index("idx_proformas_separacion", table_name="proformas")
    op.drop_index("idx_proformas_proyecto", table_name="proformas")
    op.drop_table("proformas")