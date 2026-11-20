"""usuarios: columna firma_archivo (firma del ejecutivo para proformas y contratos)

Revision ID: f3a9c1b8d2e7
Revises: e2b7c5d4f6a1
Create Date: 2026-11-20
"""
from alembic import op
import sqlalchemy as sa

revision = "f3a9c1b8d2e7"
down_revision = "e2b7c5d4f6a1"
branch_labels = None
depends_on = None

TABLA = "usuarios"
COLUMNA = "firma_archivo"


def _existe_columna() -> bool:
    columnas = [c["name"] for c in sa.inspect(op.get_bind()).get_columns(TABLA)]
    return COLUMNA in columnas


def upgrade() -> None:
    # Columna nullable: no toca ningún dato existente. Si ya existe (agregada a mano), no hace nada.
    if not _existe_columna():
        op.add_column(TABLA, sa.Column(COLUMNA, sa.String(length=255), nullable=True))


def downgrade() -> None:
    if _existe_columna():
        op.drop_column(TABLA, COLUMNA)