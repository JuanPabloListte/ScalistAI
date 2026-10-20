"""rubro en las reglas de material + membrete del estudio (logo y contacto)

Revision ID: p5d6e7f8a9b0
Revises: o4c5d6e7f8a9
Create Date: 2026-10-19

- organizations: logo_path (archivo en storage/logos) y contact_info (texto
  libre: dirección, teléfono, mail, CUIT) para el membrete del PDF.
- Reglas de material del juego del sistema: rubro según la medida, para que el
  presupuesto por rubros agrupe materiales y mano de obra juntos.
"""
from alembic import op
import sqlalchemy as sa

revision = "p5d6e7f8a9b0"
down_revision = "o4c5d6e7f8a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("logo_path", sa.String(512), nullable=True))
    op.add_column("organizations", sa.Column("contact_info", sa.Text(), nullable=True))
    sys_rules = ("kind = 'material' AND stage IS NULL AND rule_set_id IN "
                 "(SELECT id FROM rule_sets WHERE is_system)")
    op.execute(f"UPDATE rules SET stage = 'Revoques' WHERE {sys_rules} "
               "AND measure = 'muro_m2' AND lower(label) LIKE '%revoque%'")
    for measure, stage in [("muro_m2", "Mampostería"), ("columna_m3", "Estructura"),
                           ("viga_ml", "Estructura"), ("armadura_kg", "Estructura"),
                           ("riostra_ml", "Fundaciones"), ("techo_m2", "Cubierta")]:
        op.execute(f"UPDATE rules SET stage = '{stage}' WHERE {sys_rules} "
                   f"AND measure = '{measure}'")


def downgrade() -> None:
    op.drop_column("organizations", "contact_info")
    op.drop_column("organizations", "logo_path")
