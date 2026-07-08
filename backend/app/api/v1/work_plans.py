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
