"""Add macro_series (índices oficiales para el predictivo)

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-06-26

Fase 4 (Vía A) del Motor de Inteligencia de Costos: índices macroeconómicos
reales (ICC INDEC, IPC, dólar) desde los que el forecaster determinístico deriva
la tasa de proyección, y que el ML usará como features (Vía B).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'macro_series',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('indicator', sa.String(length=40), nullable=False),
        sa.Column('value', sa.Float(), nullable=False),
        sa.Column('date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('source', sa.String(length=64), nullable=False),
    )
    op.create_index('ix_macro_indicator_date', 'macro_series', ['indicator', 'date'])


def downgrade() -> None:
    op.drop_index('ix_macro_indicator_date', 'macro_series')
    op.drop_table('macro_series')
