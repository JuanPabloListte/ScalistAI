"""Tareas del cronograma desde el presupuesto del proyecto (proveedor × reglas × IFC).

Una tarea por (rubro, medida, nivel): "Mampostería (muros) — PB". De cada
tarea sale:
- costo = materiales de esa medida y rubro (con el redondeo de la lista de
  compras repartido, así la suma da el neto del presupuesto) + mano de obra;
- duración = días de las reglas de mano de obra (medida / rendimiento) / cuadrillas.

Entre niveles se reparte por la proporción de la medida en cada piso. Una
tarea sin rendimiento (p.ej. armadura, que no tiene regla de mano de obra)
acompaña a la tarea más larga de su etapa y nivel.

`budget_tasks` es puro (recibe la vista del presupuesto); el wrapper con DB
es `compute_budget_tasks`.
"""
from __future__ import annotations

import math
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services import budget_rules as br

# Orden de obra de los rubros conocidos; el resto va después, alfabético.
STAGE_ORDER = ("Fundaciones", "Estructura", "Mampostería", "Cubierta", "Revoques",
               "Pisos", "Cielorrasos", "Terminaciones")

_SHORT = {"muro_m2": "muros", "columna_m3": "columnas", "viga_ml": "vigas",
          "viga_m3": "hormigón de vigas",
          "vigueta_ml": "viguetas", "losa_m2": "entrepisos",
          "riostra_ml": "riostras", "riostra_m3": "hormigón de fundaciones",
          "techo_m2": "techo", "sup_cubierta_m2": "pisos",
          "cielorraso_m2": "cielorrasos", "armadura_kg": "armadura"}
_UNIT = {"m2": "m²", "m3": "m³", "m": "ml", "kg": "kg"}


def task_name(stage: str, measure: str) -> str:
    short = _SHORT.get(measure, measure)
    return stage if stage.lower() == short else f"{stage} ({short})"


def _stage_orders(stages) -> dict[str, int]:
    known = {s: i + 1 for i, s in enumerate(STAGE_ORDER)}
    extra = sorted(s for s in stages if s not in known)
    return {**known, **{s: len(STAGE_ORDER) + 1 + i for i, s in enumerate(extra)}}


def material_costs(budget: dict | None) -> dict[str, float]:
    """item key → costo, repartiendo el subtotal de cada renglón de la lista
    de compras (unidades redondeadas arriba) entre los ítems que lo usan."""
    if not budget:
        return {}
    units = {it["key"]: it.get("units_to_buy") or 0.0
             for it in budget["items"] if it.get("status") == "ok"}
    out: dict[str, float] = {}
    for s in budget.get("shopping_list") or []:
        keys = [k for k in s.get("items") or [] if k in units]
        total_units = sum(units[k] for k in keys)
        left = s["subtotal"]
        for i, k in enumerate(keys):
            if i == len(keys) - 1:
                share = left
            else:
                share = round(s["subtotal"] * units[k] / total_units, 2) if total_units else 0.0
                left = round(left - share, 2)
            out[k] = round(out.get(k, 0.0) + share, 2)
    return out


def budget_tasks(view: dict, by_level: list[tuple[str | None, int | None, br.Measures]],
                 crews: int = 1) -> list[dict]:
    """Tareas sin fechas (las pone schedule.lay_out). `by_level`: medidas del
    IFC por piso [(nivel, orden, Measures)]; un único (None, None, m) sin pisos."""
    crews = max(1, crews)
    groups: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"materials": 0.0, "labor": 0.0, "days": 0.0, "has_yield": False})

    mat = material_costs(view.get("budget"))
    for it in (view.get("budget") or {}).get("items") or []:
        if it["key"] not in mat or it.get("measure") not in br.MEASURES:
            continue
        stage = it.get("stage") or br.MEASURE_STAGE.get(it["measure"], "Sin rubro")
        groups[(stage, it["measure"])]["materials"] += mat[it["key"]]
    for it in (view.get("labor") or {}).get("items") or []:
        if it.get("measure") not in br.MEASURES:
            continue
        g = groups[(it["stage"], it["measure"])]
        g["labor"] += it.get("cost") or 0.0
        if it.get("days"):
            g["days"] += it["days"]
            g["has_yield"] = True

    totals: dict[str, float] = defaultdict(float)
    for _, _, m in by_level:
        for k, v in m.values.items():
            totals[k] += v
    orders = _stage_orders({s for s, _ in groups})

    tasks: list[dict] = []
    for (stage, measure), g in groups.items():
        total = totals.get(measure, 0.0)
        cost = round(g["materials"] + g["labor"], 2)
        if total <= 0 or (cost <= 0 and not g["has_yield"]):
            continue
        levels = [(lvl, lo, m.values.get(measure, 0.0)) for lvl, lo, m in by_level]
        levels = [x for x in levels if x[2] > 0]
        left = cost
        for i, (lvl, lo, qty) in enumerate(levels):
            share = qty / total
            c = left if i == len(levels) - 1 else round(cost * share, 2)
            left = round(left - c, 2)
            name = task_name(stage, measure)
            days = math.ceil(g["days"] * share / crews - 1e-9) if g["has_yield"] else None
            tasks.append({
                "assembly": f"{name} — {lvl}" if lvl else name, "assembly_id": None,
                "measure": measure, "level": lvl, "level_order": lo,
                "stage": stage, "stage_order": orders[stage],
                "quantity": round(qty, 1), "unit": _UNIT.get(br.MEASURES[measure][1], ""),
                "duration_days": max(1, days or 1), "_no_yield": days is None,
                "cost": round(c, 2),
                "materials_cost": round(g["materials"] * share, 2),
                "labor_cost": round(g["labor"] * share, 2),
            })

    # Sin rendimiento: dura lo que la tarea más larga de su etapa y nivel.
    longest: dict[tuple, int] = {}
    for t in tasks:
        if not t["_no_yield"]:
            k = (t["stage"], t["level"])
            longest[k] = max(longest.get(k, 1), t["duration_days"])
    for t in tasks:
        if t.pop("_no_yield"):
            t["duration_days"] = longest.get((t["stage"], t["level"]), 1)
        t["daily_cost"] = round(t["cost"] / max(1, t["duration_days"]), 2)
    return tasks


def project_measures_by_level(project_id: int, db: Session) -> list[tuple]:
    """Medidas del último IFC listo, separadas por piso (mismos elementos que
    budget_rules.project_measures)."""
    from app.models.detected_element import DetectedElement
    from app.models.plan import Plan

    plan = db.scalar(
        select(Plan)
        .where(Plan.project_id == project_id, Plan.status == "ready",
               Plan.original_filename.ilike("%.ifc"))
        .order_by(Plan.id.desc()))
    if plan is None:
        return []
    elements = db.scalars(select(DetectedElement).where(
        DetectedElement.plan_id == plan.id, DetectedElement.is_candidate.is_(False))).all()
    groups: dict[tuple, list] = defaultdict(list)
    for e in elements:
        groups[(getattr(e, "level", None), getattr(e, "level_order", None))].append(e)
    ordered = sorted(groups.items(),
                     key=lambda kv: (kv[0][1] if kv[0][1] is not None else -1, kv[0][0] or ""))
    return [(lvl, lo, br.measures_from_elements(els)) for (lvl, lo), els in ordered]


def compute_budget_tasks(project_id: int, db: Session, crews: int = 1) -> list[dict]:
    from app.models.project import Project
    from app.services.project_budget import build_view

    project = db.get(Project, project_id)
    if project is None:
        return []
    view = build_view(project, db)
    if view["measures"] is None:
        return []
    return budget_tasks(view, project_measures_by_level(project_id, db), crews)
