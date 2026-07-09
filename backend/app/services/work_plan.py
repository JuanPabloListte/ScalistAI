"""Plan de obra persistido: generar borrador, congelar baseline, versionar.

El diferencial: las tareas NO nacen de una hoja en blanco (Project/Primavera)
sino del cómputo del plano — `compute_schedule` convierte elementos × recetas
en tareas con cantidad, duración (qty/daily_yield) y costo. Acá ese cálculo
se materializa como borrador editable y luego baseline inmutable.

Regla de verdad única: si hay WorkPlan activo, manda el plan persistido; el
cálculo al vuelo es solo un generador de borradores.

Versionado = historial de cambios: re-programar clona el plan activo a un
borrador nuevo (vN+1); al congelarlo, el anterior pasa a "superseded" y queda
como registro de qué se había planificado antes.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.work_plan import WorkPlan, WorkTask
from app.services.schedule import compute_schedule


def get_current_plan(project_id: int, db: Session) -> WorkPlan | None:
    """El plan que manda: draft más reciente si existe, sino el activo."""
    plans = db.scalars(
        select(WorkPlan)
        .where(WorkPlan.project_id == project_id,
               WorkPlan.status.in_(("draft", "active")))
        .options(selectinload(WorkPlan.tasks))
        .order_by(WorkPlan.version.desc())
    ).all()
    for status in ("draft", "active"):
        for p in plans:
            if p.status == status:
                return p
    return None


def list_versions(project_id: int, db: Session) -> list[WorkPlan]:
    return list(db.scalars(
        select(WorkPlan).where(WorkPlan.project_id == project_id)
        .order_by(WorkPlan.version.desc())).all())


def _next_version(project_id: int, db: Session) -> int:
    versions = [p.version for p in db.scalars(
        select(WorkPlan).where(WorkPlan.project_id == project_id)).all()]
    return (max(versions) + 1) if versions else 1


def generate_draft(project_id: int, db: Session, *,
                   start_date: dt.date | None = None,
                   crews: int = 1, overlap_pct: float = 0.0) -> WorkPlan:
    """Genera (o regenera) el borrador desde el cómputo actual del proyecto.

    Si ya había un draft, se reemplaza (el borrador no es historial; las
    versiones congeladas sí). Las dependencias finish-to-start entre etapas
    se materializan como ids explícitos: cada tarea depende de las tareas de
    la etapa anterior — el grafo queda listo para CPM (etapa 4).
    """
    # Reemplazar draft previo si existe.
    for prev in db.scalars(select(WorkPlan).where(
            WorkPlan.project_id == project_id, WorkPlan.status == "draft")).all():
        db.delete(prev)
    db.flush()

    sched = compute_schedule(project_id, db, start_date=start_date,
                             crews=crews, overlap_pct=overlap_pct)
    if not sched["tasks"]:
        raise ValueError(
            "El proyecto no tiene tareas computables: cargá un plano con "
            "elementos y recetas asignadas antes de generar el plan de obra.")

    plan = WorkPlan(
        project_id=project_id,
        version=_next_version(project_id, db),
        status="draft",
        start_date=dt.date.fromisoformat(sched["start_date"]),
        crews=crews, overlap_pct=overlap_pct,
    )
    db.add(plan)
    db.flush()

    # Crear tareas; luego cablear depends_on etapa→etapa con ids reales.
    by_stage: dict[int, list[WorkTask]] = {}
    # `assembly` en el dict de compute_schedule es el NOMBRE (str).
    for t in sched["tasks"]:
        task = WorkTask(
            work_plan_id=plan.id, assembly_id=t.get("assembly_id"),
            name=t["assembly"], stage=t["stage"], stage_order=t["stage_order"],
            qty_planned=t["quantity"], unit=t["unit"],
            duration_days=t["duration_days"],
            planned_start=dt.date.fromisoformat(t["start_date"]),
            planned_end=dt.date.fromisoformat(t["end_date"]),
            cost_planned=t["cost"], source="auto",
        )
        db.add(task)
        by_stage.setdefault(t["stage_order"], []).append(task)
    db.flush()

    orders = sorted(by_stage)
    for i, order in enumerate(orders[1:], start=1):
        prev_ids = [t.id for t in by_stage[orders[i - 1]]]
        for task in by_stage[order]:
            task.depends_on = prev_ids
    db.flush()
    return plan


def freeze(plan: WorkPlan, db: Session) -> WorkPlan:
    """Congela el borrador como baseline activo (inmutable). El activo
    anterior pasa a superseded — queda como historial de reprogramaciones."""
    if plan.status != "draft":
        raise ValueError("Solo se puede congelar un borrador.")
    for prev in db.scalars(select(WorkPlan).where(
            WorkPlan.project_id == plan.project_id,
            WorkPlan.status == "active")).all():
        prev.status = "superseded"
    plan.status = "active"
    plan.frozen_at = dt.datetime.now(dt.UTC)
    db.flush()
    return plan


def rebaseline(project_id: int, db: Session) -> WorkPlan:
    """Clona el plan activo a un borrador nuevo (vN+1) para re-programar.
    Las tareas se copian tal cual (incluidas ediciones manuales); las
    dependencias se remapean a los ids clonados."""
    active = db.scalars(select(WorkPlan).where(
        WorkPlan.project_id == project_id, WorkPlan.status == "active")
        .options(selectinload(WorkPlan.tasks))).first()
    if active is None:
        raise ValueError("No hay baseline activo para re-programar.")

    for prev in db.scalars(select(WorkPlan).where(
            WorkPlan.project_id == project_id, WorkPlan.status == "draft")).all():
        db.delete(prev)
    db.flush()

    clone = WorkPlan(
        project_id=project_id, version=_next_version(project_id, db),
        status="draft", start_date=active.start_date,
        crews=active.crews, overlap_pct=active.overlap_pct,
    )
    db.add(clone)
    db.flush()

    id_map: dict[int, int] = {}
    clones: list[tuple[WorkTask, list | None]] = []
    for t in active.tasks:
        c = WorkTask(
            work_plan_id=clone.id, assembly_id=t.assembly_id, name=t.name,
            stage=t.stage, stage_order=t.stage_order,
            qty_planned=t.qty_planned, unit=t.unit,
            duration_days=t.duration_days,
            planned_start=t.planned_start, planned_end=t.planned_end,
            cost_planned=t.cost_planned, source=t.source,
        )
        db.add(c)
        clones.append((c, t.depends_on))
        db.flush()
        id_map[t.id] = c.id
    for c, deps in clones:
        if deps:
            c.depends_on = [id_map.get(d, d) for d in deps]
    db.flush()
    return clone


def serialize(plan: WorkPlan) -> dict:
    """Mismo shape que compute_schedule (el Gantt del frontend lo reusa) +
    metadata del plan (id, versión, estado)."""
    tasks = [{
        "id": t.id, "assembly": t.name, "stage": t.stage,
        "stage_order": t.stage_order, "quantity": t.qty_planned,
        "unit": t.unit, "duration_days": t.duration_days,
        "start_date": t.planned_start.isoformat(),
        "end_date": t.planned_end.isoformat(),
        "cost": t.cost_planned,
        "daily_cost": round(t.cost_planned / max(1, t.duration_days), 2),
        "depends_on": t.depends_on or [], "source": t.source,
    } for t in plan.tasks]

    stages_map: dict[tuple, list[dict]] = {}
    for t in tasks:
        stages_map.setdefault((t["stage_order"], t["stage"]), []).append(t)
    stages = [{
        "stage": stage, "stage_order": order,
        "start_date": min(x["start_date"] for x in ts),
        "end_date": max(x["end_date"] for x in ts),
        "cost": round(sum(x["cost"] for x in ts), 2),
    } for (order, stage), ts in sorted(stages_map.items())]

    end = max((t["end_date"] for t in tasks), default=plan.start_date.isoformat())
    return {
        "plan_id": plan.id, "version": plan.version, "status": plan.status,
        "frozen_at": plan.frozen_at.isoformat() if plan.frozen_at else None,
        "crews": plan.crews, "overlap_pct": plan.overlap_pct,
        "start_date": plan.start_date.isoformat(), "end_date": end,
        "total_days": (dt.date.fromisoformat(end) - plan.start_date).days,
        "total_cost": round(sum(t["cost"] for t in tasks), 2),
        "stages": stages, "tasks": tasks,
    }
