"""Alertas de obra: el módulo pasa de REGISTRAR a ANTICIPAR.

Compone lo que ya existe (avance físico, costo, CPM, serie de precios + IPC)
para avisar ANTES de que el problema pase:

1. Retraso que importa: una tarea proyecta terminar tarde Y consume toda su
   holgura (slack CPM) → empuja el fin de obra. Atrasos dentro de la holgura
   no alarman (float real, no "todo es rojo").
2. Sobrecosto: CPI por debajo de umbral (gastás más de lo que avanzás).
3. Pre-acopio (diferencial): un material dominante de una etapa que AÚN NO
   empezó viene subiendo más rápido que el IPC → conviene acopiar/recotizar
   antes de llegar a esa etapa. Usa la serie real de precios + IPC INDEC.
4. Recalibración: el rendimiento real observado difiere del daily_yield de la
   receta → sugerir ajustarlo (flywheel: cada obra planifica mejor la próxima).

Todo derivado; no persiste nada.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from sqlalchemy import select, text
from sqlalchemy.orm import Session, selectinload

from app.models.material import Assembly, AssemblyMaterial
from app.models.work_plan import ProgressEntry, WorkPlan, WorkTask
from app.services.work_cpm import critical_path
from app.services.work_cost import cost_summary
from app.services.work_progress import plan_progress

_CPI_ALERT = 0.90            # gastar $1 y avanzar <$0.90
_ACOPIO_HORIZON_DAYS = 60    # solo etapas que arrancan dentro de este horizonte
_ACOPIO_MARGIN = 1.10        # el material sube >10% más que el IPC
_YIELD_MARGIN = 0.20         # rendimiento real difiere >20% del plan


def _price_growth(db: Session, material_id: int):
    """(ratio_material, ratio_ipc, desde, hasta) de la serie de precios del
    material vs IPC en el mismo tramo. None si no hay suficientes puntos."""
    pts = db.execute(text(
        "select date, price from material_price_history "
        "where material_id=:i and price>0 order by date"), {"i": material_id}).all()
    if len(pts) < 3:
        return None
    d0 = pts[0][0].date() if hasattr(pts[0][0], "date") else pts[0][0]
    d1 = pts[-1][0].date() if hasattr(pts[-1][0], "date") else pts[-1][0]
    p0, p1 = float(pts[0][1]), float(pts[-1][1])
    if p0 <= 0 or d0 == d1:
        return None
    ipc = db.execute(text(
        "select date, value from macro_series where indicator='IPC' order by date")).all()
    def ipc_at(target):
        val = None
        for d, v in ipc:
            dd = d.date() if hasattr(d, "date") else d
            if dd <= target:
                val = float(v)
        return val
    i0, i1 = ipc_at(d0), ipc_at(d1)
    ipc_ratio = (i1 / i0) if (i0 and i1 and i0 > 0) else None
    return (p1 / p0, ipc_ratio, d0, d1)


def build_alerts(plan: WorkPlan, db: Session, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()

    # Cargar tareas con receta + materiales (para pre-acopio y recalibración).
    tasks = list(db.scalars(
        select(WorkTask).where(WorkTask.work_plan_id == plan.id)
        .options(selectinload(WorkTask.assembly)
                 .selectinload(Assembly.assembly_materials)
                 .selectinload(AssemblyMaterial.material))).all())

    prog = plan_progress(plan, db, today)
    tp = {t["task_id"]: t for t in prog["tasks"]}
    cpm = critical_path([{"id": t.id, "duration_days": t.duration_days,
                          "depends_on": t.depends_on or []} for t in tasks])

    alerts: list[dict] = []

    # 1. Retraso que consume la holgura → empuja el fin de obra.
    for t in tasks:
        p = tp[t.id]
        slack = cpm["tasks"][t.id]["slack"]
        excess = p["delay_days"] - slack
        if p["delay_days"] > 0 and excess > 0 and p["status"] != "completa":
            crit = cpm["tasks"][t.id]["critical"]
            alerts.append({
                "type": "retraso", "severity": "alta" if crit else "media",
                "task_id": t.id, "stage": t.stage,
                "title": f"{t.name}: {'crítica, ' if crit else ''}atrasa la obra +{excess}d",
                "detail": (f"Al ritmo real ({p['real_yield']} {t.unit}/día) proyecta "
                           f"terminar el {p['projected_end']} (plan {p['planned_end']}); "
                           f"supera su holgura de {slack}d."),
            })

    # 2. Sobrecosto (CPI).
    cs = cost_summary(plan, db, today)
    cpi = cs["evm"]["cpi"]
    if cpi is not None and cpi < _CPI_ALERT:
        over = cs["evm"]["over_budget_at_completion"]
        alerts.append({
            "type": "sobrecosto", "severity": "alta" if cpi < 0.8 else "media",
            "task_id": None, "stage": None,
            "title": f"Eficiencia de costo baja (CPI {cpi})",
            "detail": (f"Gastaste ${cs['evm']['ac']:,.0f} para un avance valuado en "
                       f"${cs['evm']['ev']:,.0f}. Proyección al terminar: "
                       f"${cs['evm']['eac']:,.0f} (+${over:,.0f} sobre presupuesto)."),
        })

    # 3. Pre-acopio: etapas que aún no arrancaron y empiezan pronto.
    started_stages = {t.stage for t in tasks if tp[t.id]["n_entries"] > 0}
    stage_start: dict[str, dt.date] = {}
    stage_mats: dict[str, dict[int, tuple]] = defaultdict(dict)  # stage -> mat_id -> (name, relevancia)
    for t in tasks:
        stage_start.setdefault(t.stage, t.planned_start)
        stage_start[t.stage] = min(stage_start[t.stage], t.planned_start)
        if t.assembly:
            for am in t.assembly.assembly_materials:
                m = am.material
                if not m or m.category == "Recursos Humanos":
                    continue
                rel = (am.consumption or 0) * (m.unit_price or 0)
                prev = stage_mats[t.stage].get(m.id)
                stage_mats[t.stage][m.id] = (m.name, (prev[1] if prev else 0) + rel)

    for stage in sorted(stage_start, key=lambda s: stage_start[s]):
        start = stage_start[stage]
        if stage in started_stages or start <= today:
            continue
        if (start - today).days > _ACOPIO_HORIZON_DAYS:
            continue
        # material(es) más relevantes de la etapa que suben más que el IPC.
        mats = sorted(stage_mats.get(stage, {}).items(), key=lambda kv: -kv[1][1])[:3]
        for mat_id, (mat_name, _rel) in mats:
            g = _price_growth(db, mat_id)
            if not g:
                continue
            mat_ratio, ipc_ratio, d0, d1 = g
            if ipc_ratio and mat_ratio > ipc_ratio * _ACOPIO_MARGIN:
                alerts.append({
                    "type": "pre_acopio", "severity": "media",
                    "task_id": None, "stage": stage,
                    "title": f"Acopiá {mat_name} antes de «{stage}» ({start.isoformat()})",
                    "detail": (f"Viene subiendo {round((mat_ratio-1)*100)}% vs "
                               f"IPC {round((ipc_ratio-1)*100)}% ({d0}→{d1}). La etapa "
                               f"arranca en {(start-today).days} días: conviene comprar/recotizar ya."),
                })
                break  # un aviso por etapa alcanza

    # 4. Recalibración de rendimientos: real observado vs daily_yield.
    yield_suggestions: list[dict] = []
    by_asm: dict[int, dict] = {}
    entries = db.scalars(select(ProgressEntry).where(
        ProgressEntry.task_id.in_([t.id for t in tasks]))).all() if tasks else []
    entries_by_task: dict[int, list] = defaultdict(list)
    for e in entries:
        entries_by_task[e.task_id].append(e)
    for t in tasks:
        if not t.assembly_id or not t.assembly:
            continue
        te = entries_by_task.get(t.id, [])
        if not te:
            continue
        a = by_asm.setdefault(t.assembly_id, {
            "name": t.assembly.name, "unit": t.unit,
            "planned_yield": t.assembly.daily_yield or 0, "qty": 0.0, "days": set(),
        })
        a["qty"] += sum(e.qty_done for e in te)
        a["days"].update(e.date for e in te)
    for aid, a in by_asm.items():
        days = len(a["days"])
        if days < 3 or a["planned_yield"] <= 0:
            continue
        real_yield = a["qty"] / days
        diff = (real_yield - a["planned_yield"]) / a["planned_yield"]
        if abs(diff) >= _YIELD_MARGIN:
            yield_suggestions.append({
                "assembly_id": aid, "assembly": a["name"],
                "planned_yield": round(a["planned_yield"], 2),
                "real_yield": round(real_yield, 2), "unit": a["unit"],
                "diff_pct": round(diff * 100, 1), "days_observed": days,
                "suggestion": (f"Tu cuadrilla rinde {round(real_yield,1)} {a['unit']}/día "
                               f"({'+' if diff>0 else ''}{round(diff*100)}% vs plan). "
                               f"Ajustá la receta para planificar mejor la próxima obra."),
            })

    alerts.sort(key=lambda x: {"alta": 0, "media": 1, "baja": 2}.get(x["severity"], 3))
    return {
        "as_of": today.isoformat(),
        "project_duration": cpm["project_duration"],
        "critical_path": [t.id for t in tasks if cpm["tasks"][t.id]["critical"]],
        "alerts": alerts,
        "yield_suggestions": yield_suggestions,
    }
