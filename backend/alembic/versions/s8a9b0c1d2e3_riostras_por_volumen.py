"""juegos de reglas: hormigón de riostras (vigas de fundación) por volumen

Revision ID: s8a9b0c1d2e3
Revises: r7f8a9b0c1d2
Create Date: 2026-10-22

Las 3 reglas de material de hormigón de riostras iban por metro lineal
(riostra_ml, sección supuesta 20 × 30 cm). Ahora van sobre riostra_m3 (volumen
real del IFC) con el H21 de columnas y vigas. Se aplica a TODOS los juegos: el
del sistema (is_system) y las copias de las organizaciones, con el criterio de
r7f8a9b0c1d2:
- Cada regla vieja se reemplaza en el mismo lugar SOLO si sigue idéntica a la
  de fábrica (medida, tipo, rubro, etiqueta, palabras clave, exclusiones,
  unidad, factor, modo y desperdicio; las notas y la posición no cuentan). Si
  el usuario la tocó, queda como está.
- El rubro vacío (copias anteriores a p5d6e7f8a9b0) cuenta como "Fundaciones",
  que es el rubro por defecto de la medida; al reemplazar queda "Fundaciones".
- La mano de obra de vigas de fundación sigue en riostra_ml: no se toca.
Es idempotente (tras el upgrade ya no hay reglas idénticas a las viejas). El
downgrade vuelve a riostra_ml solo las reglas idénticas a las que puso el
upgrade. Valores copiados de budget_rules (la migración no importa la app).
"""
import sqlalchemy as sa
from alembic import op

revision = "s8a9b0c1d2e3"
down_revision = "r7f8a9b0c1d2"
branch_labels = None
depends_on = None

_AGGREG = ["grancilla", "piedra partida", "canto rodado"]
_HORMIGON_NOTE = "Hormigón H21: 350 kg de cemento, 0,65 m³ de arena y 0,75 m³ de piedra por m³."
_CEM_EX = ["pegamento", "albanileria"]
_STAGE = "Fundaciones"

# (measure, label, keywords, unit, factor, waste, excludes, notes) — material, mode fixed.
OLD_RULES = [
    ("riostra_ml", "Cemento (hormigón riostras)", ["cemento"], "kg", 21.0, 5, _CEM_EX,
     "Sección supuesta 20 × 30 cm = 0,06 m³ por metro."),
    ("riostra_ml", "Arena gruesa (hormigón riostras)", ["arena gruesa"], "m3", 0.039, 10, [], None),
    ("riostra_ml", "Piedra (hormigón riostras)", _AGGREG, "m3", 0.045, 10, [], None),
]
NEW_RULES = [
    ("riostra_m3", "Cemento (hormigón riostras)", ["cemento"], "kg", 350.0, 5, _CEM_EX,
     _HORMIGON_NOTE),
    ("riostra_m3", "Arena gruesa (hormigón riostras)", ["arena gruesa"], "m3", 0.65, 10, [], None),
    ("riostra_m3", "Piedra (hormigón riostras)", _AGGREG, "m3", 0.75, 10, [], None),
]

rules = sa.table(
    "rules",
    sa.column("id", sa.Integer), sa.column("rule_set_id", sa.Integer),
    sa.column("position", sa.Integer), sa.column("measure", sa.String),
    sa.column("label", sa.String), sa.column("keywords", sa.JSON),
    sa.column("exclude_keywords", sa.JSON), sa.column("unit", sa.String),
    sa.column("factor", sa.Float), sa.column("mode", sa.String),
    sa.column("waste_pct", sa.Float), sa.column("notes", sa.Text),
    sa.column("kind", sa.String), sa.column("stage", sa.String),
    sa.column("daily_yield", sa.Float), sa.column("labor_mode", sa.String),
    sa.column("unit_price", sa.Float),
)


def _material(rule) -> dict:
    measure, label, kw, unit, factor, waste, ex, notes = rule
    return {"measure": measure, "label": label, "keywords": list(kw),
            "exclude_keywords": list(ex), "unit": unit, "factor": factor, "mode": "fixed",
            "waste_pct": float(waste), "notes": notes, "kind": "material", "stage": _STAGE}


def _same(row, spec: dict) -> bool:
    """¿La fila es idéntica a `spec`? Ignora notas y posición; rubro vacío =
    rubro por defecto de la medida (Fundaciones)."""
    return (row.measure == spec["measure"] and row.kind == spec["kind"]
            and ((row.stage or "").strip() or _STAGE) == spec["stage"]
            and row.label == spec["label"]
            and list(row.keywords or []) == spec["keywords"]
            and list(row.exclude_keywords or []) == spec["exclude_keywords"]
            and row.unit == spec["unit"] and row.mode == spec["mode"]
            and abs((row.factor or 0.0) - spec["factor"]) < 1e-9
            and abs((row.waste_pct or 0.0) - spec["waste_pct"]) < 1e-9)


def _swap(conn, src: list, dst: list) -> None:
    """En cada juego, la regla idéntica a src[i] pasa a ser dst[i] (en el lugar,
    cada fila una sola vez)."""
    set_ids = [r[0] for r in conn.execute(sa.text("SELECT id FROM rule_sets ORDER BY id"))]
    for rs_id in set_ids:
        rows = list(conn.execute(
            sa.select(*rules.c).where(rules.c.rule_set_id == rs_id,
                                      rules.c.measure.in_(("riostra_ml", "riostra_m3")))
            .order_by(rules.c.position, rules.c.id)).all())
        used: set = set()
        for old, new in zip(src, dst):
            spec = _material(old)
            hit = next((r for r in rows if r.id not in used and _same(r, spec)), None)
            if hit is None:
                continue
            used.add(hit.id)
            conn.execute(rules.update().where(rules.c.id == hit.id).values(**_material(new)))


def upgrade() -> None:
    _swap(op.get_bind(), OLD_RULES, NEW_RULES)


def downgrade() -> None:
    _swap(op.get_bind(), NEW_RULES, OLD_RULES)
