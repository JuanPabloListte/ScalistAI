"""Add material_price_history (serie temporal de precios)

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-26

Fase 1a del Motor de Inteligencia de Costos: histórico de precios por material,
base del motor predictivo. Hypertable-ready (timestamptz + índice material/fecha)
para migrar a TimescaleDB en Fase 4. El backfill desde Material.unit_price lo
hace scripts/seed_price_history.py (idempotente).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'material_price_history',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('material_id', sa.Integer(),
                  sa.ForeignKey('materials.id', ondelete='CASCADE'), nullable=False),
        sa.Column('price', sa.Float(), nullable=False),
        sa.Column('date', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('source', sa.String(length=64), nullable=False),
    )
    op.create_index('ix_mph_material_date', 'material_price_history', ['material_id', 'date'])


def downgrade() -> None:
    op.drop_index('ix_mph_material_date', 'material_price_history')
    op.drop_table('material_price_history')
