"""Add material_groups (producto canónico) + materials.group_id

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-06-28

Une materiales equivalentes entre fuentes/fechas bajo un producto canónico,
para consolidar sus precios en UNA serie temporal real. El match lo aprueba un
humano (scripts/match_materials.py --suggest / --apply).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'material_groups',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('category', sa.String(length=100), nullable=False, server_default=''),
        sa.Column('unit', sa.String(length=32), nullable=False, server_default='un'),
    )
    op.add_column('materials', sa.Column('group_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_materials_group', 'materials', 'material_groups',
        ['group_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_materials_group_id', 'materials', ['group_id'])


def downgrade() -> None:
    op.drop_index('ix_materials_group_id', 'materials')
    op.drop_constraint('fk_materials_group', 'materials', type_='foreignkey')
    op.drop_column('materials', 'group_id')
    op.drop_table('material_groups')
