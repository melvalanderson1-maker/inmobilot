"""ampliar clientes (persona juridica, conyuge, dni) y modulo clientes

Revision ID: e5f0b7c3d926
Revises: d4e9a6b2c815
Create Date: 2026-09-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e5f0b7c3d926'
down_revision: Union[str, None] = 'd4e9a6b2c815'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('clientes', sa.Column('tipo_persona', sa.String(20), nullable=False, server_default='natural'))
    op.add_column('clientes', sa.Column('dni_url', sa.String(300)))
    op.add_column('clientes', sa.Column('fecha_nacimiento', sa.Date()))
    op.add_column('clientes', sa.Column('estado_civil', sa.String(20)))
    op.add_column('clientes', sa.Column('segundo_contacto_nombre', sa.String(150)))
    op.add_column('clientes', sa.Column('segundo_contacto_telefono', sa.String(20)))
    op.add_column('clientes', sa.Column('ruc', sa.String(20)))
    op.add_column('clientes', sa.Column('razon_social', sa.String(200)))
    op.add_column('clientes', sa.Column('representante_legal', sa.String(150)))
    op.add_column('clientes', sa.Column('activo', sa.Boolean(), nullable=False, server_default='true'))

    op.create_table(
        'cliente_conyuge',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('id_cliente', sa.Integer(), sa.ForeignKey('clientes.id', ondelete='CASCADE'), nullable=False),
        sa.Column('nombres', sa.String(150), nullable=False),
        sa.Column('apellidos', sa.String(150), nullable=False),
        sa.Column('numero_documento', sa.String(20), nullable=False),
        sa.Column('telefono', sa.String(20)),
    )
    op.create_unique_constraint('uq_conyuge_cliente', 'cliente_conyuge', ['id_cliente'])

    op.execute(sa.text(
        "INSERT INTO modulos (clave, nombre, ruta, listo) "
        "SELECT 'clientes', 'Clientes', '/clientes', TRUE "
        "WHERE NOT EXISTS (SELECT 1 FROM modulos WHERE clave = 'clientes')"
    ))
    op.execute(sa.text(
        "INSERT INTO rol_modulo (id_rol, id_modulo) "
        "SELECT r.id, mo.id FROM roles r, modulos mo "
        "WHERE mo.clave = 'clientes' "
        "AND r.clave IN ('admin','gerencia','supervisor','ejecutivo_ventas','contabilidad') "
        "AND NOT EXISTS (SELECT 1 FROM rol_modulo rm "
        "WHERE rm.id_rol = r.id AND rm.id_modulo = mo.id)"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "DELETE FROM rol_modulo WHERE id_modulo IN (SELECT id FROM modulos WHERE clave = 'clientes')"
    ))
    op.execute(sa.text(
        "DELETE FROM usuario_modulo_permiso WHERE id_modulo IN (SELECT id FROM modulos WHERE clave = 'clientes')"
    ))
    op.execute(sa.text("DELETE FROM modulos WHERE clave = 'clientes'"))

    op.drop_table('cliente_conyuge')

    op.drop_column('clientes', 'activo')
    op.drop_column('clientes', 'representante_legal')
    op.drop_column('clientes', 'razon_social')
    op.drop_column('clientes', 'ruc')
    op.drop_column('clientes', 'segundo_contacto_telefono')
    op.drop_column('clientes', 'segundo_contacto_nombre')
    op.drop_column('clientes', 'estado_civil')
    op.drop_column('clientes', 'fecha_nacimiento')
    op.drop_column('clientes', 'dni_url')
    op.drop_column('clientes', 'tipo_persona')