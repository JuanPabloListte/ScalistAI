"""work_task: multi-responsable + descripción

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-07-09

El Gantt asigna VARIOS responsables por tarea. Se reemplaza el assignee_id único
por una tabla puente work_task_assignees (M2M) y se agrega description (pestaña
Detalle del modal). El campo único era de días atrás sin datos productivos.
"""
from alembic import op
import sqlalchemy as sa

revision = "c2d3e4f5a6b7"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("work_tasks", sa.Column("description", sa.Text(), nullable=True))

    op.create_table(
        "work_task_assignees",
        sa.Column("work_task_id", sa.Integer(),
                  sa.ForeignKey("work_tasks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    )

    # Migrar el responsable único existente (si lo hubiera) a la tabla puente.
    op.execute(
        "insert into work_task_assignees (work_task_id, user_id) "
        "select id, assignee_id from work_tasks where assignee_id is not null")

    op.drop_constraint("fk_work_tasks_assignee", "work_tasks", type_="foreignkey")
    op.drop_column("work_tasks", "assignee_id")


def downgrade() -> None:
    op.add_column("work_tasks", sa.Column("assignee_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_work_tasks_assignee", "work_tasks", "users",
        ["assignee_id"], ["id"], ondelete="SET NULL")
    op.execute(
        "update work_tasks t set assignee_id = ("
        "select user_id from work_task_assignees a where a.work_task_id = t.id limit 1)")
    op.drop_table("work_task_assignees")
    op.drop_column("work_tasks", "description")
