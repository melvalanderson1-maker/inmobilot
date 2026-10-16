"""precio_valido_hasta y precio_descontado en separaciones

Revision ID: c7f2a9d4e813
Revises: b5e8f1a3c629
Create Date: 2026-10-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c7f2a9d4e813'
down_revision: Union[str, None] = 'b5e8f1a3c629'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('separaciones', sa.Column('precio_valido_hasta', sa.Date(), nullable=True))
    op.add_column('separaciones', sa.Column('precio_descontado', sa.Numeric(12, 2), nullable=True))


def downgrade() -> None:
    op.drop_column('separaciones', 'precio_descontado')
    op.drop_column('separaciones', 'precio_valido_hasta')