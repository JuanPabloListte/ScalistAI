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
from app.schemas.project import (
    BuildingInfoUpdate,
    LocationUpdate,
    ProjectCreate,
    ProjectRead,
    ProjectUpdate,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Project:
    project = Project(
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
    stmt = select(Project).where(Project.user_id == user.id).order_by(Project.created_at.desc())
    return list(db.scalars(stmt).all())


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    return project


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
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
    project = db.get(Project, project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

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
    project = db.get(Project, project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

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
    project = db.get(Project, project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    if not project.name:
        raise HTTPException(status_code=400, detail="Falta el nombre del proyecto")

    has_plan = db.scalar(select(Plan.id).where(Plan.project_id == project_id).limit(1))
    if has_plan is None:
        raise HTTPException(status_code=400, detail="Falta subir al menos un plano")

    if project.address is None or project.latitude is None or project.longitude is None:
        raise HTTPException(status_code=400, detail="Falta la ubicacion del proyecto")

    if project.building_type is None or not project.building_info:
        raise HTTPException(status_code=400, detail="Falta la informacion de construccion")

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
    project = db.get(Project, project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    # Limpia los archivos del filesystem; la cascada de SQLAlchemy borra las filas de plans.
    plan_dir = Path(settings.STORAGE_DIR) / "plans" / str(project_id)
    if plan_dir.exists():
        shutil.rmtree(plan_dir, ignore_errors=True)

    db.delete(project)
    db.commit()
