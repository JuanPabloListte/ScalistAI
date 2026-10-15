"""rule_sets + rules + projects.rule_set_id

Revision ID: l1f2a3b4c5d6
Revises: k0e1f2a3b4c5
Create Date: 2026-10-14

Juegos de reglas de cómputo (IFC → productos del presupuesto del proveedor).
"""
from alembic import op
import sqlalchemy as sa

revision = "l1f2a3b4c5d6"
down_revision = "k0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rule_sets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_rule_sets_organization_id", "rule_sets", ["organization_id"])

    op.create_table(
        "rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_set_id", sa.Integer(),
                  sa.ForeignKey("rule_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("measure", sa.String(32), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column("exclude_keywords", sa.JSON(), nullable=False),
        sa.Column("unit", sa.String(8), nullable=False),
        sa.Column("factor", sa.Float(), nullable=False, server_default="0"),
        sa.Column("mode", sa.String(16), nullable=False, server_default="fixed"),
        sa.Column("waste_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_rules_rule_set_id", "rules", ["rule_set_id"])

    op.add_column("projects", sa.Column(
        "rule_set_id", sa.Integer(),
        sa.ForeignKey("rule_sets.id", ondelete="SET NULL"), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "rule_set_id")
    op.drop_index("ix_rules_rule_set_id", table_name="rules")
    op.drop_table("rules")
    op.drop_index("ix_rule_sets_organization_id", table_name="rule_sets")
    op.drop_table("rule_sets")
