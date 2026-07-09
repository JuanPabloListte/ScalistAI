"""work_task workflow fields (Jira): status/priority/assignee + historial

Revision ID: b1c2d3e4f5a6
Revises: a9b8c7d6e5f4
Create Date: 2026-07-09

Metadata de EJECUCIÓN sobre las tareas del plan (editable sobre el baseline
activo, no toca la inmutabilidad del cronograma) + tabla de historial de
cambios para la pestaña "Historial" del detalle de tarea.
"""
from alembic import op
import sqlalchemy as sa

revision = "b1c2d3e4f5a6"
down_revision = "a9b8c7d6e5f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("work_tasks", sa.Column(
        "status", sa.String(16), nullable=False, server_default="pending"))
    op.add_column("work_tasks", sa.Column(
        "priority", sa.String(8), nullable=False, server_default="medium"))
    op.add_column("work_tasks", sa.Column(
        "assignee_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_work_tasks_assignee", "work_tasks", "users",
        ["assignee_id"], ["id"], ondelete="SET NULL")

    op.create_table(
        "work_task_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("work_task_id", sa.Integer(),
                  sa.ForeignKey("work_tasks.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("field", sa.String(32), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("work_task_events")
    op.drop_constraint("fk_work_tasks_assignee", "work_tasks", type_="foreignkey")
    op.drop_column("work_tasks", "assignee_id")
    op.drop_column("work_tasks", "priority")
    op.drop_column("work_tasks", "status")
