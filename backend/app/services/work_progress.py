"""Avance FÍSICO de obra: el diferencial de ScalistAI vs Project/Primavera.

El capataz NO estima un % a ojo: registra CANTIDADES reales ("hoy 45 m² de
mampostería"). Como el plan nació del cómputo exacto del plano, el % se
DERIVA: qty_done / qty_planned. Nada de "% optimista".

Derivados (nunca persistidos, mismo criterio que el presupuesto):
- % por tarea = Σ qty_done / qty_planned (cap 100).
- % físico de obra = valor ganado: Σ(pct_i × costo_i) / Σ costo_i — ponderar
  por costo evita que "zócalos al 100%" pese igual que "estructura al 10%".
- Rendimiento real = qty acumulada / días distintos con registros → proyección
  de fin por tarea (qty restante / rendimiento real). Si aún no hay registros,
  la proyección es el plan (no se inventa rendimiento).
- Atraso proyectado de obra (v1, simplificación documentada): el mayor
  desplazamiento proyectado de una tarea vs su plan; etapas posteriores se
  asumen desplazadas en bloque (CPM real llega en la etapa 4 del módulo).
"""
from __future__ import annotations

import datetime as dt
import math

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.work_plan import ProgressEntry, WorkPlan, WorkTask


def task_progress(task: WorkTask, entries: list[ProgressEntry],
                  today: dt.date) -> dict:
    qty_done = sum(e.qty_done for e in entries)
    pct = min(1.0, qty_done / task.qty_planned) if task.qty_planned > 0 else 0.0

    days_worked = len({e.date for e in entries})
    real_yield = (qty_done / days_worked) if days_worked else None

    # Proyección de fin: desde el último registro (o hoy) al ritmo real.
    projected_end = task.planned_end
    if pct >= 1.0:
        projected_end = max((e.date for e in entries), default=task.planned_end)
    elif real_yield and task.qty_planned > 0:
        remaining_days = math.ceil((task.qty_planned - qty_done) / real_yield)
        anchor = max(max((e.date for e in entries)), today)
        projected_end = anchor + dt.timedelta(days=remaining_days)

    if pct >= 1.0:
        status = "completa"
    elif entries:
        status = "en curso"
    elif today > task.planned_end:
        status = "atrasada"  # debió terminar y no tiene ni un registro
    elif today >= task.planned_start:
        status = "debería estar en curso"
    else:
        status = "pendiente"

    return {
        "task_id": task.id, "name": task.name, "stage": task.stage,
        "stage_order": task.stage_order,
        "qty_planned": task.qty_planned, "qty_done": round(qty_done, 2),
        "unit": task.unit, "pct": round(pct * 100, 1),
        "planned_start": task.planned_start.isoformat(),
        "planned_end": task.planned_end.isoformat(),
        "projected_end": projected_end.isoformat(),
        "delay_days": max(0, (projected_end - task.planned_end).days),
        "real_yield": round(real_yield, 2) if real_yield else None,
        "cost_planned": task.cost_planned,
        "status": status,
        "n_entries": len(entries),
    }


def plan_progress(plan: WorkPlan, db: Session,
                  today: dt.date | None = None) -> dict:
    """Resumen de avance del plan: por tarea, por etapa y totales (EV)."""
    today = today or dt.date.today()
    task_ids = [t.id for t in plan.tasks]
    entries_by_task: dict[int, list[ProgressEntry]] = {tid: [] for tid in task_ids}
    if task_ids:
        for e in db.scalars(select(ProgressEntry)
                            .where(ProgressEntry.task_id.in_(task_ids))
                            .order_by(ProgressEntry.date)).all():
            entries_by_task[e.task_id].append(e)

    tasks = [task_progress(t, entries_by_task[t.id], today) for t in plan.tasks]

    bac = sum(t["cost_planned"] for t in tasks)  # presupuesto del baseline
    ev = sum(t["cost_planned"] * t["pct"] / 100.0 for t in tasks)  # valor ganado
    # Valor planificado a hoy: costo prorrateado por días transcurridos del plan.
    pv = 0.0
    for t in plan.tasks:
        if today >= t.planned_end:
            pv += t.cost_planned
        elif today > t.planned_start and t.duration_days > 0:
            frac = (today - t.planned_start).days / t.duration_days
            pv += t.cost_planned * min(1.0, frac)

    stages: dict[tuple, dict] = {}
    for t in tasks:
        s = stages.setdefault((t["stage_order"], t["stage"]), {
            "stage": t["stage"], "stage_order": t["stage_order"],
            "cost_planned": 0.0, "ev": 0.0, "delay_days": 0, "n_tareas": 0,
        })
        s["cost_planned"] += t["cost_planned"]
        s["ev"] += t["cost_planned"] * t["pct"] / 100.0
        s["delay_days"] = max(s["delay_days"], t["delay_days"])
        s["n_tareas"] += 1
    stages_out = []
    for (_, _), s in sorted(stages.items()):
        s["pct"] = round(100.0 * s["ev"] / s["cost_planned"], 1) if s["cost_planned"] else 0.0
        s["ev"] = round(s["ev"], 2)
        s["cost_planned"] = round(s["cost_planned"], 2)
        stages_out.append(s)

    delay = max((t["delay_days"] for t in tasks), default=0)
    plan_end = max((dt.date.fromisoformat(t["planned_end"]) for t in tasks),
                   default=plan.start_date)
    spi = (ev / pv) if pv > 0 else None  # >1 adelantado, <1 atrasado

    return {
        "plan_id": plan.id, "version": plan.version, "as_of": today.isoformat(),
        "tasks": tasks, "stages": stages_out,
        "totals": {
            "pct_fisico": round(100.0 * ev / bac, 1) if bac else 0.0,
            "ev": round(ev, 2), "pv": round(pv, 2), "bac": round(bac, 2),
            "spi": round(spi, 2) if spi is not None else None,
            "delay_days": delay,
            "planned_end": plan_end.isoformat(),
            "projected_end": (plan_end + dt.timedelta(days=delay)).isoformat(),
        },
    }
