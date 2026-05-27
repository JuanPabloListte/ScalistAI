"""add page_overrides json column to plans

Permite al usuario marcar/desmarcar manualmente paginas como "planta" o
"rechazada" sobreescribiendo la recomendacion del algoritmo.

Formato: {"<page>": "recommended" | "rejected"} (paginas 1-indexed como string).

Revision ID: 0006_plan_page_overrides
Revises: 0005_project_wizard_fields
Create Date: 2026-05-25

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_plan_page_overrides"
down_revision: str | None = "0005_project_wizard_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plans", sa.Column("page_overrides", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("plans", "page_overrides")
