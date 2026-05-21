"""add page_scales json column to plans

Revision ID: 0004_plan_page_scales
Revises: 0003_plan_page_count
Create Date: 2026-05-20

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_plan_page_scales"
down_revision: str | None = "0003_plan_page_count"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plans", sa.Column("page_scales", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("plans", "page_scales")
