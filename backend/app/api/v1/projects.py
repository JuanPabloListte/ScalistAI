import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.detected_element import DetectedElement
from app.models.plan import Plan
from app.models.project import Project
from app.models.user import User
from app.schemas.project import (
    BuildingInfoUpdate,
    LocationUpdate,
    ProjectCreate,
    ProjectRead,
    ProjectUpdate,
    TrainingConsentUpdate,
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
    stmt = select(Project).where(Project.organization_id == user.organization_id).order_by(Project.created_at.desc())
    return list(db.scalars(stmt).all())


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.organization_id != user.organization_id:
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
    if project is None or project.organization_id != user.organization_id:
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
    if project is None or project.organization_id != user.organization_id:
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
    if project is None or project.organization_id != user.organization_id:
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
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Project:
    """Cierra el wizard: valida que esten todos los datos y activa el proyecto."""
    project = db.get(Project, project_id)
    if project is None or project.organization_id != user.organization_id:
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

    # Snapshot automático para training: si el proyecto tiene consentimiento,
    # y el feature flag global está activo, gatillamos la generación de
    # variaciones sintéticas en background por cada página con elementos.
    if (
        getattr(settings, "AUTO_GENERATE_TRAINING_DATA", True)
        and project.allow_training_data
    ):
        from app.core.jobs import enqueue

        # Al worker: rasteriza y genera variaciones sintéticas (CPU-pesado).
        enqueue(_snapshot_project_for_training, project.id,
                background_tasks=background_tasks)

    return project


def _snapshot_project_for_training(project_id: int) -> None:
    """Background task: genera variaciones sintéticas para cada página con
    elementos confirmados. Llamado al activar el proyecto. Si falla, loggea
    pero no rompe — el activate ya respondió OK al usuario.
    """
    from app.core.database import SessionLocal
    from app.services.synthetic_generator import generate_synthetic_variations

    try:
        with SessionLocal() as db:
            plans = list(
                db.execute(select(Plan).where(Plan.project_id == project_id))
                .scalars()
                .all()
            )
        for plan in plans:
            # Identificar páginas que tienen al menos un elemento confirmado.
            with SessionLocal() as db:
                pages_with_elements = list(
                    db.execute(
                        select(DetectedElement.page)
                        .where(DetectedElement.plan_id == plan.id)
                        .distinct()
                    )
                    .scalars()
                    .all()
                )
            for page in pages_with_elements:
                try:
                    metas = generate_synthetic_variations(
                        plan.id, page, num_variations=40,
                    )
                    logger.info(
                        "training snapshot project=%s plan=%s page=%s n=%d",
                        project_id, plan.id, page, len(metas),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "snapshot failed project=%s plan=%s page=%s: %s",
                        project_id, plan.id, page, exc,
                    )
    except Exception as exc:  # noqa: BLE001
        logger.exception("training snapshot failed project=%s: %s", project_id, exc)


# Tipos que el modelo actual sabe entrenar. Páginas que sólo tienen elementos
# fuera de este set (ej: sólo `roof`) se saltean — generar máscaras vacías
# sobre planos que sí tienen estructura le enseñaría al modelo a "no predecir
# nada" en imágenes con contenido real.
_TRAINABLE_TYPES = {"wall", "room", "opening", "beam", "column"}


@router.post("/regenerate-synthetic")
def regenerate_synthetic_for_user(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Recorre todos los proyectos del usuario con consentimiento de training
    y regenera variaciones sintéticas para cada página con al menos un
    elemento entrenable.

    Solución al problema del snapshot único: `_snapshot_project_for_training`
    sólo corre al activar el proyecto. Si después confirmás elementos en
    páginas nuevas (típico: confirmar vigas/columnas en páginas estructurales
    que no tenían nada al activar), esas páginas quedan sin sintético y el
    modelo nunca las ve.

    Este endpoint te deja re-disparar el snapshot completo de tus proyectos
    cuando quieras, sin tener que tocar la DB o re-activar el proyecto.

    Devuelve un resumen plan-por-plan con cuántas variaciones se generaron.
    Es sincrónico: bloquea hasta terminar, pero corre en threadpool y no
    bloquea otras requests.
    """
    from app.services.synthetic_generator import generate_synthetic_variations

    projects = list(
        db.execute(
            select(Project)
            .where(Project.organization_id == user.organization_id, Project.allow_training_data == True)  # noqa: E712
        )
        .scalars()
        .all()
    )

    if not projects:
        return {
            "projects_processed": 0,
            "plans_processed": 0,
            "pages_processed": 0,
            "variations_generated": 0,
            "details": [],
            "message": (
                "No tenés proyectos con consentimiento de training activo. "
                "Marcá `allow_training_data=True` en al menos un proyecto."
            ),
        }

    details: list[dict] = []
    total_pages = 0
    total_variations = 0

    for project in projects:
        plans = list(
            db.execute(select(Plan).where(Plan.project_id == project.id))
            .scalars()
            .all()
        )
        for plan in plans:
            # Sólo páginas con al menos un elemento de tipo entrenable.
            pages = sorted({
                row[0] for row in db.execute(
                    select(DetectedElement.page)
                    .where(
                        DetectedElement.plan_id == plan.id,
                        DetectedElement.type.in_(_TRAINABLE_TYPES),
                    )
                    .distinct()
                ).all()
            })
            for page in pages:
                try:
                    metas = generate_synthetic_variations(
                        plan.id, page, num_variations=40,
                    )
                    total_pages += 1
                    total_variations += len(metas)
                    details.append({
                        "project_id": project.id,
                        "plan_id": plan.id,
                        "page": page,
                        "variations": len(metas),
                        "ok": True,
                    })
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "regenerate_synthetic failed plan=%s page=%s: %s",
                        plan.id, page, exc,
                    )
                    details.append({
                        "project_id": project.id,
                        "plan_id": plan.id,
                        "page": page,
                        "variations": 0,
                        "ok": False,
                        "error": str(exc),
                    })

    return {
        "projects_processed": len(projects),
        "plans_processed": len({d["plan_id"] for d in details if d["ok"]}),
        "pages_processed": total_pages,
        "variations_generated": total_variations,
        "details": details,
    }


@router.patch("/{project_id}/training-consent", response_model=ProjectRead)
def set_training_consent(
    project_id: int,
    payload: TrainingConsentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Project:
    """Cambia el flag `allow_training_data` del proyecto.

    Cuando es False, al activar el proyecto **no** se generan variaciones
    sintéticas a partir de sus planos. Útil para clientes con NDA estricto
    o IP sensible que no quieren contribuir al training global.

    Cambiarlo a False **después** de activar no borra las variaciones ya
    generadas — para eso usar el endpoint de purge (Sprint 6).
    """
    project = db.get(Project, project_id)
    if project is None or project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    project.allow_training_data = payload.allow_training_data
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
    if project is None or project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

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

    project = db.get(Project, project_id)
    if project is None or project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
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

    project = db.get(Project, project_id)
    if project is None or project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    sd = _dt.date.fromisoformat(start_date) if start_date else None
    return compute_cashflow(project_id, db, sd, max(1, crews), overlap_pct)
