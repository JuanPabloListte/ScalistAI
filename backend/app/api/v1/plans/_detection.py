from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import Plan, User
from app.models.plan_ai_context import PlanAiContext
from app.schemas.plan import PageRolesUpdate
from app.services.auto_detect_pipeline import get_ai_status, run_initial_detection
from app.services.ml_detector import get_ml_detector

from ._common import RASTER_DPI

router = APIRouter(tags=["plans"])


def _ml_page_candidates(plan: Plan, page: int, kind: str) -> list[dict]:
    """Corre inferencia ML sobre una página y devuelve los candidatos del tipo pedido.

    No persiste nada — solo propone. Devuelve [] si el modelo no está disponible.
    """
    detector = get_ml_detector()
    if not detector.is_available():
        return []

    import numpy as np

    scales = plan.page_scales or {}
    px_per_m = scales.get(str(page))

    if plan.scale_source == "dxf":
        # Página CAD: el apply de recortes deja un PNG gemelo del SVG de cada
        # página ({id}_p{n}.png) con la misma escala. La IA corre sobre ese
        # PNG exactamente igual que sobre el raster de una página PDF.
        from PIL import Image

        src = Path(plan.pdf_path)
        stem = src.stem[:-3] if src.stem.endswith("_p1") else src.stem
        png = src.with_name(f"{stem}_p{page}.png")
        if not png.exists():
            return []
        img = np.array(Image.open(png).convert("RGB"))
    elif not str(plan.pdf_path).lower().endswith(".pdf"):
        return []
    else:
        import fitz

        pdf_path = Path(plan.pdf_path)
        dpi = plan.dpi or RASTER_DPI

        doc = fitz.open(pdf_path)
        try:
            if page - 1 < 0 or page - 1 >= doc.page_count:
                return []
            p_obj = doc.load_page(page - 1)
            zoom = dpi / 72.0
            pixmap = p_obj.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            img = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                pixmap.height, pixmap.width, 3
            )
        finally:
            doc.close()

    result = detector.detect(img, px_per_m, page_index=page - 1)
    return list(getattr(result, kind, []) or [])


def _detect_endpoint_guard(plan: Plan | None, page: int, user: User) -> Plan:
    """Validaciones comunes de los endpoints de detección on-demand del editor."""
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    if not Path(plan.pdf_path).exists():
        raise HTTPException(status_code=404, detail="PDF original no disponible")
    if plan.page_count and (page < 1 or page > plan.page_count):
        raise HTTPException(status_code=400, detail="Página fuera de rango")
    return plan


@router.get("/plans/ml-status")
def get_ml_model_status(
    user: User = Depends(get_current_user),
) -> dict:
    """Devuelve si el modelo ML está cargado y disponible."""
    detector = get_ml_detector()
    return {"available": detector.is_available(), **detector.model_info()}


@router.patch("/plans/{plan_id}/page-roles", response_model=None)
def set_page_roles(
    plan_id: int,
    payload: PageRolesUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Plan:
    """Guarda el mapeo página → roles y dispara el pipeline de IA en background."""
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    cleaned: dict[str, list[str]] = {}
    max_page = plan.page_count or 0
    for raw_page, roles in payload.page_roles.items():
        try:
            page_num = int(raw_page)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"Página inválida: {raw_page!r}")
        if max_page and (page_num < 1 or page_num > max_page):
            raise HTTPException(
                status_code=400,
                detail=f"Página {page_num} fuera de rango (1..{max_page})",
            )
        unique = list(dict.fromkeys(roles))
        if unique:
            cleaned[str(page_num)] = unique

    plan.page_roles = cleaned or None
    flag_modified(plan, "page_roles")

    project = plan.project
    if project and project.wizard_step < 3:
        project.wizard_step = 3

    db.commit()
    db.refresh(plan)

    if cleaned and not payload.skip_ai_detection:
        background_tasks.add_task(run_initial_detection, plan.id)

    return plan


@router.get("/plans/{plan_id}/ai-status")
def get_ai_pipeline_status(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Devuelve el progreso del pipeline de IA."""
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    return get_ai_status(plan_id)

@router.get("/plans/{plan_id}/ai-context")
def get_ai_context(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Devuelve el contexto y análisis del LLM para este plano, si lo hay."""
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    
    ctx = db.query(PlanAiContext).filter(PlanAiContext.plan_id == plan_id).first()
    if not ctx:
        return {"provider": "scalist", "messages": []}
    return {"provider": ctx.provider, "messages": ctx.messages}


@router.get("/plans/{plan_id}/detect-openings")
def detect_openings_endpoint(
    plan_id: int,
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Devuelve candidatos de aberturas detectados por ML. No persiste nada."""
    plan = _detect_endpoint_guard(db.get(Plan, plan_id), page, user)
    try:
        return _ml_page_candidates(plan, page, "openings")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Error detectando aberturas: {exc}") from exc


@router.get("/plans/{plan_id}/detect-walls")
def detect_walls_endpoint(
    plan_id: int,
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Devuelve candidatos de muros detectados por ML. No persiste nada."""
    plan = _detect_endpoint_guard(db.get(Plan, plan_id), page, user)
    try:
        return _ml_page_candidates(plan, page, "walls")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Error detectando muros: {exc}") from exc


@router.get("/plans/{plan_id}/detect-rooms")
def detect_rooms_endpoint(
    plan_id: int,
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Devuelve candidatos de recintos detectados por ML. No persiste nada."""
    plan = _detect_endpoint_guard(db.get(Plan, plan_id), page, user)
    try:
        return _ml_page_candidates(plan, page, "rooms")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Error detectando recintos: {exc}") from exc
