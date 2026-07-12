"""work_plan_material_prices: snapshot de precios al congelar baseline

Revision ID: h7b8c9d0e1f2
Revises: g6a7b8c9d0e1
Create Date: 2026-07-12

Al freeze del WorkPlan se capturan los unit_price de los materiales de las
recetas del plan. Así el BAC/EVM (cost_planned) y la auditoría del baseline
no se contaminan si después cambia el catálogo vivo.
"""
from alembic import op
import sqlalchemy as sa

revision = "h7b8c9d0e1f2"
down_revision = "g6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "work_plan_material_prices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "work_plan_id",
            sa.Integer(),
            sa.ForeignKey("work_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "material_id",
            sa.Integer(),
            sa.ForeignKey("materials.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("unit_price", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(32), nullable=True),
        sa.Column("material_name", sa.String(255), nullable=True),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "work_plan_id", "material_id", name="uq_wpmp_plan_material"
        ),
    )
    op.create_index(
        "ix_wpmp_work_plan_id", "work_plan_material_prices", ["work_plan_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_wpmp_work_plan_id", table_name="work_plan_material_prices")
    op.drop_table("work_plan_material_prices")
