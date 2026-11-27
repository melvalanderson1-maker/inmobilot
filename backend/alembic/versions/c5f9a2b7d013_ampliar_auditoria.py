"""ampliar accion de auditoria y agregar indices de consulta

Revision ID: c5f9a2b7d013
Revises: b4e8f1a6c932
Create Date: 2026-11-27
"""
from alembic import op
import sqlalchemy as sa

revision = "c5f9a2b7d013"
down_revision = "b4e8f1a6c932"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 'revertir_validacion_caja' tiene 24 caracteres y la columna solo admitía 20
    op.alter_column(
        "auditoria",
        "accion",
        existing_type=sa.String(20),
        type_=sa.String(60),
        existing_nullable=False,
    )
    # Índices para el futuro módulo de auditoría (filtrar por fecha y por usuario)
    op.create_index("idx_auditoria_empresa_fecha", "auditoria", ["id_empresa", "created_at"])
    op.create_index("idx_auditoria_usuario_fecha", "auditoria", ["id_usuario", "created_at"])


def downgrade() -> None:
    # No se reduce: ya puede haber acciones de más de 20 caracteres
    op.drop_index("idx_auditoria_usuario_fecha", table_name="auditoria")
    op.drop_index("idx_auditoria_empresa_fecha", table_name="auditoria")