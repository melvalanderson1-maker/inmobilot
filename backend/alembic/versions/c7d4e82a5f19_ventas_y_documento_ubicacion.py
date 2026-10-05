"""tabla ventas, venta_clientes, documento_ubicacion, campos legales de empresa

Revision ID: c7d4e82a5f19
Revises: b3f7d92a6c41
Create Date: 2026-10-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c7d4e82a5f19'
down_revision: Union[str, None] = 'b3f7d92a6c41'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- Enum de estado de venta ----
    estado_venta_enum = postgresql.ENUM(
        'iniciada', 'documento_generado', 'documento_firmado', 'escriturada',
        'cancelada', 'anulada',
        name='estado_venta_enum',
    )
    estado_venta_enum.create(op.get_bind())

    # ---- Campos legales de la empresa (para rellenar los contratos) ----
    op.add_column('empresas', sa.Column('representante_legal_nombre', sa.String(150)))
    op.add_column('empresas', sa.Column('representante_legal_dni', sa.String(20)))
    op.add_column('empresas', sa.Column('representante_legal_estado_civil', sa.String(20)))
    op.add_column('empresas', sa.Column('partida_poderes', sa.String(50)))
    op.add_column('empresas', sa.Column('oficina_registral', sa.String(100)))
    op.add_column('empresas', sa.Column('domicilio_fiscal', sa.String(250)))
    op.add_column('empresas', sa.Column('cuenta_bancaria', sa.String(50)))
    op.add_column('empresas', sa.Column('banco', sa.String(100)))
    op.add_column('empresas', sa.Column('ciudad_firma_contratos', sa.String(100)))

    # ---- ventas ----
    op.create_table(
        'ventas',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('id_empresa', sa.Integer(), sa.ForeignKey('empresas.id', ondelete='CASCADE'), nullable=False),
        sa.Column('id_proyecto', sa.Integer(), sa.ForeignKey('proyectos.id'), nullable=False),
        sa.Column('id_lote', sa.Integer(), sa.ForeignKey('lotes.id'), nullable=False),
        sa.Column('id_separacion', sa.Integer(), sa.ForeignKey('separaciones.id', ondelete='SET NULL')),
        sa.Column('id_contrato', sa.Integer(), sa.ForeignKey('contratos.id', ondelete='SET NULL')),
        sa.Column('forma_pago', sa.Enum('contado', 'credito', name='forma_pago_enum'), nullable=False),
        sa.Column('precio_total', sa.Numeric(12, 2), nullable=False),
        sa.Column('estado', estado_venta_enum, nullable=False, server_default='iniciada'),
        sa.Column('documento_generado_url', sa.String(300)),
        sa.Column('documento_firmado_url', sa.String(300)),
        sa.Column('escritura_url', sa.String(300)),
        sa.Column('titulo_url', sa.String(300)),
        sa.Column('id_usuario_registro', sa.Integer(), sa.ForeignKey('usuarios.id')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('idx_ventas_estado', 'ventas', ['id_proyecto', 'estado'])
    op.create_index('idx_ventas_lote', 'ventas', ['id_lote'])

    # ---- venta_clientes (hasta varios compradores, mismo patrón que contrato_clientes) ----
    op.create_table(
        'venta_clientes',
        sa.Column('id_venta', sa.Integer(), sa.ForeignKey('ventas.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('id_cliente', sa.Integer(), sa.ForeignKey('clientes.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('rol', sa.Enum('titular', 'conyuge', 'copropietario', name='rol_cliente_contrato_enum'),
                   nullable=False, server_default='titular'),
    )

    # ---- documento_ubicacion ----
    op.create_table(
        'documento_ubicacion',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('id_venta', sa.Integer(), sa.ForeignKey('ventas.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tipo_documento', sa.String(30), nullable=False),  # minuta|contrato_preparatorio|escritura|titulo
        sa.Column('ubicacion', sa.String(30), nullable=False),  # notaria|juez_de_paz|municipalidad|archivo_central|otro
        sa.Column('notaria_nombre', sa.String(100)),
        sa.Column('estado_tramite', sa.String(20), nullable=False, server_default='en_proceso'),  # en_proceso|pendiente|concretado
        sa.Column('numero_tramite', sa.String(50)),
        sa.Column('numero_titulo', sa.String(50)),
        sa.Column('fecha_ingreso', sa.Date()),
        sa.Column('fecha_actualizacion', sa.Date()),
        sa.Column('observaciones', sa.String(500)),
        sa.Column('actualizado_por', sa.Integer(), sa.ForeignKey('usuarios.id')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('idx_documento_ubicacion_venta', 'documento_ubicacion', ['id_venta'])


def downgrade() -> None:
    op.drop_index('idx_documento_ubicacion_venta', table_name='documento_ubicacion')
    op.drop_table('documento_ubicacion')
    op.drop_table('venta_clientes')
    op.drop_index('idx_ventas_lote', table_name='ventas')
    op.drop_index('idx_ventas_estado', table_name='ventas')
    op.drop_table('ventas')
    op.drop_column('empresas', 'ciudad_firma_contratos')
    op.drop_column('empresas', 'banco')
    op.drop_column('empresas', 'cuenta_bancaria')
    op.drop_column('empresas', 'domicilio_fiscal')
    op.drop_column('empresas', 'oficina_registral')
    op.drop_column('empresas', 'partida_poderes')
    op.drop_column('empresas', 'representante_legal_estado_civil')
    op.drop_column('empresas', 'representante_legal_dni')
    op.drop_column('empresas', 'representante_legal_nombre')
    op.get_bind().execute(sa.text("DROP TYPE estado_venta_enum"))