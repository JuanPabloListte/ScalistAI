"""Seguimiento de Construcción: work_plans + work_tasks + progress + costos reales

Revision ID: a9b8c7d6e5f4
Revises: f1a2b3c4d5e6
Create Date: 2026-07-08

Etapa 1 del módulo Obra: el cronograma (hoy calculado al vuelo) se persiste
como baseline VERSIONADO. progress_entries y actual_costs se crean ya (las
usan las etapas 2-3) para no fragmentar el schema en tres migraciones.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a9b8c7d6e5f4'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'work_plans',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(),
                  sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='draft'),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('crews', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('overlap_pct', sa.Float(), nullable=False, server_default='0'),
        sa.Column('frozen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_work_plans_project_id', 'work_plans', ['project_id'])

    op.create_table(
        'work_tasks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('work_plan_id', sa.Integer(),
                  sa.ForeignKey('work_plans.id', ondelete='CASCADE'), nullable=False),
        sa.Column('assembly_id', sa.Integer(),
                  sa.ForeignKey('assemblies.id', ondelete='SET NULL'), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('stage', sa.String(length=64), nullable=False, server_default='Sin etapa'),
        sa.Column('stage_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('qty_planned', sa.Float(), nullable=False, server_default='0'),
        sa.Column('unit', sa.String(length=16), nullable=False, server_default='un'),
        sa.Column('duration_days', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('planned_start', sa.Date(), nullable=False),
        sa.Column('planned_end', sa.Date(), nullable=False),
        sa.Column('cost_planned', sa.Float(), nullable=False, server_default='0'),
        sa.Column('depends_on', sa.JSON(), nullable=True),
        sa.Column('source', sa.String(length=16), nullable=False, server_default='auto'),
    )
    op.create_index('ix_work_tasks_work_plan_id', 'work_tasks', ['work_plan_id'])

    op.create_table(
        'progress_entries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('task_id', sa.Integer(),
                  sa.ForeignKey('work_tasks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('qty_done', sa.Float(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('photo_path', sa.String(length=512), nullable=True),
        sa.Column('created_by', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_progress_entries_task_id', 'progress_entries', ['task_id'])

    op.create_table(
        'actual_costs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(),
                  sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('work_task_id', sa.Integer(),
                  sa.ForeignKey('work_tasks.id', ondelete='SET NULL'), nullable=True),
        sa.Column('stage', sa.String(length=64), nullable=True),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False, server_default='material'),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_by', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_actual_costs_project_id', 'actual_costs', ['project_id'])


def downgrade() -> None:
    op.drop_table('actual_costs')
    op.drop_table('progress_entries')
    op.drop_table('work_tasks')
    op.drop_table('work_plans')
