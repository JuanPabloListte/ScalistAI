"""Add stage/stage_order to assemblies and start_date to projects

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-19

Cimiento de cronograma (Gantt) + curva de inversión + certificación: las
assemblies se agrupan en rubros/etapas de obra (Fundación, Estructura,
Mampostería, Instalaciones, Terminaciones) con un orden, y el proyecto lleva
fecha de inicio de obra.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('assemblies', sa.Column('stage', sa.String(length=64), nullable=True))
    op.add_column('assemblies', sa.Column('stage_order', sa.Integer(), server_default='0', nullable=False))
    op.add_column('projects', sa.Column('start_date', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('projects', 'start_date')
    op.drop_column('assemblies', 'stage_order')
    op.drop_column('assemblies', 'stage')
