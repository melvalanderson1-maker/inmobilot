"""renombra dni_url a dni_frente_url y agrega dni_reverso_url en clientes

Revision ID: f6a1c8d4e037
Revises: e5f0b7c3d926
Create Date: 2026-09-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f6a1c8d4e037'
down_revision: Union[str, None] = 'e5f0b7c3d926'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('clientes', 'dni_url', new_column_name='dni_frente_url')
    op.add_column('clientes', sa.Column('dni_reverso_url', sa.String(300)))


def downgrade() -> None:
    op.drop_column('clientes', 'dni_reverso_url')
    op.alter_column('clientes', 'dni_frente_url', new_column_name='dni_url')