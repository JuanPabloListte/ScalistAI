import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.plan import Plan
from app.models.project import Project
from app.models.user import User
from app.services import project_access as pa
from app.schemas.project import (
    BuildingInfoUpdate,
    LocationUpdate,
    ProjectCreate,
    ProjectRead,
    ProjectUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Project:
    project = Project(
        organization_id=user.organization_id,
        user_id=user.id,
        name=payload.name,
        description=payload.description,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("", response_model=list[ProjectRead])
def list_projects(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Project]:
    stmt = (
        select(Project)
        .where(Project.organization_id == user.organization_id)
        .order_by(Project.created_at.desc())
    )
    projects = list(db.scalars(stmt).all())

    # El admin (y superadmin) ve todos los proyectos de la org. Un miembro común
    # solo ve los suyos: los que NO tienen equipo asignado (retrocompat, todos
    # ven todo) + aquellos donde figura como miembro. Misma regla que
    # services/project_access.get_access; `project.members` viene con selectin,
    # así que el filtro es en memoria (sin N+1).
    if user.is_superadmin or user.org_role == "admin":
        return projects
    return [
        p for p in projects
        if not p.members or any(m.user_id == user.id for m in p.members)
    ]


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Project:
    project = pa.require_project(project_id, db, user)[0]
    return project


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Project:
    project = pa.require_project(project_id, db, user, edit_plan=True)[0]
    if payload.name is not None:
        project.name = payload.name
    if payload.description is not None:
        # description "" desde el frontend se interpreta como "limpiar"
        project.description = payload.description.strip() or None
    db.commit()
    db.refresh(project)
    return project


@router.patch("/{project_id}/location", response_model=ProjectRead)
def update_project_location(
    project_id: int,
    payload: LocationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Project:
    project = pa.require_project(project_id, db, user, edit_plan=True)[0]

    project.address = payload.address
    project.latitude = payload.latitude
    project.longitude = payload.longitude
    project.city = payload.city
    project.country = payload.country
    project.wizard_step = max(project.wizard_step, 4)

    db.commit()
    db.refresh(project)
    return project


@router.patch("/{project_id}/building-info", response_model=ProjectRead)
def update_project_building_info(
    project_id: int,
    payload: BuildingInfoUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Project:
    project = pa.require_project(project_id, db, user, edit_plan=True)[0]

    project.building_type = payload.building_type
    project.building_info = payload.building_info
    project.wizard_step = max(project.wizard_step, 5)

    db.commit()
    db.refresh(project)
    return project


@router.post("/{project_id}/activate", response_model=ProjectRead)
def activate_project(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Project:
    """Cierra el wizard: valida que esten todos los datos y activa el proyecto."""
    project = pa.require_project(project_id, db, user, edit_plan=True)[0]

    if not project.name:
        raise HTTPException(status_code=400, detail="Falta el nombre del proyecto")

    plans = list(db.scalars(select(Plan).where(Plan.project_id == project_id)).all())
    if not plans:
        raise HTTPException(status_code=400, detail="Falta subir al menos un plano")

    # IFC: el parse corre en worker. No activar con cómputo incompleto o fallido.
    ifc_plans = [
        p for p in plans if (p.original_filename or "").lower().endswith(".ifc")
    ]
    if ifc_plans:
        if any(p.status == "processing" for p in ifc_plans):
            raise HTTPException(
                status_code=400,
                detail=(
                    "El modelo BIM todavía se está procesando. "
                    "Esperá a que termine antes de activar el proyecto."
                ),
            )
        if not any(p.status == "ready" for p in ifc_plans):
            raise HTTPException(
                status_code=400,
                detail=(
                    "El modelo BIM no se pudo procesar. "
                    "Subí de nuevo el archivo .ifc e intentá otra vez."
                ),
            )

    if project.address is None or project.latitude is None or project.longitude is None:
        raise HTTPException(status_code=400, detail="Falta la ubicacion del proyecto")

    # El paso "Construcción" del wizard está oculto: tipo + datos de obra los
    # autocompleta el import IFC (_autofill_building) y ya no bloquean activar.

    project.status = "active"
    project.wizard_step = 6
    db.commit()
    db.refresh(project)


    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    project = pa.require_project(project_id, db, user, edit_plan=True)[0]

    # IDs de los planes ANTES de la cascada — los necesitamos para limpiar sus
    # datos sintéticos de entrenamiento. Si no, quedan huérfanos en disco y
    # siguen alimentando el modelo aunque el usuario borró el proyecto.
    plan_ids = list(
        db.execute(select(Plan.id).where(Plan.project_id == project_id))
        .scalars()
        .all()
    )

    # Limpia los archivos del filesystem; la cascada de SQLAlchemy borra las filas de plans.
    plan_dir = Path(settings.STORAGE_DIR) / "plans" / str(project_id)
    if plan_dir.exists():
        shutil.rmtree(plan_dir, ignore_errors=True)

    # Limpia las variaciones sintéticas de cada plano (corpus de training).
    synthetic_root = Path(settings.STORAGE_DIR) / "synthetic"
    for pid in plan_ids:
        sdir = synthetic_root / f"plan_{pid}"
        if sdir.exists():
            shutil.rmtree(sdir, ignore_errors=True)
            logger.info("delete_project: limpiado sintético %s", sdir)

    db.delete(project)
    db.commit()


# ---------------------------------------------------------------------------
# Cronograma de obra (Gantt) + curva de inversión
# ---------------------------------------------------------------------------
@router.get("/{project_id}/schedule")
def get_schedule(
    project_id: int,
    start_date: str | None = None,
    crews: int = 1,
    overlap_pct: float = 0.0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Cronograma: tareas (assemblies) con duración, fechas y costo, por etapa."""
    import datetime as _dt

    from app.services.schedule import compute_schedule

    pa.require_project(project_id, db, user, financials=True)  # trae costos
    sd = _dt.date.fromisoformat(start_date) if start_date else None
    return compute_schedule(project_id, db, sd, max(1, crews), overlap_pct)


@router.get("/{project_id}/cashflow")
def get_cashflow(
    project_id: int,
    start_date: str | None = None,
    crews: int = 1,
    overlap_pct: float = 0.0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Curva de inversión mensual (flujo de fondos) derivada del cronograma."""
    import datetime as _dt

    from app.services.schedule import compute_cashflow

    pa.require_project(project_id, db, user, financials=True)  # trae costos
    sd = _dt.date.fromisoformat(start_date) if start_date else None
    return compute_cashflow(project_id, db, sd, max(1, crews), overlap_pct)
