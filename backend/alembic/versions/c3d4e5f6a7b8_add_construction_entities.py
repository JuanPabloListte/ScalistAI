"""Add construction_entities + link assemblies as recipe alternatives

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-26

Fase 0 del Motor de Inteligencia de Costos: formaliza el catálogo de entidades
constructivas (muro, losa, cubierta…) que hoy es un string suelto en
`Assembly.applies_to`. Cada entidad agrupa sus recetas alternativas (Ladrillo /
Durlock / Retak) → habilita el simulador de escenarios.

Solo schema. El backfill (crear entidades desde los applies_to existentes y
linkear assemblies) lo hace `scripts/seed_construction_entities.py` (idempotente).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'construction_entities',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(),
                  sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('type', sa.String(length=32), nullable=False),
        sa.Column('unit', sa.String(length=16), nullable=False),
        sa.Column('active', sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.create_index('ix_construction_entities_organization_id',
                    'construction_entities', ['organization_id'])

    op.add_column('assemblies', sa.Column('construction_entity_id', sa.Integer(),
                  sa.ForeignKey('construction_entities.id', ondelete='SET NULL'), nullable=True))
    op.add_column('assemblies', sa.Column('is_default_alternative', sa.Boolean(),
                  server_default='false', nullable=False))
    op.create_index('ix_assemblies_construction_entity_id',
                    'assemblies', ['construction_entity_id'])


def downgrade() -> None:
    op.drop_index('ix_assemblies_construction_entity_id', 'assemblies')
    op.drop_column('assemblies', 'is_default_alternative')
    op.drop_column('assemblies', 'construction_entity_id')
    op.drop_index('ix_construction_entities_organization_id', 'construction_entities')
    op.drop_table('construction_entities')
