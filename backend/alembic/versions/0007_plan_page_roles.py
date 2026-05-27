"""add page_roles json column to plans

Por cada pagina del PDF, el usuario indica que rol(es) cumple para la
deteccion automatica: muros, aberturas y/o recintos. Formato:

    {"<page>": ["walls", "openings", "rooms"]}

Una pagina sin rol asignado no recibe deteccion. Una pagina puede tener
varios roles (p.ej. un plano que sirve para muros y aberturas).

Revision ID: 0007_plan_page_roles
Revises: 0006_plan_page_overrides
Create Date: 2026-05-27

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_plan_page_roles"
down_revision: str | None = "0006_plan_page_overrides"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plans", sa.Column("page_roles", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("plans", "page_roles")
