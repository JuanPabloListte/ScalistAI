"""Add cost_settings (costos indirectos por org)

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-06-27

Fase 3 (Módulo 4): tasas de costos indirectos (gastos generales, beneficio, IVA)
que convierten el costo directo en precio de venta. Una fila por organización.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'cost_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('overhead_pct', sa.Float(), nullable=False, server_default='0.15'),
        sa.Column('profit_pct', sa.Float(), nullable=False, server_default='0.10'),
        sa.Column('iva_pct', sa.Float(), nullable=False, server_default='0.21'),
    )


def downgrade() -> None:
    op.drop_table('cost_settings')
