"""rol comisionista y auditoria de lotes

Revision ID: a1c9f3e7b210
Revises: 0c0679003d9a
Create Date: 2026-09-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1c9f3e7b210'
down_revision: Union[str, None] = '0c0679003d9a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ROLES_NUEVOS = [
    (
        'ejecutivo_ventas',
        'Ejecutivo de Ventas',
        'Gestiona lotes y leads de sus proyectos asignados',
        ('proyectos', 'lotes', 'contratos', 'pagos', 'leads', 'documentos', 'reportes'),
    ),
    (
        'comisionista',
        'Agente Comisionista',
        'Vende lotes disponibles o separados; comisiona por venta',
        ('lotes', 'leads'),
    ),
]


def upgrade() -> None:
    # ---- 1. Roles globales (id_empresa = NULL) ----
    # WHERE NOT EXISTS en vez de ON CONFLICT: el indice unico
    # (id_empresa, clave) no detecta colision cuando id_empresa es NULL.
    for clave, nombre, descripcion, _modulos in ROLES_NUEVOS:
        op.execute(sa.text("""
            INSERT INTO roles (id_empresa, clave, nombre, descripcion)
            SELECT NULL, :clave, :nombre, :descripcion
            WHERE NOT EXISTS (
                SELECT 1 FROM roles WHERE id_empresa IS NULL AND clave = :clave
            );
        """).bindparams(clave=clave, nombre=nombre, descripcion=descripcion))

    # ---- 2. Vincular modulos (solo si ya existen en esta BD) ----
    # Tenant existente: la tabla modulos ya esta poblada -> vincula.
    # Tenant nuevo: modulos esta vacia -> no inserta nada y lo hace setup.py.
    for clave, _nombre, _descripcion, modulos in ROLES_NUEVOS:
        lista = ", ".join("'%s'" % mod for mod in modulos)
        op.execute(sa.text(f"""
            INSERT INTO rol_modulo (id_rol, id_modulo)
            SELECT r.id, mo.id
            FROM roles r
            JOIN modulos mo ON mo.clave IN ({lista})
            WHERE r.id_empresa IS NULL AND r.clave = :clave
            ON CONFLICT DO NOTHING;
        """).bindparams(clave=clave))

    # ---- 3. Auditoria: quien creo / quien edito por ultima vez cada lote ----
    op.add_column('lotes', sa.Column('creado_por', sa.Integer(), nullable=True))
    op.add_column('lotes', sa.Column('actualizado_por', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_lotes_creado_por', 'lotes', 'usuarios', ['creado_por'], ['id']
    )
    op.create_foreign_key(
        'fk_lotes_actualizado_por', 'lotes', 'usuarios', ['actualizado_por'], ['id']
    )


def downgrade() -> None:
    op.drop_constraint('fk_lotes_actualizado_por', 'lotes', type_='foreignkey')
    op.drop_constraint('fk_lotes_creado_por', 'lotes', type_='foreignkey')
    op.drop_column('lotes', 'actualizado_por')
    op.drop_column('lotes', 'creado_por')
    op.execute("""
        DELETE FROM rol_modulo
        WHERE id_rol IN (
            SELECT id FROM roles
            WHERE id_empresa IS NULL
              AND clave IN ('ejecutivo_ventas', 'comisionista')
        );
    """)
    op.execute("""
        DELETE FROM roles
        WHERE id_empresa IS NULL
          AND clave IN ('ejecutivo_ventas', 'comisionista');
    """)