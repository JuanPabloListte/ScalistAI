"""mano de obra en las reglas de cómputo + ajustes del presupuesto por proyecto

Revision ID: o4c5d6e7f8a9
Revises: n3b4c5d6e7f8
Create Date: 2026-10-19

- rules: kind (material | labor), stage (rubro), daily_yield (unidades/día de
  una cuadrilla), labor_mode (unit | daily), unit_price, crew.
- project_budget_settings: por proyecto, el modo y el precio de cada rubro de
  mano de obra y los márgenes si difieren de los de la empresa.
- Agrega las reglas de mano de obra de referencia al juego "Estándar Argentina"
  si ya existe (si no, se siembra con ellas en el primer uso).
"""
import json

from alembic import op
import sqlalchemy as sa

revision = "o4c5d6e7f8a9"
down_revision = "n3b4c5d6e7f8"
branch_labels = None
depends_on = None

_CUADRILLA_2 = [{"trade": "Oficial", "count": 1}, {"trade": "Ayudante", "count": 1}]
_CUADRILLA_3 = [{"trade": "Oficial", "count": 1}, {"trade": "Ayudante", "count": 2}]
_NOTA = "Rendimiento de referencia: ajustalo a tu gente."

# Igual que budget_rules.DEFAULT_LABOR_RULES (copiado: la migración no importa la app).
LABOR_RULES = [
    ("muro_m2", "Mano de obra: mampostería", "Mampostería", 8.0, _CUADRILLA_2),
    ("muro_m2", "Mano de obra: revoques (2 caras)", "Revoques", 6.0, _CUADRILLA_2),
    ("columna_m3", "Mano de obra: columnas de H°A°", "Estructura", 0.5, _CUADRILLA_3),
    ("viga_ml", "Mano de obra: vigas de H°A°", "Estructura", 4.0, _CUADRILLA_3),
    ("riostra_ml", "Mano de obra: vigas de fundación", "Fundaciones", 5.0, _CUADRILLA_3),
    ("techo_m2", "Mano de obra: losa de cubierta", "Cubierta", 10.0, _CUADRILLA_3),
    ("sup_cubierta_m2", "Mano de obra: contrapiso y carpeta", "Pisos", 12.0, _CUADRILLA_2),
    ("cielorraso_m2", "Mano de obra: cielorrasos", "Terminaciones", 10.0, _CUADRILLA_2),
]


def upgrade() -> None:
    op.add_column("rules", sa.Column("kind", sa.String(16), nullable=False,
                                     server_default="material"))
    op.add_column("rules", sa.Column("stage", sa.String(64), nullable=True))
    op.add_column("rules", sa.Column("daily_yield", sa.Float(), nullable=True))
    op.add_column("rules", sa.Column("labor_mode", sa.String(16), nullable=True))
    op.add_column("rules", sa.Column("unit_price", sa.Float(), nullable=True))
    op.add_column("rules", sa.Column("crew", sa.JSON(), nullable=True))

    op.create_table(
        "project_budget_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("labor", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("overhead_pct", sa.Float(), nullable=True),
        sa.Column("profit_pct", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    )
    op.create_index("ix_project_budget_settings_project_id", "project_budget_settings",
                    ["project_id"], unique=True)

    conn = op.get_bind()
    system_id = conn.execute(sa.text(
        "SELECT id FROM rule_sets WHERE is_system ORDER BY id LIMIT 1")).scalar()
    if system_id is None:
        return
    pos = conn.execute(sa.text(
        "SELECT COALESCE(MAX(position), -1) FROM rules WHERE rule_set_id = :rs"),
        {"rs": system_id}).scalar()
    unit = {"muro_m2": "m2", "columna_m3": "m3", "viga_ml": "m", "riostra_ml": "m",
            "techo_m2": "m2", "sup_cubierta_m2": "m2", "cielorraso_m2": "m2"}
    for measure, label, stage, yield_, crew in LABOR_RULES:
        pos += 1
        conn.execute(sa.text(
            "INSERT INTO rules (rule_set_id, position, measure, label, keywords, "
            "exclude_keywords, unit, factor, mode, waste_pct, notes, kind, stage, "
            "daily_yield, labor_mode, unit_price, crew) VALUES (:rs, :pos, :m, :l, '[]', "
            "'[]', :u, 1, 'fixed', 0, :n, 'labor', :st, :y, 'unit', NULL, :crew)"),
            {"rs": system_id, "pos": pos, "m": measure, "l": label, "u": unit[measure],
             "n": _NOTA, "st": stage, "y": yield_, "crew": json.dumps(crew)})


def downgrade() -> None:
    op.execute("DELETE FROM rules WHERE kind = 'labor'")
    op.drop_index("ix_project_budget_settings_project_id", "project_budget_settings")
    op.drop_table("project_budget_settings")
    for col in ("crew", "unit_price", "labor_mode", "daily_yield", "stage", "kind"):
        op.drop_column("rules", col)
