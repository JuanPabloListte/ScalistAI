"""tenant_isolation

Revision ID: 7a0f8b8c1c2a
Revises: 600324646bb1
Create Date: 2026-06-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7a0f8b8c1c2a'
down_revision: Union[str, None] = '600324646bb1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Agregamos la columna con server_default=1 para que los datos actuales se asignen
    # a la organización por defecto.
    op.add_column('materials', sa.Column('organization_id', sa.Integer(), server_default='1', nullable=False))
    op.create_foreign_key(None, 'materials', 'organizations', ['organization_id'], ['id'], ondelete='CASCADE')

    op.add_column('assemblies', sa.Column('organization_id', sa.Integer(), server_default='1', nullable=False))
    op.create_foreign_key(None, 'assemblies', 'organizations', ['organization_id'], ['id'], ondelete='CASCADE')

def downgrade() -> None:
    op.drop_constraint(None, 'assemblies', type_='foreignkey')
    op.drop_column('assemblies', 'organization_id')

    op.drop_constraint(None, 'materials', type_='foreignkey')
    op.drop_column('materials', 'organization_id')
