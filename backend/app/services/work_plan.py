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

from app.models.work_plan import WorkPlan, WorkTask, WorkTaskEvent
from app.services.schedule import compute_schedule


def record_event(db: Session, task: WorkTask, field: str,
                 old, new, user_id: int | None = None,
                 note: str | None = None) -> WorkTaskEvent:
    """Anota un cambio en el historial de la tarea (append-only). `old`/`new`
    se guardan como texto; None se preserva para distinguir "sin valor"."""
    ev = WorkTaskEvent(
        work_task_id=task.id, field=field,
        old_value=None if old is None else str(old),
        new_value=None if new is None else str(new),
        note=note, created_by=user_id,
    )
    db.add(ev)
    return ev


def _resolve_assignee(assignee_id: int | None, org_id: int | None,
                      db: Session) -> int | None:
    """Valida que el responsable pertenezca a la organización. None o ≤0 → sin
    responsable (desasignar). ValueError si el usuario es de otra org."""
    from app.models.user import User
    if assignee_id is None or assignee_id <= 0:
        return None
    member = db.get(User, assignee_id)
    if member is None or member.organization_id != org_id:
        raise ValueError("El responsable no pertenece a tu organización.")
    return assignee_id


_BASELINE_KEYS = ("name", "planned_start", "duration_days", "depends_on")


def edit_task(task: WorkTask, plan: WorkPlan, org_id: int | None,
              patch: dict, user_id: int | None, db: Session) -> None:
    """Aplica cambios a una tarea y los registra en el historial.

    Dos planos: BASELINE (nombre/fecha/duración/deps) solo sobre borrador
    (PermissionError si el plan está congelado); FLUJO (estado/prioridad/
    responsable/comentario) también sobre el baseline activo. `patch` trae solo
    las claves enviadas (exclude_unset) para no pisar campos con defaults."""
    if any(k in patch for k in _BASELINE_KEYS) and plan.status != "draft":
        raise PermissionError(
            "El cronograma congelado no se edita: usá 'Reprogramar' para crear "
            "una versión nueva. (Estado, prioridad y responsable sí se pueden "
            "cambiar sobre el plan activo.)")

    if patch.get("name") is not None and patch["name"] != task.name:
        record_event(db, task, "name", task.name, patch["name"], user_id)
        task.name = patch["name"]
    if patch.get("planned_start") is not None:
        new_start = dt.date.fromisoformat(patch["planned_start"])
        if new_start != task.planned_start:
            record_event(db, task, "planned_start", task.planned_start.isoformat(),
                         new_start.isoformat(), user_id)
            task.planned_start = new_start
    if patch.get("duration_days") is not None and patch["duration_days"] != task.duration_days:
        record_event(db, task, "duration_days", task.duration_days,
                     patch["duration_days"], user_id)
        task.duration_days = patch["duration_days"]
    if patch.get("depends_on") is not None and patch["depends_on"] != (task.depends_on or []):
        record_event(db, task, "depends_on", task.depends_on or [],
                     patch["depends_on"], user_id)
        task.depends_on = patch["depends_on"] or None
    task.planned_end = task.planned_start + dt.timedelta(days=task.duration_days)

    note = patch.get("note")
    if patch.get("status") is not None and patch["status"] != task.status:
        record_event(db, task, "status", task.status, patch["status"], user_id, note=note)
        task.status = patch["status"]
    if patch.get("priority") is not None and patch["priority"] != task.priority:
        record_event(db, task, "priority", task.priority, patch["priority"], user_id)
        task.priority = patch["priority"]
    if "assignee_id" in patch:
        new_assignee = _resolve_assignee(patch["assignee_id"], org_id, db)
        if new_assignee != task.assignee_id:
            record_event(db, task, "assignee", task.assignee_id, new_assignee, user_id)
            task.assignee_id = new_assignee
    # Comentario suelto (sin cambio de estado) → evento de comentario.
    if note is not None and patch.get("status") is None:
        record_event(db, task, "comment", None, None, user_id, note=note)
    db.flush()


def create_manual_task(plan: WorkPlan, org_id: int | None, data: dict,
                       user_id: int | None, db: Session) -> WorkTask:
    """Crea una tarea MANUAL (change order). Aditiva: se permite sobre borrador
    y sobre el baseline activo sin alterar las tareas del cronograma congelado.
    Sin `planned_start`, arranca al terminar su(s) predecesora(s) (finish-to-
    start) o al inicio del plan. ValueError si una dependencia no es del plan."""
    assignee_id = _resolve_assignee(data.get("assignee_id"), org_id, db)
    deps = data.get("depends_on") or []
    dep_tasks = [db.get(WorkTask, d) for d in deps]
    if any(t is None or t.work_plan_id != plan.id for t in dep_tasks):
        raise ValueError("Alguna dependencia no es una tarea de este plan.")

    if data.get("planned_start"):
        start = dt.date.fromisoformat(data["planned_start"])
    elif dep_tasks:
        start = max(t.planned_end for t in dep_tasks) + dt.timedelta(days=1)
    else:
        start = plan.start_date

    duration = data.get("duration_days", 1)
    task = WorkTask(
        work_plan_id=plan.id, name=data["name"],
        stage=data.get("stage", "Sin etapa"), stage_order=data.get("stage_order", 0),
        qty_planned=data.get("qty_planned", 0.0), unit=data.get("unit", "un"),
        duration_days=duration, planned_start=start,
        planned_end=start + dt.timedelta(days=duration),
        cost_planned=data.get("cost_planned", 0.0), depends_on=deps or None,
        source="manual", status=data.get("status", "pending"),
        priority=data.get("priority", "medium"), assignee_id=assignee_id,
    )
    db.add(task)
    db.flush()
    record_event(db, task, "created", None, data["name"], user_id, note=data.get("note"))
    db.flush()
    return task


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
            # El flujo de ejecución sobrevive a la reprogramación.
            status=t.status, priority=t.priority, assignee_id=t.assignee_id,
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
        # Flujo tipo Jira (metadata de ejecución).
        "status": t.status, "priority": t.priority,
        "assignee_id": t.assignee_id,
        "assignee_email": t.assignee.email if t.assignee else None,
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
