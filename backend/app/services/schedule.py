"""Cronograma de obra (Gantt) + curva de inversión (flujo de fondos).

A partir de la geometría exacta y las recetas (assemblies con `daily_yield` y
`stage`), arma el cronograma: cada assembly es una TAREA con
duración = cantidad / rendimiento. Las tareas se agrupan en etapas (Fundación →
Estructura → Mampostería → Instalaciones → Terminaciones) que corren en orden;
dentro de una etapa las tareas son paralelas. Distribuyendo el costo de cada
tarea en sus días sale la curva de inversión mensual (curva S).

El costo por tarea usa la MISMA lógica que el cómputo de materiales (resta
aberturas en muros) → el total del cronograma coincide con el presupuesto.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.v1.plans._export import _opening_overlaps_wall
from app.models.detected_element import DetectedElement
from app.models.material import Assembly, AssemblyMaterial
from app.models.plan import Plan
from app.models.project import Project


def _area_for_cost(el: DetectedElement, applies_to: str,
                   openings_by_page: dict, page_scales: dict) -> float:
    """Medida del elemento en la unidad de la receta, para costo (muro resta
    aberturas, igual que el cómputo de materiales)."""
    if applies_to == "wall" and el.type == "wall":
        area = (el.length_m or 0.0) * (el.height_m or 2.8)
        scale = page_scales.get(str(el.page))
        if scale and scale > 0:
            for op in openings_by_page.get(el.page, []):
                if _opening_overlaps_wall(op, el, scale):
                    area -= (op.length_m or 0.0) * (op.height_m or 2.1)
        return max(area, 0.0)
    if applies_to in ("room_floor", "room_ceiling", "roof", "escalera") and el.area_m2:
        return el.area_m2
    if applies_to in ("room_wall",) and el.length_m:
        return (el.length_m or 0.0) * (el.height_m or 2.8)
    if applies_to in ("room_perimeter", "opening_perimeter", "beam",
                      "riostra", "cloaca", "electricidad") and el.length_m:
        return el.length_m
    if applies_to == "opening" and el.type == "opening":
        return (el.length_m or 0.0) * (el.height_m or 2.1)
    if applies_to in ("column", "pozo"):
        return el.area_m2 or 0.0
    if applies_to in ("sanitario", "boca_electrica"):
        return 1.0  # artefactos: 1 unidad por elemento
    return 0.0


def _qty_for_duration(el: DetectedElement, applies_to: str) -> float:
    """Cantidad en la unidad del rendimiento (daily_yield). Columnas, aberturas
    y artefactos se cuentan por unidad; el resto por su medida (m²/ml)."""
    if applies_to in ("column", "opening", "pozo", "sanitario", "boca_electrica"):
        return 1.0
    if applies_to in ("wall", "room_wall"):
        return (el.length_m or 0.0) * (el.height_m or 2.8)
    if applies_to in ("room_floor", "room_ceiling", "roof", "escalera"):
        return el.area_m2 or 0.0
    if applies_to in ("room_perimeter", "opening_perimeter", "beam",
                      "riostra", "cloaca", "electricidad"):
        return el.length_m or 0.0
    return 0.0


def _unit_for(applies_to: str) -> str:
    if applies_to in ("column", "opening", "pozo", "sanitario", "boca_electrica"):
        return "un"
    if applies_to in ("room_perimeter", "opening_perimeter", "beam",
                      "riostra", "cloaca", "electricidad"):
        return "ml"
    return "m²"


def compute_schedule(project_id: int, db: Session,
                     start_date: dt.date | None = None,
                     crews: int = 1, overlap_pct: float = 0.0) -> dict:
    """Devuelve {start_date, end_date, total_days, total_cost, tasks, stages}."""
    project = db.get(Project, project_id)
    if project is None:
        return {"tasks": [], "stages": [], "total_cost": 0.0, "total_days": 0}

    start = start_date or (project.start_date.date() if project.start_date else dt.date.today())
    crews = max(1, crews)

    plan_ids = [p.id for p in db.scalars(select(Plan).where(Plan.project_id == project_id)).all()]
    page_scales: dict[str, float] = {}
    for p in db.scalars(select(Plan).where(Plan.project_id == project_id)).all():
        page_scales.update(p.page_scales or {})

    # Eager loading: sin esto, leer el.assemblies → assembly_materials →
    # material dispara una query por elemento (N+1) → lentísimo en proyectos
    # pesados. selectinload colapsa todo en unas pocas queries.
    elements = list(db.scalars(
        select(DetectedElement)
        .where(
            DetectedElement.plan_id.in_(plan_ids),
            DetectedElement.is_candidate.is_(False),
        )
        .options(
            selectinload(DetectedElement.assemblies)
            .selectinload(Assembly.assembly_materials)
            .selectinload(AssemblyMaterial.material)
        )
    ).all()) if plan_ids else []

    openings_by_page: dict[int, list] = defaultdict(list)
    for el in elements:
        if el.type == "opening":
            openings_by_page[el.page].append(el)

    # Recetas DEFAULT por applies_to (mismo criterio que el presupuesto): un
    # elemento sin receta asignada usa la default de la org para su tipo. Sin
    # este fallback, el cronograma solo veía los elementos con asignación
    # explícita (p.ej. el matching por material BIM) y salía casi vacío,
    # descuadrado del presupuesto.
    from app.cost_intelligence.infrastructure.persistence.measurement_provider import (
        _TYPE_TO_ENTITIES,
    )
    defaults: dict[str, Assembly] = {}
    if project.organization_id:
        for asm in db.scalars(
            select(Assembly)
            .where(Assembly.organization_id == project.organization_id,
                   Assembly.is_default_alternative.is_(True))
            .options(selectinload(Assembly.assembly_materials)
                     .selectinload(AssemblyMaterial.material))
        ).all():
            defaults.setdefault(asm.applies_to, asm)

    def _assemblies_for(el: DetectedElement) -> list[Assembly]:
        if el.assemblies:
            return list(el.assemblies)
        return [defaults[e] for e in _TYPE_TO_ENTITIES.get(el.type, ())
                if e in defaults]

    # Agregar por (assembly, NIVEL): cantidad (duración) + costo. En proyectos
    # BIM cada elemento trae su storey → una tarea por receta y por piso
    # ("Mampostería — PB" ≠ "— Piso 1"). Sin nivel (PDF/DXF), level=None y el
    # comportamiento es el histórico: una tarea por receta.
    agg: dict[tuple, dict] = {}
    for el in elements:
        level = getattr(el, "level", None)
        for asm in _assemblies_for(el):
            a = agg.setdefault((asm.id, level), {
                "assembly": asm, "qty": 0.0, "cost": 0.0,
                "level": level, "level_order": getattr(el, "level_order", None),
            })
            a["qty"] += _qty_for_duration(el, asm.applies_to)
            base = _area_for_cost(el, asm.applies_to, openings_by_page, page_scales)
            if base > 0:
                for am in asm.assembly_materials:
                    mat_qty = base * am.consumption * (1.0 + am.waste_factor)
                    a["cost"] += mat_qty * (am.material.unit_price or 0.0)

    # Tareas con duración
    tasks = []
    for info in agg.values():
        asm = info["assembly"]
        yield_ = asm.daily_yield or 0.0
        duration = math.ceil(info["qty"] / (yield_ * crews)) if yield_ > 0 and info["qty"] > 0 else 1
        label = f"{asm.name} — {info['level']}" if info["level"] else asm.name
        tasks.append({
            "assembly": label, "assembly_id": asm.id,
            "level": info["level"], "level_order": info["level_order"],
            "stage": asm.stage or "Sin etapa",
            "stage_order": asm.stage_order or 0,
            "quantity": round(info["qty"], 1), "unit": _unit_for(asm.applies_to),
            "duration_days": max(1, duration), "cost": round(info["cost"], 2),
            "daily_cost": round(info["cost"] / max(1, duration), 2),
        })

    # Programar por etapa (en orden). Dentro de una etapa: las tareas SIN nivel
    # corren en paralelo desde el inicio (comportamiento histórico); las tareas
    # POR NIVEL corren en secuencia de pisos (no hacés la mampostería de P1
    # antes de terminar la de PB).
    tasks.sort(key=lambda t: (t["stage_order"], t["level_order"] if t["level_order"] is not None else -1, t["assembly"]))
    stages_map: dict[tuple, list] = defaultdict(list)
    for t in tasks:
        stages_map[(t["stage_order"], t["stage"])].append(t)

    cursor = start
    stages_out = []
    for (order, stage), stage_tasks in sorted(stages_map.items()):
        stage_start = cursor
        unleveled = [t for t in stage_tasks if t["level_order"] is None]
        leveled = [t for t in stage_tasks if t["level_order"] is not None]

        for t in unleveled:
            t["start_date"] = stage_start.isoformat()
            t["end_date"] = (stage_start + dt.timedelta(days=t["duration_days"])).isoformat()

        lvl_cursor = stage_start
        by_level: dict[int, list] = defaultdict(list)
        for t in leveled:
            by_level[t["level_order"]].append(t)
        for lo in sorted(by_level):
            grp = by_level[lo]
            for t in grp:
                t["start_date"] = lvl_cursor.isoformat()
                t["end_date"] = (lvl_cursor + dt.timedelta(days=t["duration_days"])).isoformat()
            lvl_cursor += dt.timedelta(days=max(t["duration_days"] for t in grp))

        stage_dur = max(
            max((t["duration_days"] for t in unleveled), default=0),
            (lvl_cursor - stage_start).days,
            1,
        )
        stage_end = stage_start + dt.timedelta(days=stage_dur)
        stages_out.append({
            "stage": stage, "stage_order": order,
            "start_date": stage_start.isoformat(), "end_date": stage_end.isoformat(),
            "cost": round(sum(t["cost"] for t in stage_tasks), 2),
        })
        cursor = stage_start + dt.timedelta(days=max(1, math.ceil(stage_dur * (1.0 - overlap_pct))))

    end = max((dt.date.fromisoformat(t["end_date"]) for t in tasks), default=start)
    return {
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "total_days": (end - start).days,
        "total_cost": round(sum(t["cost"] for t in tasks), 2),
        "stages": stages_out, "tasks": tasks,
    }


def compute_cashflow(project_id: int, db: Session,
                     start_date: dt.date | None = None,
                     crews: int = 1, overlap_pct: float = 0.0) -> list[dict]:
    """Curva de inversión mensual: distribuye el costo de cada tarea en sus días
    calendario y agrega por mes. Devuelve [{month, amount, accumulated}]."""
    sched = compute_schedule(project_id, db, start_date, crews, overlap_pct)
    monthly: dict[str, float] = defaultdict(float)
    for t in sched["tasks"]:
        s = dt.date.fromisoformat(t["start_date"])
        days = t["duration_days"]
        per_day = t["cost"] / max(1, days)
        for i in range(days):
            d = s + dt.timedelta(days=i)
            monthly[f"{d.year}-{d.month:02d}"] += per_day
    out = []
    acc = 0.0
    for month in sorted(monthly):
        amt = round(monthly[month], 2)
        acc += amt
        out.append({"month": month, "amount": amt, "accumulated": round(acc, 2)})
    return out
