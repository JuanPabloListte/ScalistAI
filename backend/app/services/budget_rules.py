"""Presupuesto por reglas: medidas del IFC × reglas → productos del proveedor.

1. `measures_from_elements`: resume los DetectedElement del IFC en medidas
   (m² de muro, m³ de columnas, ml de vigas, kg de armadura por diámetro...).
2. Cada regla del juego convierte una medida en cantidad de un producto
   (kg de cemento, m³ de arena, unidades de ladrillo, barras de hierro).
3. El producto se busca en la lista del proveedor por palabras clave y se
   convierte a la unidad de venta (bolsa de 25 kg, camión de 6 m³, barra de
   12 m). Entre varios candidatos gana el más barato por unidad de producto.
4. La lista de compras agrupa por renglón del proveedor y redondea hacia
   arriba (no se compran 3,4 bolsas): ese es el total de materiales.
5. Las reglas de mano de obra (kind="labor") cotizan cada rubro por unidad
   (tercerizado, $/m²) o por jornal (rendimiento × cuadrilla × jornal), y el
   precio de venta suma gastos generales, beneficio e IVA.

Todo es puro (sin DB) salvo los helpers de juegos de reglas del final.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

IVA_RATE = 0.21

# ---------------------------------------------------------------------------
# Medidas del modelo
# ---------------------------------------------------------------------------

# clave → (etiqueta, unidad). El orden es el que ve el usuario.
MEASURES: dict[str, tuple[str, str]] = {
    "muro_m2": ("Muros (largo × alto, sin aberturas)", "m2"),
    "columna_m3": ("Columnas (volumen)", "m3"),
    "viga_ml": ("Vigas (largo)", "m"),
    "riostra_ml": ("Vigas de fundación / riostras (largo)", "m"),
    "techo_m2": ("Techo / losa de cubierta (superficie)", "m2"),
    "sup_cubierta_m2": ("Superficie cubierta (pisos)", "m2"),
    "cielorraso_m2": ("Cielorrasos (superficie)", "m2"),
    "armadura_kg": ("Armadura (kg de hierro, por diámetro)", "kg"),
}

MODES = ("fixed", "brick_dims", "rebar")
UNITS = ("kg", "m3", "m2", "m", "l", "u")
KINDS = ("material", "labor")
LABOR_MODES = ("unit", "daily")
# Rubro por defecto de cada medida, para reglas que no traen el suyo.
MEASURE_STAGE: dict[str, str] = {
    "muro_m2": "Mampostería", "columna_m3": "Estructura", "viga_ml": "Estructura",
    "riostra_ml": "Fundaciones", "techo_m2": "Cubierta", "sup_cubierta_m2": "Pisos",
    "cielorraso_m2": "Cielorrasos", "armadura_kg": "Estructura",
}


def stage_of(rule) -> str:
    return (rule.stage or "").strip() or MEASURE_STAGE.get(rule.measure, "Sin rubro")


# Oficios de la tabla de jornales que se ofrecen por defecto.
DEFAULT_TRADES = ("Oficial especializado", "Oficial", "Medio oficial", "Ayudante")

# Diámetros comerciales (mm) para redondear lo que sale del modelo: los Revit
# con biblioteca US traen 3/8" (9,5 mm) o 5/8" (15,9 mm).
COMMERCIAL_DIAMETERS = (4.2, 5.0, 6.0, 8.0, 10.0, 12.0, 16.0, 20.0, 25.0, 32.0)
KG_PER_M_PER_MM2 = 0.006165  # 7850 kg/m³ × π/4 × 1e-6
DEFAULT_BAR_LENGTH_M = 12.0
MORTAR_JOINT_M = 0.015


def snap_diameter(d: float) -> float:
    return min(COMMERCIAL_DIAMETERS, key=lambda c: abs(c - d))


@dataclass
class Measures:
    values: dict[str, float] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    rebar_kg: dict[float, float] = field(default_factory=dict)  # diámetro → kg
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "measures": [
                {"key": k, "label": lbl, "unit": unit,
                 "value": round(self.values.get(k, 0.0), 3),
                 "count": self.counts.get(k, 0)}
                for k, (lbl, unit) in MEASURES.items()
            ],
            "rebar_by_diameter": [
                {"diameter_mm": d, "kg": round(kg, 2)}
                for d, kg in sorted(self.rebar_kg.items())
            ],
            "warnings": self.warnings,
        }


def measures_from_elements(elements: Iterable) -> Measures:
    """`elements`: objetos con type, length_m, area_m2, height_m, geometry."""
    m = Measures()
    add = lambda k, v: (m.values.__setitem__(k, m.values.get(k, 0.0) + v),  # noqa: E731
                        m.counts.__setitem__(k, m.counts.get(k, 0) + 1))
    snapped: dict[float, float] = {}
    bars_without_kg = 0
    openings_m2 = 0.0
    for e in elements:
        t = e.type
        L, A, H = e.length_m or 0.0, e.area_m2 or 0.0, e.height_m or 0.0
        if t == "wall" and L and H:
            add("muro_m2", L * H)
        elif t == "opening" and L and H:
            openings_m2 += L * H
        elif t == "column" and A and H:
            add("columna_m3", A * H)
        elif t == "beam" and L:
            add("viga_ml", L)
        elif t == "riostra" and L:
            add("riostra_ml", L)
        elif t == "roof" and A:
            add("techo_m2", A)
        elif t == "room" and A:
            add("sup_cubierta_m2", A)
        elif t == "cielorraso" and A:
            add("cielorraso_m2", A)
        elif t == "armadura":
            kg = (e.geometry or {}).get("kg")
            if not kg or not L:
                bars_without_kg += 1
                continue
            d_raw = math.sqrt(kg / L / KG_PER_M_PER_MM2)
            d = snap_diameter(d_raw)
            if abs(d - d_raw) > 0.3:
                snapped[d] = snapped.get(d, 0.0) + L
            m.rebar_kg[d] = m.rebar_kg.get(d, 0.0) + kg
            add("armadura_kg", kg)
    if openings_m2 and m.values.get("muro_m2"):
        gross = m.values["muro_m2"]
        m.values["muro_m2"] = max(gross - openings_m2, 0.0)
        m.warnings.append(
            f"Muros: {gross:,.1f} m² brutos − {openings_m2:,.1f} m² de puertas y ventanas.")
    for d, metros in sorted(snapped.items()):
        m.warnings.append(
            f"{metros:,.0f} m de armadura con diámetro no comercial (medida en "
            f"pulgadas en el modelo) se computan como Ø{d:g}.")
    if bars_without_kg:
        m.warnings.append(
            f"{bars_without_kg} barras de armadura sin largo/sección en el IFC no se computan.")
    return m


# ---------------------------------------------------------------------------
# Matching de productos
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def _word_rx(word: str) -> re.Pattern:
    w = re.escape(word)
    if re.fullmatch(r"\d+(?:[.,]\d+)?", word):
        # "12" matchea "PORTANTE 12" y "12X19X33", no "120" ni "4.12".
        return re.compile(rf"(?<![\d.,]){w}(?![\d]|[.,]\d)")
    # Palabras: borde a izquierda, plural opcional ("hierros", "cales").
    return re.compile(rf"(?<![a-z]){w}(?:s|es)?(?![a-z])")


def matches_keywords(description: str, keywords: list[str], exclude: list[str]) -> bool:
    text = _norm(description)

    def phrase_ok(phrase: str) -> bool:
        words = _norm(phrase).split()
        return bool(words) and all(_word_rx(w).search(text) for w in words)

    if exclude and any(phrase_ok(p) for p in exclude):
        return False
    return any(phrase_ok(p) for p in keywords)


_UNIT_FACTORS = {("m3", "l"): 1000.0, ("l", "m3"): 0.001}


def amount_in_unit(presentation: dict, unit: str, diameter: float | None = None) -> float | None:
    """Cuánto de `unit` trae UNA unidad vendida. None si no es convertible."""
    p_amount, p_unit = presentation.get("amount") or 1.0, presentation.get("unit") or "u"
    if p_unit == unit:
        return p_amount
    if (p_unit, unit) in _UNIT_FACTORS:
        return p_amount * _UNIT_FACTORS[(p_unit, unit)]
    if unit == "kg" and diameter:
        # Barra de hierro vendida por metro o por unidad (= barra de 12 m).
        length = p_amount if p_unit == "m" else (DEFAULT_BAR_LENGTH_M if p_unit == "u" else None)
        if length:
            return KG_PER_M_PER_MM2 * diameter ** 2 * length
    return None


def bricks_per_m2(dims: list[float] | None) -> float | None:
    """Unidades por m² de muro según las medidas del ladrillo en cm (AxBxC):
    la cara vista son las dos medidas mayores, más 1,5 cm de junta."""
    if not dims or len(dims) < 3:
        return None
    a, b = sorted(dims)[-2:]
    return 1.0 / ((a / 100 + MORTAR_JOINT_M) * (b / 100 + MORTAR_JOINT_M))


# ---------------------------------------------------------------------------
# Cálculo
# ---------------------------------------------------------------------------

@dataclass
class RuleSpec:
    """Forma mínima de una regla (sirve para el modelo ORM y para tests)."""
    id: int | None
    measure: str
    label: str
    keywords: list[str]
    unit: str
    factor: float
    mode: str = "fixed"
    waste_pct: float = 0.0
    exclude_keywords: list[str] = field(default_factory=list)
    notes: str | None = None
    kind: str = "material"
    stage: str | None = None
    daily_yield: float | None = None
    labor_mode: str | None = None
    unit_price: float | None = None
    crew: list[dict] | None = None

    @classmethod
    def of(cls, r) -> "RuleSpec":
        return cls(id=r.id, measure=r.measure, label=r.label, keywords=list(r.keywords or []),
                   unit=r.unit, factor=r.factor, mode=r.mode, waste_pct=r.waste_pct or 0.0,
                   exclude_keywords=list(r.exclude_keywords or []), notes=r.notes,
                   kind=getattr(r, "kind", None) or "material", stage=getattr(r, "stage", None),
                   daily_yield=getattr(r, "daily_yield", None),
                   labor_mode=getattr(r, "labor_mode", None),
                   unit_price=getattr(r, "unit_price", None),
                   crew=list(getattr(r, "crew", None) or []) or None)


def _candidates(rule: RuleSpec, lines: list[dict], diameter: float | None) -> list[dict]:
    out = []
    for ln in lines:
        if ln.get("unit_price_net") is None:
            continue
        if not matches_keywords(ln["description"], rule.keywords, rule.exclude_keywords):
            continue
        pres = ln.get("presentation") or {}
        attrs = pres.get("attrs") or {}
        if diameter is not None:
            ld = attrs.get("diameter_mm")
            if ld is None or abs(ld - diameter) > 0.3:
                continue
        per_sale = amount_in_unit(pres, rule.unit, diameter)
        if not per_sale:
            continue
        factor = rule.factor
        if rule.mode == "brick_dims":
            factor = bricks_per_m2(attrs.get("dims")) or rule.factor
        out.append({"line": ln, "per_sale": per_sale, "factor": factor,
                    # costo por unidad de MEDIDA: compara ladrillos de distinto tamaño
                    "cost_per_measure": ln["unit_price_net"] / per_sale * factor})
    out.sort(key=lambda c: c["cost_per_measure"])
    return out


def _line_ref(ln: dict) -> dict:
    return {"row": ln["row"], "code": ln.get("code"), "description": ln["description"],
            "unit_price_net": ln["unit_price_net"], "presentation": ln.get("presentation")}


def compute_budget(
    measures: Measures,
    rules: list[RuleSpec],
    lines: list[dict],
    overrides: dict[str, int | None] | None = None,
) -> dict:
    """Aplica las reglas. `overrides`: item_key → row del proveedor elegido a
    mano (None = sin precio a propósito). item_key = "<rule_id>" o
    "<rule_id>:d<diámetro>" para armaduras."""
    overrides = overrides or {}
    by_row = {ln["row"]: ln for ln in lines}
    items: list[dict] = []

    for idx, rule in enumerate(rules):
        if rule.kind == "labor":
            continue  # la mano de obra se calcula aparte (compute_labor)
        rid = rule.id if rule.id is not None else f"n{idx}"
        if rule.measure not in MEASURES:
            items.append({"key": str(rid), "rule_id": rule.id, "label": rule.label,
                          "status": "regla_invalida", "measure": rule.measure})
            continue
        m_label, m_unit = MEASURES[rule.measure]
        if rule.mode == "rebar":
            targets = [(f"{rid}:d{d:g}", f"{rule.label} Ø{d:g}", kg, d)
                       for d, kg in sorted(measures.rebar_kg.items())]
            if not targets:
                targets = [(str(rid), rule.label, 0.0, None)]
        else:
            targets = [(str(rid), rule.label, measures.values.get(rule.measure, 0.0), None)]

        for key, label, base, diameter in targets:
            item = {
                "key": key, "rule_id": rule.id, "label": label, "stage": stage_of(rule),
                "measure": rule.measure, "measure_label": m_label, "measure_unit": m_unit,
                "measure_value": round(base, 3), "unit": rule.unit,
                "waste_pct": rule.waste_pct, "notes": rule.notes,
                "factor": rule.factor, "quantity": None, "line": None,
                "units_to_buy": None, "subtotal": None, "alternatives": [],
            }
            if diameter is not None:
                item["diameter_mm"] = diameter
            cands = _candidates(rule, lines, diameter)
            item["alternatives"] = [_line_ref(c["line"]) for c in cands[1:6]]

            chosen = cands[0] if cands else None
            if key in overrides:
                row = overrides[key]
                chosen = None
                if row is not None and row in by_row:
                    ln = by_row[row]
                    pres = ln.get("presentation") or {}
                    per_sale = amount_in_unit(pres, rule.unit, diameter)
                    factor = rule.factor
                    if rule.mode == "brick_dims":
                        factor = bricks_per_m2((pres.get("attrs") or {}).get("dims")) or rule.factor
                    chosen = {"line": ln, "per_sale": per_sale, "factor": factor} if per_sale else None
                    if not per_sale:
                        item["status"] = "unidad_incompatible"
                item["manual"] = True

            factor = chosen["factor"] if chosen else (
                1.0 if rule.mode == "rebar" else rule.factor)
            if rule.mode == "rebar":
                factor = 1.0  # base ya está en kg
            qty = base * factor * (1 + (rule.waste_pct or 0) / 100)
            item["factor"] = round(factor, 4)
            item["quantity"] = round(qty, 3)

            if base <= 0:
                item["status"] = "sin_medida"
            elif chosen is None:
                item.setdefault("status", "sin_precio")
            else:
                ln = chosen["line"]
                units = qty / chosen["per_sale"]
                item.update({
                    "status": "ok",
                    "line": _line_ref(ln),
                    "per_sale": round(chosen["per_sale"], 4),
                    "units_to_buy": round(units, 3),
                    "subtotal": round(units * ln["unit_price_net"], 2),
                })
            items.append(item)

    # Lista de compras: por renglón del proveedor, unidades redondeadas arriba.
    shopping: dict[int, dict] = {}
    for it in items:
        if it.get("status") != "ok":
            continue
        row = it["line"]["row"]
        s = shopping.setdefault(row, {**it["line"], "units": 0.0, "items": []})
        s["units"] += it["units_to_buy"]
        s["items"].append(it["key"])
    shopping_list = []
    for s in sorted(shopping.values(), key=lambda s: s["row"]):
        buy = math.ceil(s["units"] - 1e-9)
        shopping_list.append({**s, "units": round(s["units"], 3), "units_to_buy": buy,
                              "subtotal": round(buy * s["unit_price_net"], 2)})

    used_rows = set(shopping)
    net = round(sum(s["subtotal"] for s in shopping_list), 2)
    return {
        "items": items,
        "shopping_list": shopping_list,
        "unused_lines": [_line_ref(ln) for ln in lines if ln["row"] not in used_rows],
        "totals": {"net": net, "iva": round(net * IVA_RATE, 2),
                   "total": round(net * (1 + IVA_RATE), 2), "iva_rate": IVA_RATE},
        "counts": {
            "ok": sum(1 for i in items if i.get("status") == "ok"),
            "sin_precio": sum(1 for i in items if i.get("status") == "sin_precio"),
            "sin_medida": sum(1 for i in items if i.get("status") == "sin_medida"),
        },
    }


# ---------------------------------------------------------------------------
# Mano de obra y precio de venta
# ---------------------------------------------------------------------------

def compute_labor(
    measures: Measures,
    rules: list[RuleSpec],
    trade_costs: dict[str, float],
    settings: dict[str, dict] | None = None,
) -> dict:
    """Costo de mano de obra por rubro.

    Cada regla de mano de obra se cotiza en uno de dos modos (la regla trae el
    habitual y `settings` lo puede pisar por proyecto, junto con el precio):
    - unit: medida × precio por unidad (tercerizado: "$ 18.000 por m²").
    - daily: días = medida / rendimiento; costo = días × Σ(cuadrilla × jornal).
    `trade_costs`: oficio → costo por día para la empresa (con cargas).
    El rendimiento da los días también en modo unit (los usa el cronograma).
    """
    settings = settings or {}
    items: list[dict] = []
    for idx, rule in enumerate(rules):
        if rule.kind != "labor":
            continue
        rid = rule.id if rule.id is not None else f"n{idx}"
        over = settings.get(str(rid)) or {}
        mode = over.get("mode") or rule.labor_mode or "unit"
        m_label, m_unit = MEASURES.get(rule.measure, (rule.measure, ""))
        qty = measures.values.get(rule.measure, 0.0) if rule.measure in MEASURES else 0.0
        crew = [c for c in (rule.crew or []) if c.get("trade") and (c.get("count") or 0) > 0]
        y = rule.daily_yield or 0.0
        days = qty / y if y > 0 else None
        item = {
            "key": str(rid), "rule_id": rule.id, "label": rule.label,
            "stage": stage_of(rule), "measure": rule.measure,
            "measure_label": m_label, "measure_unit": m_unit, "quantity": round(qty, 3),
            "mode": mode, "daily_yield": rule.daily_yield, "crew": crew,
            "notes": rule.notes, "days": round(days, 2) if days is not None else None,
            "workdays": None, "unit_price": None, "cost": None,
            "manual": bool(over), "missing_trades": [],
        }
        if qty <= 0:
            item["status"] = "sin_medida"
        elif mode == "daily":
            missing = [c["trade"] for c in crew if not trade_costs.get(c["trade"])]
            if days is None:
                item["status"] = "sin_rendimiento"
            elif not crew or missing:
                item["status"] = "sin_jornal"
                item["missing_trades"] = missing
            else:
                per_day = sum(c["count"] * trade_costs[c["trade"]] for c in crew)
                item.update({
                    "status": "ok", "unit_price": round(per_day / y, 2),
                    "workdays": round(days * sum(c["count"] for c in crew), 1),
                    "cost": round(days * per_day, 2),
                })
        else:
            price = over["unit_price"] if "unit_price" in over else rule.unit_price
            if price is None or price <= 0:
                item["status"] = "sin_precio"
            else:
                item.update({"status": "ok", "unit_price": round(float(price), 2),
                             "cost": round(qty * float(price), 2)})
        items.append(item)

    stages: dict[str, dict] = {}
    for it in items:
        s = stages.setdefault(it["stage"], {"stage": it["stage"], "cost": 0.0, "items": []})
        s["items"].append(it["key"])
        if it["cost"]:
            s["cost"] = round(s["cost"] + it["cost"], 2)
    return {
        "items": items,
        "by_stage": list(stages.values()),
        "total": round(sum(i["cost"] or 0 for i in items), 2),
        "counts": {
            "ok": sum(1 for i in items if i["status"] == "ok"),
            "pendientes": sum(1 for i in items if i["status"] in
                              ("sin_precio", "sin_jornal", "sin_rendimiento")),
            "sin_medida": sum(1 for i in items if i["status"] == "sin_medida"),
        },
    }


def compute_price(materials_net: float, labor_total: float, *, overhead_pct: float,
                  profit_pct: float, iva_pct: float = IVA_RATE) -> dict:
    """Costo directo (materiales + mano de obra) → precio de venta, con la
    cuenta de cost_intelligence: directo + GG% = costo; + beneficio% sobre el
    costo = precio sin IVA; + IVA."""
    from decimal import Decimal

    from app.cost_intelligence.domain.pricing_breakdown import IndirectRates, build_price
    from app.cost_intelligence.domain.value_objects import Money

    direct = Money(Decimal(str(materials_net)) + Decimal(str(labor_total)))
    b = build_price(direct, IndirectRates(Decimal(str(overhead_pct)), Decimal(str(profit_pct)),
                                          Decimal(str(iva_pct))))
    f = lambda m: float(m.amount)  # noqa: E731
    return {"materials": round(materials_net, 2), "labor": round(labor_total, 2),
            "direct": f(b.direct), "overhead": f(b.overhead), "profit": f(b.profit),
            "net": f(b.net), "iva": f(b.iva), "total": f(b.total),
            "overhead_pct": overhead_pct, "profit_pct": profit_pct, "iva_pct": iva_pct}


# ---------------------------------------------------------------------------
# Juego de reglas por defecto
# ---------------------------------------------------------------------------

DEFAULT_RULE_SET_NAME = "Estándar Argentina"
DEFAULT_RULE_SET_DESCRIPTION = (
    "Valores de referencia para obra húmeda tradicional (ladrillo cerámico + "
    "hormigón armado H21). Revisalos y ajustalos a tu forma de construir.")

_AGGREG = ["grancilla", "piedra partida", "canto rodado"]
_HORMIGON_NOTE = "Hormigón H21: 350 kg de cemento, 0,65 m³ de arena y 0,75 m³ de piedra por m³."

# (measure, label, keywords, unit, factor, mode, waste, excludes, notes)
DEFAULT_RULES: list[tuple] = [
    ("muro_m2", "Ladrillo portante 12", ["portante 12"], "u", 15.0, "brick_dims", 5, [],
     "Unidades por m² según las medidas del ladrillo del proveedor (+1,5 cm de "
     "junta). Si no trae medidas, 15 u/m²."),
    ("muro_m2", "Cemento (mortero de asiento)", ["cemento"], "kg", 3.0, "fixed", 5,
     ["pegamento", "albanileria"], "Mortero 1/4:1:4, ~0,02 m³ por m² de muro."),
    ("muro_m2", "Cal hidratada (mortero de asiento)", ["cal hidratada"], "kg", 5.0, "fixed", 5,
     [], None),
    ("muro_m2", "Arena gruesa (mortero de asiento)", ["arena gruesa"], "m3", 0.025, "fixed", 10,
     [], None),
    ("muro_m2", "Cemento (revoque grueso, 2 caras)", ["cemento"], "kg", 2.0, "fixed", 5,
     ["pegamento", "albanileria"], "Revoque grueso a la cal reforzado, 1,5 cm por cara."),
    ("muro_m2", "Cal hidratada (revoque grueso, 2 caras)", ["cal hidratada"], "kg", 8.0, "fixed",
     5, [], None),
    ("muro_m2", "Arena fina (revoque, 2 caras)", ["arena fina"], "m3", 0.04, "fixed", 10, [], None),
    ("columna_m3", "Cemento (hormigón columnas)", ["cemento"], "kg", 350.0, "fixed", 5,
     ["pegamento", "albanileria"], _HORMIGON_NOTE),
    ("columna_m3", "Arena gruesa (hormigón columnas)", ["arena gruesa"], "m3", 0.65, "fixed", 10,
     [], None),
    ("columna_m3", "Piedra (hormigón columnas)", _AGGREG, "m3", 0.75, "fixed", 10, [], None),
    ("viga_ml", "Cemento (hormigón vigas)", ["cemento"], "kg", 21.0, "fixed", 5,
     ["pegamento", "albanileria"],
     "Sección supuesta 20 × 30 cm = 0,06 m³ por metro (el IFC no trae la sección)."),
    ("viga_ml", "Arena gruesa (hormigón vigas)", ["arena gruesa"], "m3", 0.039, "fixed", 10,
     [], None),
    ("viga_ml", "Piedra (hormigón vigas)", _AGGREG, "m3", 0.045, "fixed", 10, [], None),
    ("riostra_ml", "Cemento (hormigón riostras)", ["cemento"], "kg", 21.0, "fixed", 5,
     ["pegamento", "albanileria"], "Sección supuesta 20 × 30 cm = 0,06 m³ por metro."),
    ("riostra_ml", "Arena gruesa (hormigón riostras)", ["arena gruesa"], "m3", 0.039, "fixed", 10,
     [], None),
    ("riostra_ml", "Piedra (hormigón riostras)", _AGGREG, "m3", 0.045, "fixed", 10, [], None),
    ("techo_m2", "Ladrillo de losa (cerámico)", ["losa"], "u", 5.5, "fixed", 5,
     ["pegamento"], "Losa de viguetas cada 50 cm con ladrillo cerámico de 25 × 38/40."),
    ("techo_m2", "Cemento (capa de compresión)", ["cemento"], "kg", 17.5, "fixed", 5,
     ["pegamento", "albanileria"], "Capa de compresión de 5 cm (0,05 m³/m²)."),
    ("techo_m2", "Arena gruesa (capa de compresión)", ["arena gruesa"], "m3", 0.0325, "fixed",
     10, [], None),
    ("techo_m2", "Piedra (capa de compresión)", _AGGREG, "m3", 0.0375, "fixed", 10, [], None),
    ("armadura_kg", "Hierro", ["hierro", "acero"], "kg", 1.0, "rebar", 8, ["alambre", "malla"],
     "Un ítem por diámetro; kg exactos del modelo convertidos a barras de 12 m."),
    ("armadura_kg", "Alambre de atar", ["alambre"], "kg", 0.02, "fixed", 0, [],
     "~2% del peso del hierro."),
]


_CUADRILLA_2 = [{"trade": "Oficial", "count": 1}, {"trade": "Ayudante", "count": 1}]
_CUADRILLA_3 = [{"trade": "Oficial", "count": 1}, {"trade": "Ayudante", "count": 2}]
_LABOR_NOTE = "Rendimiento de referencia: ajustalo a tu gente."

# (measure, label, rubro, rendimiento por día de la cuadrilla, cuadrilla).
# Modo por defecto: tercerizado (precio por unidad, que carga cada proyecto).
# Hay copia en la migración o4c5d6e7f8a9 para juegos ya sembrados.
DEFAULT_LABOR_RULES: list[tuple] = [
    ("muro_m2", "Mano de obra: mampostería", "Mampostería", 8.0, _CUADRILLA_2),
    ("muro_m2", "Mano de obra: revoques (2 caras)", "Revoques", 6.0, _CUADRILLA_2),
    ("columna_m3", "Mano de obra: columnas de H°A°", "Estructura", 0.5, _CUADRILLA_3),
    ("viga_ml", "Mano de obra: vigas de H°A°", "Estructura", 4.0, _CUADRILLA_3),
    ("riostra_ml", "Mano de obra: vigas de fundación", "Fundaciones", 5.0, _CUADRILLA_3),
    ("techo_m2", "Mano de obra: losa de cubierta", "Cubierta", 10.0, _CUADRILLA_3),
    ("sup_cubierta_m2", "Mano de obra: contrapiso y carpeta", "Pisos", 12.0, _CUADRILLA_2),
    ("cielorraso_m2", "Mano de obra: cielorrasos", "Terminaciones", 10.0, _CUADRILLA_2),
]


def _default_rules():
    from app.models.rule_set import Rule

    rules = [
        Rule(position=i, measure=m, label=lbl, keywords=list(kw), unit=u, factor=f,
             mode=mode, waste_pct=w, exclude_keywords=list(ex), notes=notes,
             stage="Revoques" if "revoque" in lbl.lower() else MEASURE_STAGE[m])
        for i, (m, lbl, kw, u, f, mode, w, ex, notes) in enumerate(DEFAULT_RULES)
    ]
    start = len(rules)
    rules += [
        Rule(position=start + i, measure=m, label=lbl, keywords=[], exclude_keywords=[],
             unit=MEASURES[m][1], factor=1.0, mode="fixed", waste_pct=0.0, notes=_LABOR_NOTE,
             kind="labor", stage=stage, daily_yield=y, labor_mode="unit", unit_price=None,
             crew=[dict(c) for c in crew])
        for i, (m, lbl, stage, y, crew) in enumerate(DEFAULT_LABOR_RULES)
    ]
    return rules


def ensure_system_rule_set(db: Session):
    """Devuelve el juego global del sistema ("Estándar Argentina"), sembrándolo
    si no existe. Idempotente también entre requests concurrentes (la UI pide
    lista + presupuesto a la vez): un lock de transacción serializa el
    chequeo y el insert."""
    from sqlalchemy import func

    from app.models.rule_set import RuleSet

    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(select(func.pg_advisory_xact_lock(func.hashtext("rule_sets_seed"), 0)))
    existing = db.scalar(select(RuleSet).where(RuleSet.is_system.is_(True))
                         .order_by(RuleSet.id))
    if existing is not None:
        return existing
    rs = RuleSet(organization_id=None, name=DEFAULT_RULE_SET_NAME,
                 description=DEFAULT_RULE_SET_DESCRIPTION, is_default=True,
                 is_system=True, rules=_default_rules())
    db.add(rs)
    db.flush()
    return rs


def list_rule_sets(organization_id: int, db: Session) -> list:
    from app.models.rule_set import RuleSet

    from sqlalchemy import or_

    ensure_system_rule_set(db)
    return list(db.scalars(
        select(RuleSet)
        .where(or_(RuleSet.organization_id == organization_id, RuleSet.is_system.is_(True)))
        .options(selectinload(RuleSet.rules))
        .order_by(RuleSet.is_system.desc(), RuleSet.name.asc())
    ).all())


def duplicate_rule_set(src, name: str, organization_id: int, db: Session):
    """Copia `src` (de la org o el del sistema) a la org dada, editable."""
    from app.models.rule_set import Rule, RuleSet

    rs = RuleSet(organization_id=organization_id, name=name,
                 description=src.description, is_default=False,
                 rules=[Rule(position=r.position, measure=r.measure, label=r.label,
                             keywords=list(r.keywords), exclude_keywords=list(r.exclude_keywords),
                             unit=r.unit, factor=r.factor, mode=r.mode,
                             waste_pct=r.waste_pct, notes=r.notes, kind=r.kind,
                             stage=r.stage, daily_yield=r.daily_yield,
                             labor_mode=r.labor_mode, unit_price=r.unit_price,
                             crew=[dict(c) for c in (r.crew or [])] or None)
                        for r in src.rules])
    db.add(rs)
    db.flush()
    return rs


def project_measures(project_id: int, db: Session) -> Measures | None:
    """Medidas del último IFC listo del proyecto, o None si no hay."""
    from app.models.detected_element import DetectedElement
    from app.models.plan import Plan

    plan = db.scalar(
        select(Plan)
        .where(Plan.project_id == project_id, Plan.status == "ready",
               Plan.original_filename.ilike("%.ifc"))
        .order_by(Plan.id.desc())
    )
    if plan is None:
        return None
    elements = db.scalars(
        select(DetectedElement).where(DetectedElement.plan_id == plan.id,
                                      DetectedElement.is_candidate.is_(False))
    ).all()
    return measures_from_elements(elements)
