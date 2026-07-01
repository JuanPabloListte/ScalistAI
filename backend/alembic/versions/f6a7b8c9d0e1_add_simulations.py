"""Add simulations (read-model materializado del simulador)

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-26

Fase 2b del Motor de Inteligencia de Costos: persiste el resultado de una
simulación (totales + líneas de material como JSON) para no recomputar y para
alimentar el export (Módulo 5).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'simulations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('plan_id', sa.Integer(),
                  sa.ForeignKey('plans.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False, server_default='done'),
        sa.Column('totals', sa.JSON(), nullable=False),
        sa.Column('lines', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_simulations_organization_id', 'simulations', ['organization_id'])
    op.create_index('ix_simulations_plan_id', 'simulations', ['plan_id'])


def downgrade() -> None:
    op.drop_index('ix_simulations_plan_id', 'simulations')
    op.drop_index('ix_simulations_organization_id', 'simulations')
    op.drop_table('simulations')
