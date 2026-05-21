import math
import uuid
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.plan import Plan
from app.models.project import Project
from app.models.user import User
from app.schemas.plan import PlanRead, ScaleByRatio, ScaleCalibration
from app.services.auto_scale import detect_scales
from app.services.pdf import page_count, rasterize
from app.services.preprocess import enhance_for_display
from app.services.prewarm import prewarm_plan_pages

router = APIRouter(tags=["plans"])

MAX_PDF_BYTES = 50 * 1024 * 1024
# 150 DPI da ~30 MP por página A3 — tamaño que el browser muestra sin pérdida
# de líneas finas al hacer fit-zoom. Para IA pesada futura usaremos un caché
# aparte a 300 DPI.
RASTER_DPI = 150


def _page_raster_path(pdf_path: Path, page: int) -> Path:
    """Path donde cacheamos el PNG binarizado de una página (1-indexed)."""
    return pdf_path.with_name(f"{pdf_path.stem}_p{page}.png")


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
    project = db.get(Project, project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos PDF")

    contents = await file.read()
    if len(contents) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="Archivo demasiado grande (máx 50 MB)")

    plan_storage = Path(settings.STORAGE_DIR) / "plans" / str(project_id)
    plan_storage.mkdir(parents=True, exist_ok=True)

    file_id = uuid.uuid4().hex
    pdf_path = plan_storage / f"{file_id}.pdf"
    pdf_path.write_bytes(contents)

    try:
        n_pages = page_count(pdf_path)
    except Exception as exc:  # noqa: BLE001
        pdf_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"PDF inválido: {exc}") from exc

    # Intento de auto-calibración leyendo texto del PDF (best-effort).
    try:
        auto_scales = detect_scales(pdf_path, RASTER_DPI)
    except Exception:  # noqa: BLE001
        auto_scales = {}

    plan = Plan(
        project_id=project_id,
        original_filename=file.filename or f"{file_id}.pdf",
        pdf_path=str(pdf_path),
        dpi=RASTER_DPI,
        page_count=n_pages,
        status="ready",
        page_scales=auto_scales or None,
        scale_source="auto_text" if auto_scales else None,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)

    # Pre-warm las páginas en background. La primera request del navegador
    # también puede dispararse antes de que el background termine — en ese
    # caso el endpoint /raster cae al fallback síncrono y renderiza la página
    # individual que se pidió.
    background_tasks.add_task(prewarm_plan_pages, plan.id)

    return plan


@router.get("/projects/{project_id}/plans", response_model=list[PlanRead])
def list_plans(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Plan]:
    project = db.get(Project, project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    stmt = select(Plan).where(Plan.project_id == project_id).order_by(Plan.created_at.desc())
    return list(db.scalars(stmt).all())


@router.get("/plans/{plan_id}", response_model=PlanRead)
def get_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Plan:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    return plan


@router.post("/plans/{plan_id}/prewarm", status_code=status.HTTP_202_ACCEPTED)
def start_prewarm(
    plan_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, int | str]:
    """Dispara (idempotente) el pre-render de todas las páginas en background.

    El visor lo llama cuando se abre un plano para asegurarse de que el caché
    esté caliente — útil para planos viejos que se subieron antes de que el
    upload disparara el background automáticamente.
    """
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    pdf_path = Path(plan.pdf_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF original no disponible")

    if plan.page_count is None:
        try:
            plan.page_count = page_count(pdf_path)
            db.commit()
            db.refresh(plan)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"PDF ilegible: {exc}") from exc

    background_tasks.add_task(prewarm_plan_pages, plan.id)
    return {"status": "scheduled", "page_count": plan.page_count or 0}


@router.post("/plans/{plan_id}/scale", response_model=PlanRead)
def calibrate_scale(
    plan_id: int,
    payload: ScaleCalibration,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Plan:
    """Calibra la escala de UNA página manualmente y la guarda en page_scales[page]."""
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    if plan.page_count and payload.page > plan.page_count:
        raise HTTPException(status_code=400, detail="Página fuera de rango")

    dx = payload.p2.x - payload.p1.x
    dy = payload.p2.y - payload.p1.y
    pixel_distance = math.sqrt(dx * dx + dy * dy)
    if pixel_distance < 1:
        raise HTTPException(
            status_code=400, detail="Los puntos están demasiado cerca para calibrar"
        )

    px_per_m = pixel_distance / payload.real_distance_m
    scales = dict(plan.page_scales or {})
    scales[str(payload.page)] = round(px_per_m, 4)
    plan.page_scales = scales
    plan.scale_source = "manual"
    db.commit()
    db.refresh(plan)
    return plan


@router.post("/plans/{plan_id}/scale-ratio", response_model=PlanRead)
def set_scale_by_ratio(
    plan_id: int,
    payload: ScaleByRatio,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Plan:
    """Setea la escala de una página dando directamente el denominador (1:N)."""
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    if plan.page_count and payload.page > plan.page_count:
        raise HTTPException(status_code=400, detail="Página fuera de rango")

    dpi = plan.dpi or RASTER_DPI
    px_per_m = (dpi * 1000.0) / (25.4 * payload.denominator)
    scales = dict(plan.page_scales or {})
    scales[str(payload.page)] = round(px_per_m, 4)
    plan.page_scales = scales
    plan.scale_source = "manual_ratio"
    db.commit()
    db.refresh(plan)
    return plan


@router.delete("/plans/{plan_id}/scale/{page}", response_model=PlanRead)
def clear_page_scale(
    plan_id: int,
    page: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Plan:
    """Borra la escala de una página puntual."""
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    scales = dict(plan.page_scales or {})
    scales.pop(str(page), None)
    plan.page_scales = scales or None
    db.commit()
    db.refresh(plan)
    return plan


@router.post("/plans/{plan_id}/auto-detect-scale", response_model=PlanRead)
def auto_detect_scale(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Plan:
    """Re-corre la detección automática de escalas leyendo el texto del PDF.

    Las calibraciones manuales previas (presentes en page_scales) tienen
    precedencia y no se sobreescriben.
    """
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    pdf_path = Path(plan.pdf_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF original no disponible")

    detected = detect_scales(pdf_path, plan.dpi or RASTER_DPI)
    existing = dict(plan.page_scales or {})
    # Existing wins → no pisamos calibraciones manuales del usuario.
    merged = {**detected, **existing}
    plan.page_scales = merged or None
    if not plan.scale_source and merged:
        plan.scale_source = "auto_text"
    db.commit()
    db.refresh(plan)
    return plan


@router.get("/plans/{plan_id}/preview-auto-detect")
def preview_auto_detect_scale(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, int]:
    """Escanea el texto del PDF y devuelve las escalas detectadas sin guardarlas.
    Retorna un diccionario {pagina: denominador} (ej: {"1": 100, "2": 50}).
    """
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    pdf_path = Path(plan.pdf_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF original no disponible")

    import fitz
    from app.services.auto_scale import _find_denominator
    doc = fitz.open(pdf_path)
    result = {}
    try:
        for i in range(doc.page_count):
            page = doc.load_page(i)
            text = page.get_text("text") or ""
            denominator = _find_denominator(text)
            if denominator is not None and denominator > 0:
                result[str(i + 1)] = int(denominator)
    finally:
        doc.close()
    return result


@router.post("/plans/{plan_id}/bulk-scale-ratio", response_model=PlanRead)
def set_bulk_scale_by_ratio(
    plan_id: int,
    payload: dict[str, float],
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Plan:
    """Setea la escala de varias páginas a la vez dando sus denominadores (1:N)."""
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    dpi = plan.dpi or RASTER_DPI
    scales = dict(plan.page_scales or {})

    for page_str, denominator in payload.items():
        try:
            page = int(page_str)
        except ValueError:
            raise HTTPException(status_code=400, detail="Número de página inválido")

        if plan.page_count and page > plan.page_count:
            raise HTTPException(status_code=400, detail=f"Página {page} fuera de rango")
        if denominator <= 0:
            raise HTTPException(status_code=400, detail="El denominador debe ser mayor a 0")

        px_per_m = (dpi * 1000.0) / (25.4 * denominator)
        scales[page_str] = round(px_per_m, 4)

    plan.page_scales = scales
    plan.scale_source = "manual_ratio"
    db.commit()
    db.refresh(plan)
    return plan


@router.get("/plans/{plan_id}/render-status")
def get_render_status(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, int]:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    total = plan.page_count or 0
    pdf_path = Path(plan.pdf_path)
    if not pdf_path.exists() or total == 0:
        return {"rendered": 0, "total": total}
    rendered = sum(1 for _ in pdf_path.parent.glob(f"{pdf_path.stem}_p*.png"))
    return {"rendered": min(rendered, total), "total": total}


@router.get("/plans/{plan_id}/raster")
def get_plan_raster(
    plan_id: int,
    page: int = Query(default=1, ge=1, description="Número de página, base 1"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileResponse:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    pdf_path = Path(plan.pdf_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF original no disponible")

    # Backfill page_count para planos creados con la versión anterior.
    if plan.page_count is None:
        try:
            plan.page_count = page_count(pdf_path)
            db.commit()
            db.refresh(plan)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"PDF ilegible: {exc}") from exc

    if page > plan.page_count:
        raise HTTPException(
            status_code=400,
            detail=f"Página {page} fuera de rango (1..{plan.page_count})",
        )

    cached = _page_raster_path(pdf_path, page)
    if not cached.exists():
        try:
            raster_bytes = rasterize(pdf_path, page_index=page - 1, dpi=plan.dpi or RASTER_DPI)
            enhanced = enhance_for_display(raster_bytes)
            cached.write_bytes(enhanced)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=500,
                detail=f"Error procesando página {page}: {exc}",
            ) from exc

    return FileResponse(cached, media_type="image/png")
