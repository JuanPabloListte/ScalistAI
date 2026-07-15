"""project_members: membresía por proyecto con rol de permiso

Revision ID: k0e1f2a3b4c5
Revises: j9d0e1f2a3b4
Create Date: 2026-07-14

Eje de PERMISOS por proyecto (jefe_obra / capataz / comitente), distinto del
oficio (job_roles). Aditiva y retrocompatible: un proyecto sin filas acá se
comporta como antes (cualquier miembro de la org lo ve completo).
"""
from alembic import op
import sqlalchemy as sa

revision = "k0e1f2a3b4c5"
down_revision = "j9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False, server_default="capataz"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "project_id", "user_id", name="uq_project_members_project_user"
        ),
    )
    op.create_index("ix_project_members_project_id", "project_members", ["project_id"])
    op.create_index("ix_project_members_user_id", "project_members", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_project_members_user_id", table_name="project_members")
    op.drop_index("ix_project_members_project_id", table_name="project_members")
    op.drop_table("project_members")
