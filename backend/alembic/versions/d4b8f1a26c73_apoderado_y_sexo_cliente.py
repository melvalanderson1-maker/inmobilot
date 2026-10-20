"""firmante apoderado en empresas y sexo del cliente

Revision ID: d4b8f1a26c73
Revises: a9c3e7d15b42
Create Date: 2026-10-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd4b8f1a26c73'
down_revision: Union[str, None] = 'a9c3e7d15b42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Gerente general: datos extra que pide la minuta
    op.add_column('empresas', sa.Column('representante_legal_genero', sa.String(1)))
    op.add_column('empresas', sa.Column('representante_legal_domicilio', sa.String(250)))
    op.add_column('empresas', sa.Column('representante_legal_ocupacion', sa.String(100)))

    # Apoderado(a)
    op.add_column('empresas', sa.Column('apoderado_nombre', sa.String(150)))
    op.add_column('empresas', sa.Column('apoderado_dni', sa.String(20)))
    op.add_column('empresas', sa.Column('apoderado_genero', sa.String(1)))
    op.add_column('empresas', sa.Column('apoderado_estado_civil', sa.String(20)))
    op.add_column('empresas', sa.Column('apoderado_ocupacion', sa.String(100)))
    op.add_column('empresas', sa.Column('apoderado_domicilio', sa.String(250)))
    op.add_column('empresas', sa.Column('apoderado_partida_poderes', sa.String(50)))

    # Sexo del comprador (M | F) para concordar masculino/femenino en los documentos
    op.add_column('clientes', sa.Column('sexo', sa.String(1)))


def downgrade() -> None:
    op.drop_column('clientes', 'sexo')
    for col in (
        'apoderado_partida_poderes', 'apoderado_domicilio', 'apoderado_ocupacion',
        'apoderado_estado_civil', 'apoderado_genero', 'apoderado_dni', 'apoderado_nombre',
        'representante_legal_ocupacion', 'representante_legal_domicilio', 'representante_legal_genero',
    ):
        op.drop_column('empresas', col)