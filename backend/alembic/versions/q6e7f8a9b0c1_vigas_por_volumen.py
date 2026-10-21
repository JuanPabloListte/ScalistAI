"""juego estándar: hormigón de vigas por volumen, entrepisos y viguetas

Revision ID: q6e7f8a9b0c1
Revises: p5d6e7f8a9b0
Create Date: 2026-10-21

Solo toca el juego del sistema ("Estándar Argentina", is_system), no los de
las organizaciones:
- Borra las 3 reglas de material de hormigón de vigas sobre viga_ml (sección
  supuesta 20 × 30) y en su lugar pone las mismas sobre viga_m3 con el H21 de
  columnas, más la vigueta pretensada (vigueta_ml).
- Agrega las 4 reglas de losa de entrepiso (losa_m2) después de las del techo
  y la mano de obra de entrepiso después de la de losa de cubierta.
- Renumera las posiciones para que queden 0..n-1 en ese orden.
Si el juego no existe se siembra con esto en el primer uso; si ya tiene reglas
sobre viga_m3 no se hace nada. Las reglas están copiadas de budget_rules (la
migración no importa la app).
"""
import sqlalchemy as sa
from alembic import op

revision = "q6e7f8a9b0c1"
down_revision = "p5d6e7f8a9b0"
branch_labels = None
depends_on = None

_AGGREG = ["grancilla", "piedra partida", "canto rodado"]
_HORMIGON_NOTE = "Hormigón H21: 350 kg de cemento, 0,65 m³ de arena y 0,75 m³ de piedra por m³."
_CEM_EX = ["pegamento", "albanileria"]

# (measure, label, keywords, unit, factor, waste, excludes, notes) — mode fixed, rubro Estructura.
OLD_BEAM_RULES = [
    ("viga_ml", "Cemento (hormigón vigas)", ["cemento"], "kg", 21.0, 5, _CEM_EX,
     "Sección supuesta 20 × 30 cm = 0,06 m³ por metro (el IFC no trae la sección)."),
    ("viga_ml", "Arena gruesa (hormigón vigas)", ["arena gruesa"], "m3", 0.039, 10, [], None),
    ("viga_ml", "Piedra (hormigón vigas)", _AGGREG, "m3", 0.045, 10, [], None),
]
NEW_BEAM_RULES = [
    ("viga_m3", "Cemento (hormigón vigas)", ["cemento"], "kg", 350.0, 5, _CEM_EX, _HORMIGON_NOTE),
    ("viga_m3", "Arena gruesa (hormigón vigas)", ["arena gruesa"], "m3", 0.65, 10, [], None),
    ("viga_m3", "Piedra (hormigón vigas)", _AGGREG, "m3", 0.75, 10, [], None),
    ("vigueta_ml", "Vigueta pretensada", ["vigueta"], "m", 1.0, 3, [],
     "Metros de vigueta del modelo."),
]
SLAB_RULES = [
    ("losa_m2", "Ladrillo de losa (entrepiso)", ["losa"], "u", 5.5, 5, ["pegamento"],
     "Losa de viguetas cada 50 cm con ladrillo cerámico de 25 × 38/40."),
    ("losa_m2", "Cemento (capa de compresión, entrepiso)", ["cemento"], "kg", 17.5, 5, _CEM_EX,
     "Capa de compresión de 5 cm (0,05 m³/m²)."),
    ("losa_m2", "Arena gruesa (capa de compresión, entrepiso)", ["arena gruesa"], "m3", 0.0325,
     10, [], None),
    ("losa_m2", "Piedra (capa de compresión, entrepiso)", _AGGREG, "m3", 0.0375, 10, [], None),
]
SLAB_LABOR = {"measure": "losa_m2", "label": "Mano de obra: losa de entrepiso",
              "keywords": [], "exclude_keywords": [], "unit": "m2", "factor": 1.0,
              "mode": "fixed", "waste_pct": 0.0,
              "notes": "Rendimiento de referencia: ajustalo a tu gente.",
              "kind": "labor", "stage": "Estructura", "daily_yield": 10.0,
              "labor_mode": "unit", "unit_price": None,
              "crew": [{"trade": "Oficial", "count": 1}, {"trade": "Ayudante", "count": 2}]}

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
    # none_as_null: crew vacío queda NULL en SQL, como lo deja el ORM al sembrar.
    sa.column("crew", sa.JSON(none_as_null=True)),
)


def _material(rule) -> dict:
    measure, label, kw, unit, factor, waste, ex, notes = rule
    return {"measure": measure, "label": label, "keywords": list(kw),
            "exclude_keywords": list(ex), "unit": unit, "factor": factor, "mode": "fixed",
            "waste_pct": float(waste), "notes": notes, "kind": "material",
            "stage": "Estructura", "daily_yield": None, "labor_mode": None,
            "unit_price": None, "crew": None}


def _system_id(conn):
    return conn.execute(sa.text(
        "SELECT id FROM rule_sets WHERE is_system ORDER BY id LIMIT 1")).scalar()


def _current(conn, rs_id) -> list:
    return list(conn.execute(
        sa.select(rules.c.id, rules.c.measure, rules.c.kind)
        .where(rules.c.rule_set_id == rs_id)
        .order_by(rules.c.position, rules.c.id)).all())


def _apply(conn, rs_id, order: list) -> None:
    """`order`: lista de ids existentes (int) o dicts de reglas nuevas. Inserta
    las nuevas y deja position = índice para todas."""
    for pos, item in enumerate(order):
        if isinstance(item, dict):
            conn.execute(rules.insert().values(rule_set_id=rs_id, position=pos, **item))
        else:
            conn.execute(rules.update().where(rules.c.id == item).values(position=pos))


def _insert_after(order: list, pred, new: list) -> None:
    """Inserta `new` después del último elemento existente que cumple `pred`;
    si no hay ninguno, al final."""
    idx = max((i for i, it in enumerate(order) if not isinstance(it, dict) and pred(it)),
              default=None)
    at = len(order) if idx is None else idx + 1
    order[at:at] = new


def upgrade() -> None:
    conn = op.get_bind()
    rs_id = _system_id(conn)
    if rs_id is None:
        return
    rows = _current(conn, rs_id)
    if any(r.measure == "viga_m3" for r in rows):
        return
    info = {r.id: r for r in rows}
    old_ids = [r.id for r in rows if r.measure == "viga_ml" and r.kind == "material"]

    order: list = []
    beams_placed = False
    for r in rows:
        if r.id in old_ids:
            if not beams_placed:
                order += [_material(x) for x in NEW_BEAM_RULES]
                beams_placed = True
            continue
        order.append(r.id)
    if not beams_placed:  # alguien las borró: van después de las de columnas
        _insert_after(order, lambda i: info[i].kind == "material"
                      and info[i].measure == "columna_m3",
                      [_material(x) for x in NEW_BEAM_RULES])
    is_mat = lambda i: info[i].kind == "material"  # noqa: E731
    # Entrepiso después del techo; si no hay techo, al final de los materiales.
    has_roof = any(is_mat(i) and info[i].measure == "techo_m2"
                   for i in order if not isinstance(i, dict))
    _insert_after(order, (lambda i: is_mat(i) and info[i].measure == "techo_m2") if has_roof
                  else is_mat, [_material(x) for x in SLAB_RULES])
    _insert_after(order, lambda i: info[i].kind == "labor" and info[i].measure == "techo_m2",
                  [dict(SLAB_LABOR)])

    if old_ids:
        conn.execute(rules.delete().where(rules.c.id.in_(old_ids)))
    _apply(conn, rs_id, order)


def downgrade() -> None:
    conn = op.get_bind()
    rs_id = _system_id(conn)
    if rs_id is None:
        return
    rows = _current(conn, rs_id)
    new_measures = ("viga_m3", "vigueta_ml", "losa_m2")
    drop_ids = [r.id for r in rows if r.measure in new_measures
                and (r.kind == "material" or r.measure == "losa_m2")]
    if not drop_ids:
        return
    order: list = []
    beams_placed = False
    for r in rows:
        if r.id in drop_ids:
            if r.measure == "viga_m3" and r.kind == "material" and not beams_placed:
                order += [_material(x) for x in OLD_BEAM_RULES]
                beams_placed = True
            continue
        order.append(r.id)
    conn.execute(rules.delete().where(rules.c.id.in_(drop_ids)))
    _apply(conn, rs_id, order)
