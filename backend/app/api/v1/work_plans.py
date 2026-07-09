"""API del módulo Obra (Etapa 1): plan de obra persistido y versionado.

Flujo: POST draft (genera desde el cómputo) → PATCH tareas (editar borrador)
→ POST freeze (baseline inmutable) → POST rebaseline (vN+1 para re-programar).
GET devuelve el plan que manda (draft > active) con el mismo shape del
cronograma calculado, así el Gantt del frontend reusa el render.
"""
from __future__ import annotations

import datetime as dt
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import Project, User
from app.models.work_plan import ObraShareLink, WorkPlan, WorkTask
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
    # Baseline (solo editable en borrador).
    name: Optional[str] = None
    duration_days: Optional[int] = Field(None, ge=1, le=730)
    planned_start: Optional[str] = None  # ISO
    depends_on: Optional[list[int]] = None
    # Flujo de ejecución (editable también sobre el baseline activo).
    status: Optional[str] = Field(None, pattern="^(pending|in_progress|in_review|completed|blocked|cancelled)$")
    priority: Optional[str] = Field(None, pattern="^(low|medium|high|critical)$")
    assignee_ids: Optional[list[int]] = None  # lista completa; [] desasigna a todos
    description: Optional[str] = None
    note: Optional[str] = None         # comentario libre para el historial


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


@router.get("/projects/{project_id}/work-alerts")
def get_work_alerts(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Alertas anticipadas del baseline activo: retrasos que empujan la obra
    (holgura CPM), sobrecosto (CPI), pre-acopio (material subiendo > IPC) y
    sugerencias de recalibración de rendimientos. 404 si no hay baseline."""
    from app.services.work_alerts import build_alerts

    _project_guard(project_id, db, user)
    active = next((p for p in wp.list_versions(project_id, db)
                   if p.status == "active"), None)
    if active is None:
        raise HTTPException(status_code=404,
                            detail="No hay baseline activo: congelá el plan de obra primero.")
    db.refresh(active)
    return build_alerts(active, db)


def _render_report(project: Project, db: Session, public: bool) -> bytes:
    """Genera el PDF del reporte del baseline activo. `public` omite lo
    financiero (para el link del comitente). 404 si no hay baseline."""
    from app.services.work_alerts import build_alerts
    from app.services.work_cost import cost_summary
    from app.services.work_progress import plan_progress
    from app.services.work_report import build_work_report_pdf

    active = next((p for p in wp.list_versions(project.id, db)
                   if p.status == "active"), None)
    if active is None:
        raise HTTPException(status_code=404,
                            detail="No hay baseline activo: congelá el plan de obra primero.")
    db.refresh(active)
    return build_work_report_pdf(
        project.name, wp.serialize(active), plan_progress(active, db),
        cost_summary(active, db), build_alerts(active, db), public=public)


def _pdf_response(pdf: bytes, project_name: str, inline: bool):
    from fastapi.responses import StreamingResponse
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in project_name)[:60]
    disp = "inline" if inline else "attachment"
    return StreamingResponse(
        iter([pdf]), media_type="application/pdf",
        headers={"Content-Disposition": f'{disp}; filename="obra_{safe}.pdf"'})


@router.get("/projects/{project_id}/work-report.pdf")
def get_work_report(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Reporte ejecutivo de obra en PDF (avance físico + EVM ajustado por IPC +
    alertas + detalle de tareas). Entregable interno. 404 si no hay baseline."""
    project = _project_guard(project_id, db, user)
    return _pdf_response(_render_report(project, db, public=False), project.name, inline=False)


# ---- Link solo-lectura para el comitente -------------------------------------

def _active_share_link(project_id: int, db: Session) -> ObraShareLink | None:
    return db.scalars(
        select(ObraShareLink).where(
            ObraShareLink.project_id == project_id,
            ObraShareLink.revoked_at.is_(None))
        .order_by(ObraShareLink.id.desc())).first()


def _share_payload(link: ObraShareLink | None) -> dict:
    if link is None:
        return {"token": None, "report_url": None, "created_at": None}
    return {
        "token": link.token,
        "report_url": f"/api/v1/public/obra/{link.token}/report.pdf",
        "created_at": link.created_at.isoformat() if link.created_at else None,
    }


@router.get("/projects/{project_id}/share-link")
def get_share_link(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Devuelve el link activo de solo lectura del proyecto (o token=None)."""
    _project_guard(project_id, db, user)
    return _share_payload(_active_share_link(project_id, db))


@router.post("/projects/{project_id}/share-link")
def create_share_link(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Crea (o rota) el link de solo lectura. Revoca el anterior: un token
    activo por proyecto. El token es opaco (256 bits)."""
    _project_guard(project_id, db, user)
    existing = _active_share_link(project_id, db)
    if existing is not None:
        existing.revoked_at = dt.datetime.now(dt.UTC)
    link = ObraShareLink(
        project_id=project_id, token=secrets.token_urlsafe(32), created_by=user.id)
    db.add(link)
    db.commit()
    db.refresh(link)
    return _share_payload(link)


@router.delete("/projects/{project_id}/share-link", status_code=204)
def revoke_share_link(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """Revoca el link activo (el comitente deja de poder ver el reporte)."""
    _project_guard(project_id, db, user)
    link = _active_share_link(project_id, db)
    if link is not None:
        link.revoked_at = dt.datetime.now(dt.UTC)
        db.commit()


def _project_from_token(token: str, db: Session) -> Project:
    """Resuelve un token público → proyecto. Sin auth: el token ES la
    credencial. 404 si no existe o fue revocado."""
    link = db.scalars(select(ObraShareLink).where(
        ObraShareLink.token == token, ObraShareLink.revoked_at.is_(None))).first()
    if link is None:
        raise HTTPException(status_code=404, detail="Link no válido o revocado.")
    project = db.get(Project, link.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
    return project


@router.get("/public/obra/{token}")
def public_obra_summary(token: str, db: Session = Depends(get_db)) -> dict:
    """Resumen PÚBLICO de avance para el comitente (sin login, sin financieros):
    % físico, cronograma y fecha proyectada."""
    from app.services.work_progress import plan_progress

    project = _project_from_token(token, db)
    active = next((p for p in wp.list_versions(project.id, db)
                   if p.status == "active"), None)
    if active is None:
        return {"project": project.name, "has_report": False}
    db.refresh(active)
    prog = plan_progress(active, db)
    tot = prog["totals"]
    return {
        "project": project.name, "has_report": True, "as_of": prog["as_of"],
        "pct_fisico": tot["pct_fisico"], "spi": tot["spi"],
        "planned_end": tot["planned_end"], "projected_end": tot["projected_end"],
        "delay_days": tot["delay_days"],
        "report_url": f"/api/v1/public/obra/{token}/report.pdf",
    }


@router.get("/public/obra/{token}/report.pdf")
def public_obra_report(token: str, db: Session = Depends(get_db)):
    """Reporte de avance PÚBLICO (sin login, sin financieros del contratista).
    Se abre inline en el navegador."""
    project = _project_from_token(token, db)
    return _pdf_response(_render_report(project, db, public=True), project.name, inline=True)


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
    """Edita una tarea. Dos planos separados:

    - BASELINE (nombre, fecha, duración, dependencias): solo sobre un BORRADOR;
      el cronograma congelado es inmutable (para cambiarlo: reprogramar).
    - FLUJO (estado, prioridad, responsable, comentario): metadata de EJECUCIÓN,
      editable también sobre el baseline activo — no altera el plan medido.

    Cada cambio queda en el historial de la tarea (pestaña "Historial")."""
    task = db.get(WorkTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    plan = _plan_guard(task.work_plan_id, db, user)
    project = db.get(Project, plan.project_id)
    try:
        wp.edit_task(task, plan, project.organization_id,
                     payload.model_dump(exclude_unset=True), user.id, db)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    db.refresh(plan)
    return wp.serialize(plan)


class TaskCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    stage: str = Field("Sin etapa", max_length=64)
    stage_order: int = Field(0, ge=0, le=99)
    planned_start: Optional[str] = None            # ISO; default = inicio del plan
    duration_days: int = Field(1, ge=1, le=730)
    unit: str = Field("un", max_length=16)
    qty_planned: float = Field(0.0, ge=0)
    cost_planned: float = Field(0.0, ge=0)
    depends_on: list[int] = Field(default_factory=list)
    priority: str = Field("medium", pattern="^(low|medium|high|critical)$")
    status: str = Field("pending", pattern="^(pending|in_progress|in_review|completed|blocked|cancelled)$")
    assignee_ids: list[int] = Field(default_factory=list)
    description: Optional[str] = None
    note: Optional[str] = None


@router.post("/work-plans/{plan_id}/work-tasks")
def create_task(
    plan_id: int,
    payload: TaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Crea una tarea MANUAL (change order / imprevisto de obra). Se permite
    sobre borrador y sobre el baseline activo: es aditiva, no altera las tareas
    del cronograma congelado. Si `planned_start` es None, arranca al terminar
    su(s) predecesora(s) (o al inicio del plan si no tiene dependencias)."""
    plan = _plan_guard(plan_id, db, user)
    project = db.get(Project, plan.project_id)
    try:
        wp.create_manual_task(plan, project.organization_id,
                              payload.model_dump(), user.id, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    db.refresh(plan)
    return wp.serialize(plan)


@router.delete("/work-tasks/{task_id}", status_code=204)
def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """Elimina una tarea MANUAL (change order). Las tareas del cómputo
    (source="auto") son el cronograma: no se borran sueltas — se cambian
    reprogramando una versión nueva."""
    task = db.get(WorkTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    _plan_guard(task.work_plan_id, db, user)
    if task.source != "manual":
        raise HTTPException(
            status_code=409,
            detail="Solo se eliminan tareas manuales; las del cronograma se cambian reprogramando.")
    db.delete(task)
    db.commit()


@router.get("/work-tasks/{task_id}/history")
def get_task_history(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Historial de cambios de la tarea (más reciente primero) para la pestaña
    "Historial" del detalle."""
    task = db.get(WorkTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    _plan_guard(task.work_plan_id, db, user)
    return [{
        "id": e.id, "field": e.field,
        "old_value": e.old_value, "new_value": e.new_value, "note": e.note,
        "author_email": e.author.email if e.author else None,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    } for e in task.events]
