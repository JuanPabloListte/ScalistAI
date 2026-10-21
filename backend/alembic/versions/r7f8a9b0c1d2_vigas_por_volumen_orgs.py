"""juegos de reglas de las organizaciones: hormigón de vigas por volumen, entrepisos y viguetas

Revision ID: r7f8a9b0c1d2
Revises: q6e7f8a9b0c1
Create Date: 2026-10-21

q6e7f8a9b0c1 hizo estos cambios solo en el juego del sistema (is_system). Acá se
aplican a las copias de las organizaciones (is_system = false) sin pisar lo que el
usuario editó:
- Cada regla de vigas sobre viga_ml se reemplaza (en el mismo lugar) por la de
  viga_m3 SOLO si sigue idéntica a la de fábrica (medida, rubro, etiqueta,
  palabras clave, exclusiones, unidad, factor, modo y desperdicio; las notas y la
  posición no cuentan). Si el usuario la tocó, queda como está.
- Vigueta pretensada, las 4 reglas de losa de entrepiso y la mano de obra de
  entrepiso se agregan solo si la copia no tiene ya una regla con esa medida y
  etiqueta. Los materiales nuevos van después de las de su familia y la mano de
  obra después de la de techo; las posiciones se renumeran 0..n-1.
Es idempotente. El downgrade deshace solo lo que sigue idéntico a lo que puso el
upgrade: la regla viga_m3 vuelve a viga_ml; vigueta, losas y mano de obra se
borran. No toca el juego del sistema. Valores copiados de budget_rules (la
migración no importa la app).
"""
import sqlalchemy as sa
from alembic import op

revision = "r7f8a9b0c1d2"
down_revision = "q6e7f8a9b0c1"
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
]
VIGUETA = ("vigueta_ml", "Vigueta pretensada", ["vigueta"], "m", 1.0, 3, [],
           "Metros de vigueta del modelo.")
SLAB_RULES = [
    ("losa_m2", "Ladrillo de losa (entrepiso)", ["losa"], "u", 5.5, 5, ["pegamento"],
     "Losa de viguetas cada 50 cm con ladrillo cerámico de 25 × 38/40."),
    ("losa_m2", "Cemento (capa de compresión, entrepiso)", ["cemento"], "kg", 17.5, 5, _CEM_EX,
     "Capa de compresión de 5 cm (0,05 m³/m²)."),
    ("losa_m2", "Arena gruesa (capa de compresión, entrepiso)", ["arena gruesa"], "m3", 0.0325,
     10, [], None),
    ("losa_m2", "Piedra (capa de compresión, entrepiso)", _AGGREG, "m3", 0.0375, 10, [], None),
]
_CREW = [{"trade": "Oficial", "count": 1}, {"trade": "Ayudante", "count": 2}]
SLAB_LABOR = {"measure": "losa_m2", "label": "Mano de obra: losa de entrepiso",
              "keywords": [], "exclude_keywords": [], "unit": "m2", "factor": 1.0,
              "mode": "fixed", "waste_pct": 0.0,
              "notes": "Rendimiento de referencia: ajustalo a tu gente.",
              "kind": "labor", "stage": "Estructura", "daily_yield": 10.0,
              "labor_mode": "unit", "unit_price": None, "crew": _CREW}

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


def _same(row, spec: dict) -> bool:
    """¿La fila es idéntica a `spec`? Compara medida, tipo, rubro, etiqueta,
    palabras clave, exclusiones, unidad, factor, modo y desperdicio (y, en mano de
    obra, rendimiento, modo y cuadrilla). Ignora notas y posición."""
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


def _org_set_ids(conn) -> list:
    return [r[0] for r in conn.execute(sa.text(
        "SELECT id FROM rule_sets WHERE NOT is_system ORDER BY id")).all()]


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


def _insert_after(order: list, info: dict, pred, new: dict, fallback) -> None:
    """Inserta `new` después del último existente que cumple `pred`; si no hay,
    después del último que cumple `fallback`; si tampoco, al final."""
    ids = [(i, it) for i, it in enumerate(order) if not isinstance(it, dict)]
    for p in (pred, fallback):
        idx = max((i for i, it in ids if p(info[it])), default=None)
        if idx is not None:
            at = idx + 1
            while at < len(order) and isinstance(order[at], dict):
                at += 1  # después de lo que ya se agregó acá, para respetar el orden
            order.insert(at, new)
            return
    order.append(new)


def upgrade() -> None:
    conn = op.get_bind()
    for rs_id in _org_set_ids(conn):
        rows = _rows(conn, rs_id)
        changed = False

        # 1) Reglas de vigas viejas, idénticas a la de fábrica -> viga_m3 en el lugar.
        used: set = set()
        for old, new in zip(OLD_BEAM_RULES, NEW_BEAM_RULES):
            old_spec = _material(old)
            hit = next((r for r in rows if r.id not in used and _same(r, old_spec)), None)
            if hit is None:
                continue
            used.add(hit.id)
            conn.execute(rules.update().where(rules.c.id == hit.id).values(**_material(new)))
            changed = True
        if changed:
            rows = _rows(conn, rs_id)
        info = {r.id: r for r in rows}

        # 2) Reglas nuevas que falten (misma medida y etiqueta).
        have = {(r.measure, r.label) for r in rows}
        order: list = [r.id for r in rows]
        added = False

        def is_mat(r) -> bool:
            return r.kind == "material"

        def add(spec: dict, pred, fallback) -> None:
            nonlocal added
            if (spec["measure"], spec["label"]) in have:
                return
            _insert_after(order, info, pred, spec, fallback)
            have.add((spec["measure"], spec["label"]))
            added = True

        add(_material(VIGUETA),
            lambda r: is_mat(r) and r.measure == "viga_m3",
            lambda r: is_mat(r) and r.measure in ("viga_ml", "columna_m3"))
        for rule in SLAB_RULES:
            add(_material(rule),
                lambda r: is_mat(r) and r.measure in ("techo_m2", "losa_m2"), is_mat)
        add(dict(SLAB_LABOR, crew=list(_CREW)),
            lambda r: r.kind == "labor" and r.measure == "techo_m2",
            lambda r: r.kind == "labor")

        if added or changed:
            _apply(conn, rs_id, order)


def downgrade() -> None:
    conn = op.get_bind()
    for rs_id in _org_set_ids(conn):
        rows = _rows(conn, rs_id)
        # Borrar solo lo idéntico a lo que puso el upgrade (cada spec una vez).
        drops = [_material(VIGUETA)] + [_material(r) for r in SLAB_RULES] + [dict(SLAB_LABOR)]
        drop_ids: list = []
        for spec in drops:
            hit = next((r for r in rows if r.id not in drop_ids and _same(r, spec)), None)
            if hit is not None:
                drop_ids.append(hit.id)
        if drop_ids:
            conn.execute(rules.delete().where(rules.c.id.in_(drop_ids)))
        # viga_m3 idéntica -> viga_ml de fábrica, en el lugar.
        used: set = set()
        for old, new in zip(OLD_BEAM_RULES, NEW_BEAM_RULES):
            new_spec = _material(new)
            hit = next((r for r in rows if r.id not in used and _same(r, new_spec)), None)
            if hit is None:
                continue
            used.add(hit.id)
            conn.execute(rules.update().where(rules.c.id == hit.id).values(**_material(old)))
        if drop_ids:
            _apply(conn, rs_id, [r.id for r in rows if r.id not in drop_ids])
