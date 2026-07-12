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

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, object_session, selectinload

from app.models.material import Assembly, AssemblyMaterial
from app.models.work_plan import WorkPlan, WorkPlanMaterialPrice, WorkTask, WorkTaskEvent
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


def _resolve_assignees(assignee_ids, org_id: int | None, db: Session) -> list:
    """Resuelve y valida los responsables (varios por tarea). Devuelve la lista
    de User únicos, ordenados por email. ValueError si alguno es de otra org."""
    from app.models.user import User
    out: dict[int, "User"] = {}
    for uid in assignee_ids or []:
        if uid is None or uid <= 0 or uid in out:
            continue
        member = db.get(User, uid)
        if member is None or member.organization_id != org_id:
            raise ValueError("Algún responsable no pertenece a tu organización.")
        out[uid] = member
    return sorted(out.values(), key=lambda u: u.email)


def _emails(users) -> str:
    return ", ".join(u.email for u in users) or "—"


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
    if "description" in patch and (patch.get("description") or None) != task.description:
        record_event(db, task, "description", None, None, user_id)
        task.description = patch.get("description") or None
    if "assignee_ids" in patch:
        new_assignees = _resolve_assignees(patch["assignee_ids"], org_id, db)
        if {u.id for u in new_assignees} != {u.id for u in task.assignees}:
            record_event(db, task, "assignee", _emails(task.assignees),
                         _emails(new_assignees), user_id)
            task.assignees = new_assignees
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
    assignees = _resolve_assignees(data.get("assignee_ids"), org_id, db)
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
        priority=data.get("priority", "medium"),
        description=data.get("description") or None, assignees=assignees,
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

    # Crear tareas; luego cablear depends_on con ids reales. Dos planos:
    # etapa→etapa (como siempre) y, dentro de una etapa, nivel k−1 → nivel k
    # (proyectos BIM: la mampostería de P1 depende de la de PB).
    by_stage: dict[int, list[tuple[WorkTask, int | None]]] = {}
    # `assembly` en el dict de compute_schedule es el NOMBRE (str, ya con nivel).
    for t in sched["tasks"]:
        task = WorkTask(
            work_plan_id=plan.id, assembly_id=t.get("assembly_id"),
            name=t["assembly"], stage=t["stage"], stage_order=t["stage_order"],
            qty_planned=t["quantity"], unit=t["unit"],
            level=t.get("level"), level_order=t.get("level_order"),
            duration_days=t["duration_days"],
            planned_start=dt.date.fromisoformat(t["start_date"]),
            planned_end=dt.date.fromisoformat(t["end_date"]),
            cost_planned=t["cost"], source="auto",
        )
        db.add(task)
        by_stage.setdefault(t["stage_order"], []).append((task, t.get("level_order")))
    db.flush()

    orders = sorted(by_stage)
    for i, order in enumerate(orders):
        prev_stage_ids = ([t.id for t, _ in by_stage[orders[i - 1]]] if i > 0 else [])
        here = by_stage[order]
        levels = sorted({lo for _, lo in here if lo is not None})
        first = levels[0] if levels else None
        ids_by_level = {lo: [t.id for t, l in here if l == lo] for lo in levels}
        for task, lo in here:
            if lo is None or lo == first:
                # Sin nivel (o el nivel más bajo): depende de la etapa anterior.
                if prev_stage_ids:
                    task.depends_on = prev_stage_ids
            else:
                # Nivel k: depende de las tareas del nivel anterior de SU etapa.
                prev_lo = levels[levels.index(lo) - 1]
                task.depends_on = ids_by_level[prev_lo]
    db.flush()
    return plan


def _refresh_auto_costs_at_freeze(plan: WorkPlan, db: Session) -> None:
    """Recalcula cost_planned de tareas auto con precios vivos al momento del
    freeze (misma fórmula que compute_schedule). Así el BAC no queda con
    precios de cuando se generó el borrador días antes."""
    try:
        sched = compute_schedule(
            plan.project_id, db,
            start_date=plan.start_date,
            crews=plan.crews,
            overlap_pct=plan.overlap_pct,
        )
    except Exception:  # noqa: BLE001
        return  # sin cómputo usable: se congelan los costos del borrador
    by_key = {
        (t.get("assembly_id"), t["assembly"]): t["cost"]
        for t in sched["tasks"]
    }
    for task in plan.tasks:
        if task.source != "auto" or not task.assembly_id:
            continue
        cost = by_key.get((task.assembly_id, task.name))
        if cost is not None:
            task.cost_planned = float(cost)


def snapshot_material_prices(plan: WorkPlan, db: Session) -> list[WorkPlanMaterialPrice]:
    """Captura unit_price de cada material de las recetas del plan.

    Idempotente: reemplaza filas previas del mismo work_plan_id.
    """
    db.execute(
        delete(WorkPlanMaterialPrice).where(
            WorkPlanMaterialPrice.work_plan_id == plan.id
        )
    )

    # Cargar tareas + recetas + insumos
    tasks = list(db.scalars(
        select(WorkTask)
        .where(WorkTask.work_plan_id == plan.id)
        .options(
            selectinload(WorkTask.assembly)
            .selectinload(Assembly.assembly_materials)
            .selectinload(AssemblyMaterial.material)
        )
    ).all())

    seen: dict[int, WorkPlanMaterialPrice] = {}
    now = dt.datetime.now(dt.UTC)
    for task in tasks:
        asm = task.assembly
        if asm is None:
            continue
        for am in asm.assembly_materials:
            m = am.material
            if m is None or m.id in seen:
                continue
            row = WorkPlanMaterialPrice(
                work_plan_id=plan.id,
                material_id=m.id,
                unit_price=float(m.unit_price or 0.0),
                unit=m.unit,
                material_name=m.name,
                captured_at=now,
            )
            db.add(row)
            seen[m.id] = row
    db.flush()
    return list(seen.values())


def price_map_for_plan(plan_id: int, db: Session) -> dict[int, float]:
    """material_id → unit_price del snapshot del baseline (vacío si no hay)."""
    rows = db.scalars(
        select(WorkPlanMaterialPrice).where(
            WorkPlanMaterialPrice.work_plan_id == plan_id
        )
    ).all()
    return {r.material_id: r.unit_price for r in rows}


def freeze(plan: WorkPlan, db: Session) -> WorkPlan:
    """Congela el borrador como baseline activo (inmutable). El activo
    anterior pasa a superseded — queda como historial de reprogramaciones.

    Al congelar: (1) refresca costos auto con precios vivos, (2) snapshot de
    precios de materiales, (3) marca active + frozen_at.
    """
    if plan.status != "draft":
        raise ValueError("Solo se puede congelar un borrador.")

    # Asegurar tasks cargadas para refresh/snapshot
    plan = db.scalars(
        select(WorkPlan)
        .where(WorkPlan.id == plan.id)
        .options(selectinload(WorkPlan.tasks))
    ).one()

    _refresh_auto_costs_at_freeze(plan, db)
    snapshot_material_prices(plan, db)

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
            level=t.level, level_order=t.level_order,
            duration_days=t.duration_days,
            planned_start=t.planned_start, planned_end=t.planned_end,
            cost_planned=t.cost_planned, source=t.source,
            # El flujo de ejecución sobrevive a la reprogramación.
            status=t.status, priority=t.priority, description=t.description,
            assignees=list(t.assignees),
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
        "assembly_id": t.assembly_id,
        "level": t.level,
        "level_order": t.level_order,
        # Flujo tipo Jira (metadata de ejecución).
        "status": t.status, "priority": t.priority,
        "description": t.description,
        "assignees": [{"user_id": u.id, "email": u.email} for u in t.assignees],
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
    sess = object_session(plan)
    if sess is not None:
        snap_count = sess.scalar(
            select(func.count()).select_from(WorkPlanMaterialPrice).where(
                WorkPlanMaterialPrice.work_plan_id == plan.id
            )
        ) or 0
    else:
        snap_count = len(plan.material_prices or [])
    return {
        "plan_id": plan.id, "version": plan.version, "status": plan.status,
        "frozen_at": plan.frozen_at.isoformat() if plan.frozen_at else None,
        "crews": plan.crews, "overlap_pct": plan.overlap_pct,
        "start_date": plan.start_date.isoformat(), "end_date": end,
        "total_days": (dt.date.fromisoformat(end) - plan.start_date).days,
        "total_cost": round(sum(t["cost"] for t in tasks), 2),
        "price_snapshot_count": int(snap_count),
        "stages": stages, "tasks": tasks,
    }


def _task_diff_key(assembly_id: int | None, name: str) -> tuple:
    return (assembly_id, name)


def compute_diff(project_id: int, db: Session) -> dict:
    """Compara el plan vigente (draft > active) contra compute_schedule actual.

    Read-only: no escribe. Key = (assembly_id, name). Tareas manuales del plan
    sin match en cómputo salen como `removed` del cómputo (siguen en el plan).
    """
    plan = get_current_plan(project_id, db)
    try:
        sched = compute_schedule(
            project_id, db,
            start_date=plan.start_date if plan else None,
            crews=plan.crews if plan else 1,
            overlap_pct=plan.overlap_pct if plan else 0.0,
        )
    except Exception as exc:  # noqa: BLE001
        raise ValueError(str(exc)) from exc

    compute_tasks = {
        _task_diff_key(t.get("assembly_id"), t["assembly"]): t
        for t in sched["tasks"]
    }
    plan_tasks: dict[tuple, dict] = {}
    if plan is not None:
        for t in plan.tasks:
            plan_tasks[_task_diff_key(t.assembly_id, t.name)] = {
                "name": t.name,
                "assembly_id": t.assembly_id,
                "level": t.level,
                "qty": t.qty_planned,
                "unit": t.unit,
                "cost": t.cost_planned,
                "duration_days": t.duration_days,
                "source": t.source,
            }

    keys = set(plan_tasks) | set(compute_tasks)
    rows: list[dict] = []
    for key in sorted(keys, key=lambda k: (k[1] or "", k[0] or 0)):
        p = plan_tasks.get(key)
        c = compute_tasks.get(key)
        if p and c:
            qty_p, qty_c = float(p["qty"]), float(c["quantity"])
            cost_p, cost_c = float(p["cost"]), float(c["cost"])
            same_qty = abs(qty_p - qty_c) < 0.05
            same_cost = abs(cost_p - cost_c) < 1.0
            status = "same" if same_qty and same_cost else "changed"
            rows.append({
                "name": p["name"],
                "assembly_id": p["assembly_id"] or c.get("assembly_id"),
                "level": p.get("level") or c.get("level"),
                "unit": p["unit"] or c.get("unit"),
                "qty_plan": qty_p,
                "qty_compute": qty_c,
                "cost_plan": cost_p,
                "cost_compute": cost_c,
                "duration_plan": p["duration_days"],
                "duration_compute": c["duration_days"],
                "source": p.get("source"),
                "status": status,
            })
        elif p and not c:
            rows.append({
                "name": p["name"],
                "assembly_id": p["assembly_id"],
                "level": p.get("level"),
                "unit": p["unit"],
                "qty_plan": float(p["qty"]),
                "qty_compute": None,
                "cost_plan": float(p["cost"]),
                "cost_compute": None,
                "duration_plan": p["duration_days"],
                "duration_compute": None,
                "source": p.get("source"),
                "status": "removed",  # en plan, no en cómputo actual
            })
        else:
            assert c is not None
            rows.append({
                "name": c["assembly"],
                "assembly_id": c.get("assembly_id"),
                "level": c.get("level"),
                "unit": c.get("unit"),
                "qty_plan": None,
                "qty_compute": float(c["quantity"]),
                "cost_plan": None,
                "cost_compute": float(c["cost"]),
                "duration_plan": None,
                "duration_compute": c["duration_days"],
                "source": "auto",
                "status": "added",  # en cómputo, no en plan
            })

    plan_total = float(sum(t.cost_planned for t in plan.tasks)) if plan else 0.0
    compute_total = float(sched.get("total_cost") or sum(t["cost"] for t in sched["tasks"]))
    n_changed = sum(1 for r in rows if r["status"] != "same")
    return {
        "plan_id": plan.id if plan else None,
        "plan_status": plan.status if plan else None,
        "plan_version": plan.version if plan else None,
        "plan_total": round(plan_total, 2),
        "compute_total": round(compute_total, 2),
        "delta_cost": round(compute_total - plan_total, 2),
        "n_changed": n_changed,
        "tasks": rows,
    }
