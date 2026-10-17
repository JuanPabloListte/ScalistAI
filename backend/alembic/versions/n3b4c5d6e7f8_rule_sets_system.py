"""rule_sets: juego estándar global (is_system, organization_id nullable)

Revision ID: n3b4c5d6e7f8
Revises: m2a3b4c5d6e7
Create Date: 2026-10-17

"Estándar Argentina" pasa a ser UN juego global (organization_id NULL,
is_system) que solo edita el superadmin. Las copias sembradas por org (mismo
nombre, predeterminadas) se borran: sus proyectos quedan con rule_set_id NULL
y resuelven al estándar global, que se siembra solo en el primer uso.
"""
from alembic import op
import sqlalchemy as sa

revision = "n3b4c5d6e7f8"
down_revision = "m2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rule_sets", sa.Column(
        "is_system", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column("rule_sets", "organization_id", existing_type=sa.Integer(), nullable=True)
    op.execute(
        "DELETE FROM rule_sets WHERE organization_id IS NOT NULL "
        "AND is_default AND name = 'Estándar Argentina'")
    # Con el estándar global como predeterminado, las orgs no tienen el suyo.
    op.execute("UPDATE rule_sets SET is_default = false WHERE organization_id IS NOT NULL")


def downgrade() -> None:
    op.execute("DELETE FROM rule_sets WHERE organization_id IS NULL")
    op.alter_column("rule_sets", "organization_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("rule_sets", "is_system")
