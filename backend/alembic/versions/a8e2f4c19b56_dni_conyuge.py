"""agrega dni_frente_url y dni_reverso_url a cliente_conyuge

Revision ID: a8e2f4c19b56
Revises: f6a1c8d4e037
Create Date: 2026-09-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a8e2f4c19b56'
down_revision: Union[str, None] = 'f6a1c8d4e037'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('cliente_conyuge', sa.Column('dni_frente_url', sa.String(300)))
    op.add_column('cliente_conyuge', sa.Column('dni_reverso_url', sa.String(300)))


def downgrade() -> None:
    op.drop_column('cliente_conyuge', 'dni_reverso_url')
    op.drop_column('cliente_conyuge', 'dni_frente_url')