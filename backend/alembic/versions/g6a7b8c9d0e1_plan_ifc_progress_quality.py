"""plans: error_message, parse progress, ifc_quality

Revision ID: g6a7b8c9d0e1
Revises: f5a6b7c8d9e0
Create Date: 2026-07-11

Soporta UX del pivote IFC:
- error_message: motivo persistido cuando process_ifc falla
- parse_progress / parse_stage: etapas del worker (0–100)
- ifc_quality: semáforo (green/yellow/red) + checks al subir
"""
from alembic import op
import sqlalchemy as sa

revision = "g6a7b8c9d0e1"
down_revision = "f5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plans", sa.Column("error_message", sa.String(512), nullable=True))
    op.add_column("plans", sa.Column("parse_progress", sa.Integer(), nullable=True))
    op.add_column("plans", sa.Column("parse_stage", sa.String(64), nullable=True))
    op.add_column("plans", sa.Column("ifc_quality", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("plans", "ifc_quality")
    op.drop_column("plans", "parse_stage")
    op.drop_column("plans", "parse_progress")
    op.drop_column("plans", "error_message")
