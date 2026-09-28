"""separaciones, comprobantes, devoluciones y roles caja/facturacion

Revision ID: c3d8e5f1a742
Revises: b7e2a4c91f33
Create Date: 2026-09-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c3d8e5f1a742'
down_revision: Union[str, None] = 'b7e2a4c91f33'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

estado_separacion = postgresql.ENUM(
    'pendiente_caja', 'pendiente_facturacion', 'vigente', 'vencida',
    'convertida', 'devolucion_pendiente', 'devuelta', 'rechazada',
    name='estado_separacion_enum', create_type=False,
)
forma_pago = postgresql.ENUM(
    'contado', 'credito', name='forma_pago_enum', create_type=False,
)

ROLES_NUEVOS = [
    ('caja', 'Caja', 'Valida vouchers de pago'),
    ('facturacion', 'Facturación', 'Emite y sube comprobantes'),
    ('contabilidad', 'Contabilidad', 'Consulta cobranza y reportes'),
]


def upgrade() -> None:
    bind = op.get_bind()
    estado_separacion.create(bind, checkfirst=True)

    op.create_table(
        'separaciones',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('id_empresa', sa.Integer(), sa.ForeignKey('empresas.id', ondelete='CASCADE'), nullable=False),
        sa.Column('id_proyecto', sa.Integer(), sa.ForeignKey('proyectos.id'), nullable=False),
        sa.Column('id_lote', sa.Integer(), sa.ForeignKey('lotes.id'), nullable=False),
        sa.Column('id_cliente', sa.Integer(), sa.ForeignKey('clientes.id'), nullable=False),
        sa.Column('id_ejecutivo', sa.Integer(), sa.ForeignKey('usuarios.id'), nullable=False),
        sa.Column('fecha_inicio', sa.Date(), nullable=False),
        sa.Column('fecha_vencimiento', sa.Date(), nullable=False),
        sa.Column('importe', sa.Numeric(12, 2), nullable=False),
        sa.Column('motivo', sa.String(300)),
        sa.Column('tipo_pago', forma_pago),
        sa.Column('notas', sa.String(500)),
        sa.Column('dni_frente_url', sa.String(300), nullable=False),
        sa.Column('dni_reverso_url', sa.String(300), nullable=False),
        sa.Column('voucher_url', sa.String(300), nullable=False),
        sa.Column('proforma_url', sa.String(300)),
        sa.Column('contrato_url', sa.String(300)),
        sa.Column('contrato_firmado_url', sa.String(300)),
        sa.Column('estado', estado_separacion, nullable=False, server_default='pendiente_caja'),
        sa.Column('validado_por', sa.Integer(), sa.ForeignKey('usuarios.id')),
        sa.Column('fecha_validacion', sa.DateTime()),
        sa.Column('motivo_rechazo', sa.String(300)),
        sa.Column('agenda_fecha', sa.DateTime()),
        sa.Column('fecha_conversion', sa.Date()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('idx_separaciones_estado', 'separaciones', ['id_proyecto', 'estado'])
    op.create_index('idx_separaciones_lote', 'separaciones', ['id_lote'])
    # Un lote solo puede tener UNA separación activa a la vez
    op.create_index(
        'uq_separacion_lote_activa', 'separaciones', ['id_lote'],
        unique=True,
        postgresql_where=sa.text(
            "estado IN ('pendiente_caja','pendiente_facturacion','vigente','devolucion_pendiente')"
        ),
    )

    op.create_table(
        'comprobantes_pago',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('id_separacion', sa.Integer(), sa.ForeignKey('separaciones.id', ondelete='CASCADE')),
        sa.Column('tipo', sa.String(30), nullable=False),
        sa.Column('numero', sa.String(50), nullable=False),
        sa.Column('archivo_url', sa.String(300), nullable=False),
        sa.Column('emitido_por', sa.Integer(), sa.ForeignKey('usuarios.id')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        'devoluciones',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('id_separacion', sa.Integer(), sa.ForeignKey('separaciones.id', ondelete='CASCADE'), nullable=False),
        sa.Column('monto', sa.Numeric(12, 2), nullable=False),
        sa.Column('sustento', sa.String(500), nullable=False),
        sa.Column('solicitado_por', sa.Integer(), sa.ForeignKey('usuarios.id')),
        sa.Column('fecha_solicitud', sa.Date(), server_default=sa.func.current_date()),
        sa.Column('estado', sa.String(20), nullable=False, server_default='pendiente'),
        sa.Column('resuelto_por', sa.Integer(), sa.ForeignKey('usuarios.id')),
        sa.Column('fecha_resolucion', sa.DateTime()),
        sa.Column('respuesta', sa.String(300)),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )

    for clave, nombre, descripcion in ROLES_NUEVOS:
        op.execute(
            sa.text(
                "INSERT INTO roles (id_empresa, clave, nombre, descripcion) "
                "SELECT NULL, CAST(:c AS VARCHAR), CAST(:n AS VARCHAR), CAST(:d AS VARCHAR) "
                "WHERE NOT EXISTS (SELECT 1 FROM roles WHERE clave = CAST(:c AS VARCHAR))"
            ).bindparams(c=clave, n=nombre, d=descripcion)
        )


def downgrade() -> None:
    op.drop_table('devoluciones')
    op.drop_table('comprobantes_pago')
    op.drop_index('uq_separacion_lote_activa', table_name='separaciones')
    op.drop_index('idx_separaciones_lote', table_name='separaciones')
    op.drop_index('idx_separaciones_estado', table_name='separaciones')
    op.drop_table('separaciones')
    estado_separacion.drop(op.get_bind(), checkfirst=True)