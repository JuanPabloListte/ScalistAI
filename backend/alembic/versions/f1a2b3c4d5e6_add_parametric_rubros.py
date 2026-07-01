"""Add parametric_rubros a cost_settings (rubros llave-en-mano estimados)

Revision ID: a1b2c3d4e5f6
Revises: c9d0e1f2a3b4
Create Date: 2026-07-01

Los modelos IFC (y planos) suelen traer solo la obra gris (estructura +
mampostería + aberturas). Los rubros que NO están en el modelo —fundaciones,
instalaciones eléctrica/sanitaria/gas, terminaciones— se estiman como % sobre
la obra gris, práctica estándar de cómputo. Se guardan como JSON por org
(editable). NULL = usar los defaults del repo.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('cost_settings', sa.Column('parametric_rubros', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('cost_settings', 'parametric_rubros')
