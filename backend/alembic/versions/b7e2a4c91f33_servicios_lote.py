"""servicios lote (agua, desague, luz, internet)

Revision ID: b7e2a4c91f33
Revises: a1c9f3e7b210
Create Date: 2026-09-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b7e2a4c91f33'
down_revision: Union[str, None] = 'a1c9f3e7b210'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('lotes', sa.Column('servicios', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('lotes', 'servicios')