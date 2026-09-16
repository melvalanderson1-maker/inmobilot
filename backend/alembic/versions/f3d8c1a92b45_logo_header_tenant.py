"""logo header tenant

Revision ID: f3d8c1a92b45
Revises: a47ac3568278
Create Date: 2026-09-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f3d8c1a92b45'
down_revision: Union[str, None] = 'a47ac3568278'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tenants', sa.Column('logo_header_url', sa.String(length=300), nullable=True))


def downgrade() -> None:
    op.drop_column('tenants', 'logo_header_url')