"""API del módulo Obra (Etapa 1): plan de obra persistido y versionado.

Flujo: POST draft (genera desde el cómputo) → PATCH tareas (editar borrador)
→ POST freeze (baseline inmutable) → POST rebaseline (vN+1 para re-programar).
GET devuelve el plan que manda (draft > active) con el mismo shape del
cronograma calculado, así el Gantt del frontend reusa el render.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import Project, User
from app.models.work_plan import WorkPlan, WorkTask
from app.services import work_plan as wp

router = APIRouter(tags=["work-plans"])


def _project_guard(project_id: int, db: Session, user: User) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    return project


def _plan_guard(plan_id: int, db: Session, user: User) -> WorkPlan:
    plan = db.get(WorkPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan de obra no encontrado")
    _project_guard(plan.project_id, db, user)
    return plan


class DraftRequest(BaseModel):
    start_date: Optional[str] = None   # ISO; default: hoy / start del proyecto
    crews: int = Field(1, ge=1, le=20)
    overlap_pct: float = Field(0.0, ge=0.0, le=0.9)


class TaskPatch(BaseModel):
    name: Optional[str] = None
    duration_days: Optional[int] = Field(None, ge=1, le=730)
    planned_start: Optional[str] = None  # ISO


@router.get("/projects/{project_id}/work-plan")
def get_work_plan(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Plan vigente (draft > active) + historial de versiones. `plan=None` si
    el proyecto todavía no generó ninguno (el Gantt cae al cálculo al vuelo)."""
    _project_guard(project_id, db, user)
    plan = wp.get_current_plan(project_id, db)
    versions = [{
        "plan_id": p.id, "version": p.version, "status": p.status,
        "frozen_at": p.frozen_at.isoformat() if p.frozen_at else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    } for p in wp.list_versions(project_id, db)]
    return {"plan": wp.serialize(plan) if plan else None, "versions": versions}


@router.post("/projects/{project_id}/work-plan/draft")
def create_draft(
    project_id: int,
    payload: DraftRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Genera (o regenera) el BORRADOR del plan desde el cómputo del plano."""
    _project_guard(project_id, db, user)
    sd = dt.date.fromisoformat(payload.start_date) if payload.start_date else None
    try:
        plan = wp.generate_draft(project_id, db, start_date=sd,
                                 crews=payload.crews, overlap_pct=payload.overlap_pct)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    db.refresh(plan)
    return wp.serialize(plan)


@router.post("/work-plans/{plan_id}/freeze")
def freeze_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Congela el borrador como baseline activo (inmutable)."""
    plan = _plan_guard(plan_id, db, user)
    try:
        wp.freeze(plan, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    db.refresh(plan)
    return wp.serialize(plan)


@router.post("/projects/{project_id}/work-plan/rebaseline")
def rebaseline_plan(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Clona el baseline activo a un borrador vN+1 para re-programar."""
    _project_guard(project_id, db, user)
    try:
        plan = wp.rebaseline(project_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    db.refresh(plan)
    return wp.serialize(plan)


class ProgressCreate(BaseModel):
    date: Optional[str] = None      # ISO; default hoy
    qty_done: float = Field(..., gt=0)
    note: Optional[str] = None


@router.get("/projects/{project_id}/work-progress")
def get_work_progress(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Avance físico del plan ACTIVO: % por tarea/etapa/obra (valor ganado),
    rendimiento real observado y fin proyectado. 404 si no hay baseline."""
    from app.services.work_progress import plan_progress

    _project_guard(project_id, db, user)
    active = next((p for p in wp.list_versions(project_id, db)
                   if p.status == "active"), None)
    if active is None:
        raise HTTPException(status_code=404,
                            detail="No hay baseline activo: congelá el plan de obra primero.")
    db.refresh(active)  # carga tasks
    return plan_progress(active, db)


@router.post("/work-tasks/{task_id}/progress")
def add_progress(
    task_id: int,
    payload: ProgressCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Registra avance FÍSICO en unidades de obra ("hoy 45 m²"). Solo sobre
    el baseline activo. Append-only: corregir = borrar el registro erróneo."""
    from app.models.work_plan import ProgressEntry

    task = db.get(WorkTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    plan = _plan_guard(task.work_plan_id, db, user)
    if plan.status != "active":
        raise HTTPException(status_code=409,
                            detail="El avance se registra sobre el baseline activo (congelá el plan primero).")
    entry = ProgressEntry(
        task_id=task_id,
        date=dt.date.fromisoformat(payload.date) if payload.date else dt.date.today(),
        qty_done=payload.qty_done, note=payload.note, created_by=user.id,
    )
    db.add(entry)
    db.commit()
    from app.services.work_progress import plan_progress
    db.refresh(plan)
    return plan_progress(plan, db)


@router.get("/work-tasks/{task_id}/progress")
def list_progress(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    from app.models.work_plan import ProgressEntry
    from sqlalchemy import select as _select

    task = db.get(WorkTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    _plan_guard(task.work_plan_id, db, user)
    return [{
        "id": e.id, "date": e.date.isoformat(), "qty_done": e.qty_done,
        "note": e.note, "created_at": e.created_at.isoformat() if e.created_at else None,
    } for e in db.scalars(_select(ProgressEntry)
                          .where(ProgressEntry.task_id == task_id)
                          .order_by(ProgressEntry.date.desc(), ProgressEntry.id.desc())).all()]


@router.delete("/work-progress/{entry_id}", status_code=204)
def delete_progress(
    entry_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """Borra un registro erróneo (la corrección honesta en un log append-only)."""
    from app.models.work_plan import ProgressEntry

    entry = db.get(ProgressEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Registro no encontrado")
    task = db.get(WorkTask, entry.task_id)
    _plan_guard(task.work_plan_id, db, user)
    db.delete(entry)
    db.commit()


class ActualCostCreate(BaseModel):
    date: Optional[str] = None
    amount: float = Field(..., gt=0)
    kind: str = Field("material", pattern="^(material|mano_obra|otro)$")
    work_task_id: Optional[int] = None
    stage: Optional[str] = None
    note: Optional[str] = None


@router.get("/projects/{project_id}/work-cost")
def get_work_cost(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Avance FINANCIERO del baseline activo: EVM (PV/EV/AC/CPI/SPI/EAC),
    desvío ajustado por IPC (inflación vs desvío real) y curva S plan/real/
    proyección."""
    from app.services.work_cost import cost_summary

    _project_guard(project_id, db, user)
    active = next((p for p in wp.list_versions(project_id, db)
                   if p.status == "active"), None)
    if active is None:
        raise HTTPException(status_code=404,
                            detail="No hay baseline activo: congelá el plan de obra primero.")
    db.refresh(active)
    return cost_summary(active, db)


@router.get("/projects/{project_id}/actual-costs")
def list_actual_costs(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    from app.models.work_plan import ActualCost
    from sqlalchemy import select as _select

    _project_guard(project_id, db, user)
    return [{
        "id": a.id, "date": a.date.isoformat(), "amount": a.amount,
        "kind": a.kind, "work_task_id": a.work_task_id, "stage": a.stage,
        "note": a.note,
    } for a in db.scalars(_select(ActualCost)
                          .where(ActualCost.project_id == project_id)
                          .order_by(ActualCost.date.desc(), ActualCost.id.desc())).all()]


@router.post("/projects/{project_id}/actual-costs")
def add_actual_cost(
    project_id: int,
    payload: ActualCostCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Registra un costo REAL (factura, jornal, otro). Devuelve el resumen
    financiero actualizado."""
    from app.models.work_plan import ActualCost, WorkTask
    from app.services.work_cost import cost_summary

    _project_guard(project_id, db, user)
    stage = payload.stage
    if payload.work_task_id is not None:
        task = db.get(WorkTask, payload.work_task_id)
        if task is None or db.get(WorkPlan, task.work_plan_id).project_id != project_id:
            raise HTTPException(status_code=400, detail="Tarea inválida para este proyecto")
        stage = stage or task.stage
    cost = ActualCost(
        project_id=project_id,
        date=dt.date.fromisoformat(payload.date) if payload.date else dt.date.today(),
        amount=payload.amount, kind=payload.kind,
        work_task_id=payload.work_task_id, stage=stage,
        note=payload.note, created_by=user.id,
    )
    db.add(cost)
    db.commit()
    active = next((p for p in wp.list_versions(project_id, db)
                   if p.status == "active"), None)
    if active is None:
        return {}
    db.refresh(active)
    return cost_summary(active, db)


@router.delete("/actual-costs/{cost_id}", status_code=204)
def delete_actual_cost(
    cost_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    from app.models.work_plan import ActualCost

    cost = db.get(ActualCost, cost_id)
    if cost is None:
        raise HTTPException(status_code=404, detail="Costo no encontrado")
    _project_guard(cost.project_id, db, user)
    db.delete(cost)
    db.commit()


@router.patch("/work-tasks/{task_id}")
def patch_task(
    task_id: int,
    payload: TaskPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Edita una tarea de un BORRADOR (el baseline congelado es inmutable —
    para cambiarlo: rebaseline)."""
    task = db.get(WorkTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    plan = _plan_guard(task.work_plan_id, db, user)
    if plan.status != "draft":
        raise HTTPException(
            status_code=409,
            detail="El baseline congelado no se edita: usá 'Reprogramar' para crear una versión nueva.")

    if payload.name is not None:
        task.name = payload.name
    if payload.planned_start is not None:
        task.planned_start = dt.date.fromisoformat(payload.planned_start)
    if payload.duration_days is not None:
        task.duration_days = payload.duration_days
    task.planned_end = task.planned_start + dt.timedelta(days=task.duration_days)
    db.commit()
    db.refresh(plan)
    return wp.serialize(plan)
