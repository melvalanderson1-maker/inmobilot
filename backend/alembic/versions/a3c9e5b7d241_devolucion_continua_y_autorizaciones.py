"""devolucion con continuidad de venta, autorizaciones de venta, menu Ventas y Contratos

Revision ID: a3c9e5b7d241
Revises: f4b8d2a6c917
Create Date: 2026-10-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a3c9e5b7d241'
down_revision: Union[str, None] = 'f4b8d2a6c917'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('devoluciones', sa.Column('continua_venta', sa.Boolean(), nullable=False, server_default=sa.text('false')))

    op.create_table(
        'autorizaciones_venta',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('id_empresa', sa.Integer(), sa.ForeignKey('empresas.id', ondelete='CASCADE'), nullable=False),
        sa.Column('id_proyecto', sa.Integer(), sa.ForeignKey('proyectos.id'), nullable=False),
        sa.Column('id_separacion', sa.Integer(), sa.ForeignKey('separaciones.id', ondelete='CASCADE'), nullable=False),
        sa.Column('solicitado_por', sa.Integer(), sa.ForeignKey('usuarios.id'), nullable=False),
        sa.Column('estado', sa.String(20), nullable=False, server_default='pendiente'),
        sa.Column('motivos', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('propuesta', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('respuesta', sa.String(300)),
        sa.Column('resuelto_por', sa.Integer(), sa.ForeignKey('usuarios.id')),
        sa.Column('resuelto_at', sa.DateTime()),
        sa.Column('id_venta', sa.Integer(), sa.ForeignKey('ventas.id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('idx_autorizaciones_venta_sep', 'autorizaciones_venta', ['id_separacion', 'estado'])

    op.execute("UPDATE modulos SET nombre = 'Ventas y Contratos' WHERE clave = 'contratos'")


def downgrade() -> None:
    op.execute("UPDATE modulos SET nombre = 'Contratos' WHERE clave = 'contratos'")
    op.drop_index('idx_autorizaciones_venta_sep', table_name='autorizaciones_venta')
    op.drop_table('autorizaciones_venta')
    op.drop_column('devoluciones', 'continua_venta')