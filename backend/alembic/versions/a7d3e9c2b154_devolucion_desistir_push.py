"""separacion anulada, circuito de devolucion, desistimiento de venta, saldo contado, push

Revision ID: a7d3e9c2b154
Revises: f3a9c1b8d2e7
Create Date: 2026-11-25
"""
from alembic import op
import sqlalchemy as sa

revision = "a7d3e9c2b154"
down_revision = "f3a9c1b8d2e7"
branch_labels = None
depends_on = None


def _cols(tabla: str) -> list[str]:
    return [c["name"] for c in sa.inspect(op.get_bind()).get_columns(tabla)]


def _add(tabla: str, col: sa.Column) -> None:
    if col.name not in _cols(tabla):
        op.add_column(tabla, col)


def upgrade() -> None:
    # Nuevo valor del enum (no puede ir dentro de una transacción)
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE estado_separacion_enum ADD VALUE IF NOT EXISTS 'anulada'")

    # Devoluciones: ejecución de Caja y nota de crédito de Facturación
    _add("devoluciones", sa.Column("metodo_pago", sa.String(40)))
    _add("devoluciones", sa.Column("numero_operacion", sa.String(60)))
    _add("devoluciones", sa.Column("voucher_url", sa.String(300)))
    _add("devoluciones", sa.Column("ejecutado_por", sa.Integer(), sa.ForeignKey("usuarios.id")))
    _add("devoluciones", sa.Column("fecha_ejecucion", sa.DateTime()))
    _add("devoluciones", sa.Column("nota_credito_numero", sa.String(50)))
    _add("devoluciones", sa.Column("nota_credito_url", sa.String(300)))
    _add("devoluciones", sa.Column("nota_credito_por", sa.Integer(), sa.ForeignKey("usuarios.id")))
    _add("devoluciones", sa.Column("fecha_nota_credito", sa.DateTime()))

    # Ventas: fecha límite del saldo (contado) y datos del desistimiento
    _add("ventas", sa.Column("fecha_limite_saldo", sa.Date()))
    _add("ventas", sa.Column("motivo_desistimiento", sa.String(300)))
    _add("ventas", sa.Column("fecha_desistimiento", sa.DateTime()))
    _add("ventas", sa.Column("desistido_por", sa.Integer(), sa.ForeignKey("usuarios.id")))

    # Web Push
    if "push_suscripciones" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "push_suscripciones",
            sa.Column("id", sa.BigInteger(), primary_key=True),
            sa.Column("id_usuario", sa.Integer(), sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
            sa.Column("endpoint", sa.Text(), nullable=False),
            sa.Column("p256dh", sa.String(200), nullable=False),
            sa.Column("auth", sa.String(100), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.UniqueConstraint("endpoint", name="uq_push_endpoint"),
        )
        op.create_index("idx_push_usuario", "push_suscripciones", ["id_usuario"])


def downgrade() -> None:
    # El valor del enum no se puede quitar en PostgreSQL; las columnas se dejan (son nullable).
    pass