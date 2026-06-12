"""Add is_candidate and confidence to detected_elements

Revision ID: a1b2c3d4e5f6
Revises: 5539a7e60576
Create Date: 2026-06-12

Soporte del esquema híbrido (vectorial + IA): la IA puede proponer elementos
que el CAD no trae (is_candidate=True, no computan hasta aceptarse) y cada
elemento lleva un nivel de confianza 0.0-1.0.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '5539a7e60576'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'detected_elements',
        sa.Column('is_candidate', sa.Boolean(), server_default='false', nullable=False),
    )
    op.add_column(
        'detected_elements',
        sa.Column('confidence', sa.Float(), server_default='1.0', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('detected_elements', 'confidence')
    op.drop_column('detected_elements', 'is_candidate')
