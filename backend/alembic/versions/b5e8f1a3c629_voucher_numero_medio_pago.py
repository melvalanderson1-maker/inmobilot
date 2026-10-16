"""voucher_numero y medio_pago en separaciones

Revision ID: b5e8f1a3c629
Revises: a3c9e5b7d241
Create Date: 2026-10-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b5e8f1a3c629'
down_revision: Union[str, None] = 'a3c9e5b7d241'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('separaciones', sa.Column('voucher_numero', sa.String(60), nullable=True))
    op.add_column('separaciones', sa.Column('medio_pago', sa.String(40), nullable=True))


def downgrade() -> None:
    op.drop_column('separaciones', 'medio_pago')
    op.drop_column('separaciones', 'voucher_numero')