"""juegos de reglas: terminaciones (revoque fino, pintura, cerámicos) y aberturas

Revision ID: t9b0c1d2e3f4
Revises: s8a9b0c1d2e3
Create Date: 2026-10-22

El presupuesto cubría solo la obra gruesa. Se agregan las reglas de fábrica de
revoque fino, fijador y pintura (muro_m2, dos caras), revestimiento cerámico
(revestimiento_m2), piso cerámico (sup_cubierta_m2) y puertas / ventanas
(puerta_u, ventana_u), con su mano de obra. Se aplica a TODOS los juegos: el del
sistema (is_system) y las copias de las organizaciones:
- Cada regla se agrega solo si el juego no tiene ya una con esa medida y
  etiqueta (no duplica lo que el usuario cargó a mano ni lo que sembró la app).
- Los materiales van después de los de su familia (muros, pisos/losas o al final
  de los materiales) y la mano de obra después de la de su medida (o al final);
  las posiciones del juego se renumeran 0..n-1.
Es idempotente. El downgrade borra solo las reglas idénticas a las que agrega el
upgrade (medida, tipo, rubro, etiqueta, palabras clave, exclusiones, unidad,
factor, modo, desperdicio y, en mano de obra, rendimiento, modo y cuadrilla; las
notas y la posición no cuentan). Valores copiados de budget_rules (la migración
no importa la app).
"""
import sqlalchemy as sa
from alembic import op

revision = "t9b0c1d2e3f4"
down_revision = "s8a9b0c1d2e3"
branch_labels = None
depends_on = None

_PEGAMENTO_NOTE = "Pegamento cementicio, ~5 kg/m²."
_PASTINA_NOTE = "~0,3 kg/m² con juntas de 2-3 mm."
_ABERTURA_EX = ["cerradura", "bisagra", "manija", "burlete"]

# (measure, label, rubro, keywords, unit, factor, waste, excludes, notes) — material, mode fixed.
WALL_RULES = [
    ("muro_m2", "Revoque fino (2 caras)", "Revoques", ["revoque fino"], "kg", 8.0, 10, [],
     "Revoque fino premezclado, ~4 kg/m² por cara."),
    ("muro_m2", "Fijador (2 caras)", "Pintura", ["fijador"], "l", 0.2, 5, [],
     "Fijador sellador, ~0,1 l/m² por cara."),
    ("muro_m2", "Pintura látex (2 caras, 2 manos)", "Pintura", ["latex", "látex"], "l", 0.5, 5,
     ["cielorraso"], "Látex interior, 2 manos: ~0,25 l/m² por cara."),
    ("revestimiento_m2", "Cerámico de revestimiento", "Revestimientos",
     ["ceramico", "revestimiento"], "m2", 1.0, 10, ["piso", "ladrillo", "pegamento", "pastina"],
     "m² de muros con material cerámico en el modelo (una cara)."),
    ("revestimiento_m2", "Pegamento para cerámicos", "Revestimientos", ["pegamento"], "kg", 5.0,
     5, ["porcelanato"], _PEGAMENTO_NOTE),
    ("revestimiento_m2", "Pastina", "Revestimientos", ["pastina"], "kg", 0.3, 5, [],
     _PASTINA_NOTE),
]
FLOOR_RULES = [
    ("sup_cubierta_m2", "Piso cerámico", "Pisos", ["piso ceramico", "ceramico"], "m2", 1.0, 10,
     ["revestimiento", "ladrillo", "pegamento", "pastina"],
     "m² de superficie cubierta (pisos del modelo)."),
    ("sup_cubierta_m2", "Pegamento (piso)", "Pisos", ["pegamento"], "kg", 5.0, 5,
     ["porcelanato"], _PEGAMENTO_NOTE),
    ("sup_cubierta_m2", "Pastina (piso)", "Pisos", ["pastina"], "kg", 0.3, 5, [], _PASTINA_NOTE),
]
OPENING_RULES = [
    ("puerta_u", "Puerta", "Aberturas", ["puerta"], "u", 1.0, 0,
     ["cerradura", "bisagra", "picaporte", "manija", "burlete"],
     "Una por puerta del modelo; elegí el modelo y la medida en el proveedor."),
    ("ventana_u", "Ventana", "Aberturas", ["ventana"], "u", 1.0, 0, _ABERTURA_EX,
     "Una por ventana del modelo; elegí el modelo y la medida en el proveedor."),
]

_CREW = [{"trade": "Oficial", "count": 1}, {"trade": "Ayudante", "count": 1}]
_UNITS = {"muro_m2": "m2", "revestimiento_m2": "m2", "sup_cubierta_m2": "m2",
          "puerta_u": "u", "ventana_u": "u"}
# (measure, label, rubro, rendimiento por día) — cuadrilla oficial + ayudante.
WALL_LABOR = [
    ("muro_m2", "Mano de obra: revoque fino (2 caras)", "Revoques", 8.0),
    ("muro_m2", "Mano de obra: pintura (2 caras)", "Pintura", 15.0),
    ("revestimiento_m2", "Mano de obra: revestimiento cerámico", "Revestimientos", 8.0),
]
FLOOR_LABOR = [("sup_cubierta_m2", "Mano de obra: piso cerámico", "Pisos", 10.0)]
OPENING_LABOR = [
    ("puerta_u", "Mano de obra: colocación de puertas", "Aberturas", 4.0),
    ("ventana_u", "Mano de obra: colocación de ventanas", "Aberturas", 4.0),
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
    # none_as_null: crew vacío queda NULL en SQL, como lo deja el ORM al sembrar.
    sa.column("crew", sa.JSON(none_as_null=True)),
)


def _material(rule) -> dict:
    measure, label, stage, kw, unit, factor, waste, ex, notes = rule
    return {"measure": measure, "label": label, "keywords": list(kw),
            "exclude_keywords": list(ex), "unit": unit, "factor": factor, "mode": "fixed",
            "waste_pct": float(waste), "notes": notes, "kind": "material", "stage": stage,
            "daily_yield": None, "labor_mode": None, "unit_price": None, "crew": None}


def _labor(rule) -> dict:
    measure, label, stage, y = rule
    return {"measure": measure, "label": label, "keywords": [], "exclude_keywords": [],
            "unit": _UNITS[measure], "factor": 1.0, "mode": "fixed", "waste_pct": 0.0,
            "notes": "Rendimiento de referencia: ajustalo a tu gente.",
            "kind": "labor", "stage": stage, "daily_yield": y, "labor_mode": "unit",
            "unit_price": None, "crew": [dict(c) for c in _CREW]}


def _same(row, spec: dict) -> bool:
    """¿La fila es idéntica a `spec`? Ignora notas y posición."""
    return (row.measure == spec["measure"] and row.kind == spec["kind"]
            and row.stage == spec["stage"] and row.label == spec["label"]
            and list(row.keywords or []) == spec["keywords"]
            and list(row.exclude_keywords or []) == spec["exclude_keywords"]
            and row.unit == spec["unit"] and row.mode == spec["mode"]
            and abs((row.factor or 0.0) - spec["factor"]) < 1e-9
            and abs((row.waste_pct or 0.0) - spec["waste_pct"]) < 1e-9
            and (spec["kind"] != "labor" or (
                row.daily_yield == spec["daily_yield"]
                and row.labor_mode == spec["labor_mode"]
                and row.unit_price == spec["unit_price"]
                and (row.crew or None) == spec["crew"])))


def _set_ids(conn) -> list:
    return [r[0] for r in conn.execute(sa.text("SELECT id FROM rule_sets ORDER BY id")).all()]


def _rows(conn, rs_id) -> list:
    return list(conn.execute(
        sa.select(*rules.c).where(rules.c.rule_set_id == rs_id)
        .order_by(rules.c.position, rules.c.id)).all())


def _apply(conn, rs_id, order: list) -> None:
    """`order`: ids existentes (int) o dicts de reglas nuevas. Inserta las nuevas
    y deja position = índice para todas."""
    for pos, item in enumerate(order):
        if isinstance(item, dict):
            conn.execute(rules.insert().values(rule_set_id=rs_id, position=pos, **item))
        else:
            conn.execute(rules.update().where(rules.c.id == item).values(position=pos))


def _insert_after(order: list, info: dict, preds: list, new: dict) -> None:
    """Inserta `new` después del último elemento (existente o recién agregado)
    que cumple el primer predicado de `preds` con alguna coincidencia; si
    ninguno coincide, al final."""
    def view(it):
        return info[it] if not isinstance(it, dict) else _Spec(it)

    for p in preds:
        idx = max((i for i, it in enumerate(order) if p(view(it))), default=None)
        if idx is not None:
            order.insert(idx + 1, new)
            return
    order.append(new)


class _Spec:
    """Un dict de regla nueva visto con atributos, como una fila."""

    def __init__(self, d: dict):
        self.__dict__.update(d)


def upgrade() -> None:
    conn = op.get_bind()
    for rs_id in _set_ids(conn):
        rows = _rows(conn, rs_id)
        info = {r.id: r for r in rows}
        have = {(r.measure, r.label) for r in rows}
        order: list = [r.id for r in rows]
        added = False

        def mat(*measures):
            return lambda r: r.kind == "material" and r.measure in measures

        def lab(*measures):
            return lambda r: r.kind == "labor" and r.measure in measures

        def is_mat(r) -> bool:
            return r.kind == "material"

        def is_lab(r) -> bool:
            return r.kind == "labor"

        def add(spec: dict, *preds) -> None:
            nonlocal added
            if (spec["measure"], spec["label"]) in have:
                return
            _insert_after(order, info, list(preds), spec)
            have.add((spec["measure"], spec["label"]))
            added = True

        for r in WALL_RULES:
            add(_material(r), mat("muro_m2", "revestimiento_m2"), is_mat)
        for r in FLOOR_RULES:
            add(_material(r), mat("sup_cubierta_m2", "losa_m2", "techo_m2"), is_mat)
        for r in OPENING_RULES:
            add(_material(r), mat("puerta_u", "ventana_u"), is_mat)
        for r in WALL_LABOR:
            add(_labor(r), lab("muro_m2", "revestimiento_m2"), is_lab)
        for r in FLOOR_LABOR:
            add(_labor(r), lab("sup_cubierta_m2"), is_lab)
        for r in OPENING_LABOR:
            add(_labor(r), lab("puerta_u", "ventana_u"), is_lab)

        if added:
            _apply(conn, rs_id, order)


def downgrade() -> None:
    conn = op.get_bind()
    specs = ([_material(r) for r in WALL_RULES + FLOOR_RULES + OPENING_RULES]
             + [_labor(r) for r in WALL_LABOR + FLOOR_LABOR + OPENING_LABOR])
    for rs_id in _set_ids(conn):
        rows = _rows(conn, rs_id)
        drop_ids: list = []
        for spec in specs:
            hit = next((r for r in rows if r.id not in drop_ids and _same(r, spec)), None)
            if hit is not None:
                drop_ids.append(hit.id)
        if drop_ids:
            conn.execute(rules.delete().where(rules.c.id.in_(drop_ids)))
            _apply(conn, rs_id, [r.id for r in rows if r.id not in drop_ids])
