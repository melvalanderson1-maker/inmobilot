"""agrega tipo y numero de documento del representante legal

Revision ID: b3f7d92a6c41
Revises: a8e2f4c19b56
Create Date: 2026-09-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b3f7d92a6c41'
down_revision: Union[str, None] = 'a8e2f4c19b56'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('clientes', sa.Column('representante_tipo_documento', sa.String(10)))
    op.add_column('clientes', sa.Column('representante_numero_documento', sa.String(20)))


def downgrade() -> None:
    op.drop_column('clientes', 'representante_numero_documento')
    op.drop_column('clientes', 'representante_tipo_documento')