"""add allow_training_data consent flag to projects

Cada proyecto puede optar in/out del uso de sus planos confirmados como
datos de entrenamiento para mejorar la IA de detección. Default = True
(opt-out implícito); para clientes con NDA / IP estricta, queda en False
y nunca se snapshotean sus planos.

Revision ID: 0008_project_training_consent
Revises: 0007_plan_page_roles
Create Date: 2026-05-27

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_project_training_consent"
down_revision: str | None = "0007_plan_page_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "allow_training_data",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "allow_training_data")
