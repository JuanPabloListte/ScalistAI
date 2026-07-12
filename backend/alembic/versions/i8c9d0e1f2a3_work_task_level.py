"""work_tasks: level + level_order from BIM storey

Revision ID: i8c9d0e1f2a3
Revises: h7b8c9d0e1f2
Create Date: 2026-07-12

Persist level/level_order on WorkTask so Gantt can show BIM provenance
and compute-diff can key by (assembly_id, level) without parsing names.
"""
from alembic import op
import sqlalchemy as sa

revision = "i8c9d0e1f2a3"
down_revision = "h7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("work_tasks", sa.Column("level", sa.String(64), nullable=True))
    op.add_column("work_tasks", sa.Column("level_order", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("work_tasks", "level_order")
    op.drop_column("work_tasks", "level")
