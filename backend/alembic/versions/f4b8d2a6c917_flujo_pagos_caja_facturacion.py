"""flujo de pagos: validacion de Caja y comprobante de Facturacion

Revision ID: f4b8d2a6c917
Revises: e2a7c5d193b8
Create Date: 2026-10-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f4b8d2a6c917'
down_revision: Union[str, None] = 'e2a7c5d193b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Los pagos que ya existen quedan como 'validado' (siguen contando en los saldos)
    op.add_column('pagos', sa.Column('estado', sa.String(30), nullable=False, server_default='validado'))
    op.add_column('pagos', sa.Column('validado_por', sa.Integer(), sa.ForeignKey('usuarios.id')))
    op.add_column('pagos', sa.Column('fecha_validacion', sa.DateTime()))
    op.add_column('pagos', sa.Column('motivo_rechazo', sa.String(300)))
    op.add_column('pagos', sa.Column('factura_tipo', sa.String(30)))
    op.add_column('pagos', sa.Column('factura_numero', sa.String(50)))
    op.add_column('pagos', sa.Column('factura_url', sa.String(300)))
    op.add_column('pagos', sa.Column('facturado_por', sa.Integer(), sa.ForeignKey('usuarios.id')))
    op.add_column('pagos', sa.Column('fecha_facturacion', sa.DateTime()))
    op.create_index('idx_pagos_estado', 'pagos', ['id_contrato', 'estado'])

    # Módulo "Pagos" para Caja y Facturación; módulo "Contratos" para Legal (abre el detalle de la venta)
    op.execute(
        "INSERT INTO rol_modulo (id_rol, id_modulo) "
        "SELECT r.id, mo.id FROM roles r, modulos mo "
        "WHERE r.id_empresa IS NULL AND ("
        "  (r.clave IN ('caja', 'facturacion') AND mo.clave = 'pagos') "
        "  OR (r.clave = 'legal' AND mo.clave = 'contratos')"
        ") AND NOT EXISTS (SELECT 1 FROM rol_modulo x WHERE x.id_rol = r.id AND x.id_modulo = mo.id)"
    )


def downgrade() -> None:
    op.drop_index('idx_pagos_estado', table_name='pagos')
    for col in ('fecha_facturacion', 'facturado_por', 'factura_url', 'factura_numero', 'factura_tipo',
                'motivo_rechazo', 'fecha_validacion', 'validado_por', 'estado'):
        op.drop_column('pagos', col)