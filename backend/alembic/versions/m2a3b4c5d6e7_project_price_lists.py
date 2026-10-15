"""project_price_lists: presupuesto del proveedor por proyecto

Revision ID: m2a3b4c5d6e7
Revises: l1f2a3b4c5d6
Create Date: 2026-10-14
"""
from alembic import op
import sqlalchemy as sa

revision = "m2a3b4c5d6e7"
down_revision = "l1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_price_lists",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("file_path", sa.String(1024), nullable=False),
        sa.Column("iva_included", sa.Boolean(), nullable=True),
        sa.Column("parsed", sa.JSON(), nullable=False),
        sa.Column("overrides", sa.JSON(), nullable=False),
        sa.Column("line_patches", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_project_price_lists_project_id", "project_price_lists",
                    ["project_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_project_price_lists_project_id", table_name="project_price_lists")
    op.drop_table("project_price_lists")
