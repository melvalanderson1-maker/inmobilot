"""tabla de auditoria (quien edito o elimino que)

Revision ID: d1a6b4c3e2f5
Revises: c9f5a3b2d4e1
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d1a6b4c3e2f5"
down_revision = "c9f5a3b2d4e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auditoria",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("id_empresa", sa.Integer(), sa.ForeignKey("empresas.id", ondelete="CASCADE")),
        sa.Column("id_usuario", sa.Integer(), sa.ForeignKey("usuarios.id")),
        sa.Column("entidad", sa.String(30), nullable=False),
        sa.Column("id_entidad", sa.Integer(), nullable=False),
        sa.Column("accion", sa.String(20), nullable=False),
        sa.Column("cambios", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("idx_auditoria_entidad", "auditoria", ["entidad", "id_entidad"])


def downgrade() -> None:
    op.drop_index("idx_auditoria_entidad", table_name="auditoria")
    op.drop_table("auditoria")