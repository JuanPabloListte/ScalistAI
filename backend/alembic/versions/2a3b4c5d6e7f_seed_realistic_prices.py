"""seed_realistic_prices

Revision ID: 2a3b4c5d6e7f
Revises: 1fc6c0fbe443
Create Date: 2026-05-22 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '2a3b4c5d6e7f'
down_revision: Union[str, None] = '1fc6c0fbe443'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Update seeded prices to realistic averages
    op.execute("UPDATE material_yields SET unit_price = 350.00 WHERE material_id = 1")
    op.execute("UPDATE material_yields SET unit_price = 4500.00 WHERE material_id = 2")
    op.execute("UPDATE material_yields SET unit_price = 12500.00 WHERE material_id = 3")
    op.execute("UPDATE material_yields SET unit_price = 1800.00 WHERE material_id = 4")


def downgrade() -> None:
    op.execute("UPDATE material_yields SET unit_price = 0.0 WHERE material_id IN (1, 2, 3, 4)")
