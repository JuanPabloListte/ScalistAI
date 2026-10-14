"""job_roles + user_job_roles

Revision ID: j9d0e1f2a3b4
Revises: i8c9d0e1f2a3
Create Date: 2026-07-14

Roles de obra (oficios) por organización, asignables multi a users.
"""
from alembic import op
import sqlalchemy as sa

revision = "j9d0e1f2a3b4"
down_revision = "i8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "name", name="uq_job_roles_org_name"),
    )
    op.create_index("ix_job_roles_organization_id", "job_roles", ["organization_id"])

    op.create_table(
        "user_job_roles",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("job_role_id", sa.Integer(), sa.ForeignKey("job_roles.id", ondelete="CASCADE"), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("user_job_roles")
    op.drop_index("ix_job_roles_organization_id", table_name="job_roles")
    op.drop_table("job_roles")
