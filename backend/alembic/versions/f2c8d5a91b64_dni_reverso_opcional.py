"""dni reverso opcional en separaciones

Revision ID: f2c8d5a91b64
Revises: e6a1c9b37d52
"""
from alembic import op
import sqlalchemy as sa

revision = "f2c8d5a91b64"
down_revision = "e6a1c9b37d52"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("separaciones", "dni_reverso_url", existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    op.execute("UPDATE separaciones SET dni_reverso_url = dni_frente_url WHERE dni_reverso_url IS NULL")
    op.alter_column("separaciones", "dni_reverso_url", existing_type=sa.String(), nullable=False)