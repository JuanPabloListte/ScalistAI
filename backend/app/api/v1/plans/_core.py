import uuid
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.uploads import save_upload
from app.models import Plan, User
from app.schemas.plan import PlanRead
from app.services import project_access as pa

from ._common import MAX_IFC_BYTES

router = APIRouter(tags=["plans"])


@router.post(
    "/projects/{project_id}/plans",
    response_model=PlanRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_plan(
    project_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Plan:
    project = pa.require_project(project_id, db, user, edit_plan=True)[0]

    fname_lower = (file.filename or "").lower()
    is_ifc = fname_lower.endswith(".ifc")

    # IFC (BIM): modelo exacto, sin páginas ni raster. Salta el visor -> presupuesto.
    if is_ifc:
        from app.core.jobs import enqueue
        from app.services.ifc_import import build_ifc_plan, process_ifc

        # Hasta 500 MB: se vuelca a disco por bloques, nunca entero en memoria.
        tmp = Path(settings.STORAGE_DIR) / "plans" / str(project_id) / f"{uuid.uuid4().hex}.part"
        await save_upload(file, tmp, MAX_IFC_BYTES)
        try:
            plan = build_ifc_plan(project_id, tmp, file.filename or "modelo.ifc", db)
        finally:
            tmp.unlink(missing_ok=True)
        if project.wizard_step < 2:
            project.wizard_step = 2
        db.commit()
        db.refresh(plan)
        # Al worker: parsear 200+ MB dentro del proceso web corrompía la
        # geometría bajo presión de memoria (8 de 92 muros).
        enqueue(process_ifc, plan.id, background_tasks=background_tasks)
        return plan

    raise HTTPException(
        status_code=400,
        detail="Solo se aceptan modelos BIM en formato .ifc.",
    )


@router.get("/projects/{project_id}/plans", response_model=list[PlanRead])
def list_plans(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Plan]:
    pa.require_project(project_id, db, user)  # cualquier miembro del proyecto lo lista
    stmt = select(Plan).where(Plan.project_id == project_id).order_by(Plan.created_at.desc())
    return list(db.scalars(stmt).all())


@router.get("/plans/{plan_id}", response_model=PlanRead)
def get_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Plan:
    plan, _, _ = pa.require_plan(plan_id, db, user)
    return plan

