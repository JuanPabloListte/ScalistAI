"""Avance FINANCIERO de obra: valor ganado (EVM) + desvío ajustado por inflación.

El killer feature argentino: un seguimiento de costos NOMINAL miente. Si
gastaste 20% más, ¿fue por ineficiencia o porque el cemento subió 20%? Con la
serie IPC (INDEC) separamos las dos cosas:

    EV        = valor ganado a precios del BASELINE (lo que el avance DEBÍA costar)
    EV_hoy    = EV × (IPC_hoy / IPC_baseline)   → mismo trabajo a precios de hoy
    inflación = EV_hoy − EV                      (te costó más porque subió todo)
    desvío_real = AC − EV_hoy                    (te costó más por vos: eficiencia)

EVM clásico encima:
    BAC = presupuesto total del baseline · PV = valor planificado a la fecha
    AC  = costo real incurrido (facturas cargadas)
    CV  = EV − AC (variación de costo) · CPI = EV/AC · SPI = EV/PV
    EAC = BAC / CPI (costo estimado al terminar, si el ritmo de gasto sigue)

Nada se persiste: todo se deriva de ActualCost + baseline + IPC, igual que el
resto del motor de costos.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.work_plan import ActualCost, WorkPlan
from app.services.work_progress import plan_progress


def _ipc_ratio(db: Session, baseline_date: dt.date, today: dt.date):
    """(ratio, ipc_base, ipc_now, fecha_now) del IPC INDEC entre baseline y hoy.
    None si no hay serie. ipc_base = último punto <= baseline_date."""
    rows = db.execute(text(
        "select date, value from macro_series where indicator='IPC' order by date")).all()
    if len(rows) < 2:
        return None
    ipc_base = None
    for d, v in rows:
        dd = d.date() if hasattr(d, "date") else d
        if dd <= baseline_date:
            ipc_base = float(v)
    now_date, ipc_now = rows[-1]
    now_date = now_date.date() if hasattr(now_date, "date") else now_date
    if not ipc_base or ipc_base <= 0:
        return None
    return (float(ipc_now) / ipc_base, ipc_base, float(ipc_now), now_date)


def _month_iter(start: dt.date, end: dt.date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield f"{y}-{m:02d}"
        m += 1
        if m > 12:
            m = 1; y += 1


def cost_summary(plan: WorkPlan, db: Session, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    prog = plan_progress(plan, db, today)
    ev = prog["totals"]["ev"]
    pv = prog["totals"]["pv"]
    bac = prog["totals"]["bac"]
    task_by_id = {t["task_id"]: t for t in prog["tasks"]}

    # --- Costos reales cargados ---
    acs = list(db.scalars(select(ActualCost).where(
        ActualCost.project_id == plan.project_id).order_by(ActualCost.date)).all())
    ac = sum(a.amount for a in acs)

    by_kind: dict[str, float] = defaultdict(float)
    by_stage_real: dict[str, float] = defaultdict(float)
    for a in acs:
        by_kind[a.kind] += a.amount
        stage = a.stage
        if stage is None and a.work_task_id and a.work_task_id in task_by_id:
            stage = task_by_id[a.work_task_id]["stage"]
        by_stage_real[stage or "Sin asignar"] += a.amount

    # --- EVM ---
    cv = ev - ac                                  # <0 = gastaste de más
    cpi = (ev / ac) if ac > 0 else None           # <1 = ineficiente
    spi = prog["totals"]["spi"]
    eac = (bac / cpi) if cpi else bac             # costo estimado al terminar

    # --- Ajuste por inflación (IPC INDEC) ---
    baseline_date = (plan.frozen_at.date() if plan.frozen_at else plan.start_date)
    ipc = _ipc_ratio(db, baseline_date, today)
    inflation = None
    if ipc:
        ratio, ipc_base, ipc_now, ipc_date = ipc
        ev_now = ev * ratio
        inflation = {
            "ipc_base": round(ipc_base, 1), "ipc_now": round(ipc_now, 1),
            "ipc_base_date": baseline_date.isoformat(), "ipc_now_date": ipc_date.isoformat(),
            "accum_pct": round((ratio - 1) * 100, 1),
            "ev_now": round(ev_now, 2),
            "inflation_gap": round(ev_now - ev, 2),      # atribuible a inflación
            "real_variance": round(ac - ev_now, 2),      # >0 = desvío real (tuyo)
        }

    # --- Curva S: plan (baseline) vs real (facturas) vs proyección ---
    planned_month: dict[str, float] = defaultdict(float)
    for t in plan.tasks:
        per_day = t.cost_planned / max(1, t.duration_days)
        for i in range(t.duration_days):
            d = t.planned_start + dt.timedelta(days=i)
            planned_month[f"{d.year}-{d.month:02d}"] += per_day
    real_month: dict[str, float] = defaultdict(float)
    for a in acs:
        real_month[f"{a.date.year}-{a.date.month:02d}"] += a.amount

    plan_end = max((t.planned_end for t in plan.tasks), default=plan.start_date)
    months = list(_month_iter(plan.start_date, max(plan_end, today)))
    cur_month = f"{today.year}-{today.month:02d}"
    # Proyección: real hasta el mes actual, luego reparte el remanente (EAC−AC)
    # siguiendo la forma de lo que resta del plan.
    remaining_plan = sum(v for m, v in planned_month.items() if m > cur_month) or 1.0
    curve = []
    acc_plan = acc_real = acc_proj = 0.0
    real_seen = False
    for m in months:
        acc_plan += planned_month.get(m, 0.0)
        row = {"month": m, "plan": round(acc_plan, 2)}
        if m <= cur_month:
            acc_real += real_month.get(m, 0.0)
            acc_proj = acc_real
            row["real"] = round(acc_real, 2)
            real_seen = True
        else:
            share = planned_month.get(m, 0.0) / remaining_plan
            acc_proj += max(0.0, eac - ac) * share
        if real_seen:
            row["projected"] = round(acc_proj, 2)
        curve.append(row)

    # --- Plan vs real por etapa (para tabla) ---
    stages = []
    planned_by_stage: dict[str, float] = defaultdict(float)
    for t in prog["tasks"]:
        planned_by_stage[t["stage"]] += t["cost_planned"]
    for stage in sorted(set(planned_by_stage) | set(by_stage_real)):
        stages.append({
            "stage": stage,
            "planned": round(planned_by_stage.get(stage, 0.0), 2),
            "real": round(by_stage_real.get(stage, 0.0), 2),
        })

    return {
        "plan_id": plan.id, "version": plan.version, "as_of": today.isoformat(),
        "evm": {
            "bac": round(bac, 2), "pv": round(pv, 2), "ev": round(ev, 2),
            "ac": round(ac, 2), "cv": round(cv, 2),
            "cpi": round(cpi, 2) if cpi else None,
            "spi": spi, "eac": round(eac, 2),
            "over_budget_at_completion": round(eac - bac, 2),
        },
        "inflation": inflation,
        "by_kind": {k: round(v, 2) for k, v in by_kind.items()},
        "stages": stages,
        "curve": curve,
        "n_costs": len(acs),
    }
