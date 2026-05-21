"""add page_count column to plans

Revision ID: 0003_plan_page_count
Revises: 0002_project_description
Create Date: 2026-05-20

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_plan_page_count"
down_revision: str | None = "0002_project_description"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plans", sa.Column("page_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("plans", "page_count")
