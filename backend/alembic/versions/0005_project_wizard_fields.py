"""project wizard fields: location, building info, wizard_step

Borra todos los proyectos existentes (entorno de desarrollo) y agrega las
columnas que necesita el wizard de 5 pasos.

Revision ID: 0005_project_wizard_fields
Revises: 0004_plan_page_scales
Create Date: 2026-05-25

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_project_wizard_fields"
down_revision: str | None = "2a3b4c5d6e7f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Entorno de desarrollo: borramos todos los proyectos para arrancar
    # limpio. La cascada de FKs en plans/detected_elements/etc se encarga
    # del resto.
    op.execute("DELETE FROM projects")

    op.add_column("projects", sa.Column("address", sa.String(length=512), nullable=True))
    op.add_column("projects", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("projects", sa.Column("longitude", sa.Float(), nullable=True))
    op.add_column("projects", sa.Column("city", sa.String(length=128), nullable=True))
    op.add_column("projects", sa.Column("country", sa.String(length=128), nullable=True))
    op.add_column("projects", sa.Column("building_type", sa.String(length=32), nullable=True))
    op.add_column("projects", sa.Column("building_info", sa.JSON(), nullable=True))
    op.add_column(
        "projects",
        sa.Column("wizard_step", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("projects", "wizard_step")
    op.drop_column("projects", "building_info")
    op.drop_column("projects", "building_type")
    op.drop_column("projects", "country")
    op.drop_column("projects", "city")
    op.drop_column("projects", "longitude")
    op.drop_column("projects", "latitude")
    op.drop_column("projects", "address")
