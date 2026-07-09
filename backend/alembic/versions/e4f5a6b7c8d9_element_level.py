"""detected_elements: nivel BIM (storey) por elemento

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-07-09

level = nombre del IfcBuildingStorey ("Planta Baja"); level_order = índice por
elevación (0 = más bajo). NULL en fuentes sin nivel (PDF/DXF/manual). Habilita
tareas del cronograma por piso ("Mampostería — PB" antes que "— P1").
"""
from alembic import op
import sqlalchemy as sa

revision = "e4f5a6b7c8d9"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("detected_elements", sa.Column("level", sa.String(64), nullable=True))
    op.add_column("detected_elements", sa.Column("level_order", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("detected_elements", "level_order")
    op.drop_column("detected_elements", "level")
