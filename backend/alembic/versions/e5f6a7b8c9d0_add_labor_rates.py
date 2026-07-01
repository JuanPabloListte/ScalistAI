"""Add labor_rates + labor_rate_history (mano de obra first-class)

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-06-26

Fase 1b del Motor de Inteligencia de Costos: promueve la mano de obra de
"Material hs" a concepto propio (costo diario por oficio) con serie histórica.
NO-BREAKING: el material "Mano de Obra" sigue existiendo; el rewire de recetas
es de una fase posterior. Seed: scripts/seed_labor_rates.py (idempotente).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'labor_rates',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('trade', sa.String(length=80), nullable=False),
        sa.Column('daily_cost', sa.Float(), nullable=False, server_default='0'),
        sa.Column('active', sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.create_index('ix_labor_rates_organization_id', 'labor_rates', ['organization_id'])

    op.create_table(
        'labor_rate_history',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('labor_rate_id', sa.Integer(),
                  sa.ForeignKey('labor_rates.id', ondelete='CASCADE'), nullable=False),
        sa.Column('daily_cost', sa.Float(), nullable=False),
        sa.Column('date', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('source', sa.String(length=64), nullable=False),
    )
    op.create_index('ix_lrh_rate_date', 'labor_rate_history', ['labor_rate_id', 'date'])


def downgrade() -> None:
    op.drop_index('ix_lrh_rate_date', 'labor_rate_history')
    op.drop_table('labor_rate_history')
    op.drop_index('ix_labor_rates_organization_id', 'labor_rates')
    op.drop_table('labor_rates')
