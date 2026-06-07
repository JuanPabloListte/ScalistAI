import math

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import Plan, User
from app.schemas.plan import ScaleByRatio, ScaleCalibration, ScaleDirect
from app.services.auto_scale import detect_scales
from app.services.dimension_text import extract_dimensions

from ._common import RASTER_DPI

router = APIRouter(tags=["plans"])


@router.post("/plans/{plan_id}/scale", response_model=None)
def calibrate_scale(
    plan_id: int,
    payload: ScaleCalibration,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Plan:
    """Calibra la escala de una página manualmente y la guarda en page_scales[page]."""
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    if plan.page_count and payload.page > plan.page_count:
        raise HTTPException(status_code=400, detail="Página fuera de rango")

    dx = payload.p2.x - payload.p1.x
    dy = payload.p2.y - payload.p1.y
    pixel_distance = math.sqrt(dx * dx + dy * dy)
    if pixel_distance < 1:
        raise HTTPException(status_code=400, detail="Los puntos están demasiado cerca para calibrar")

    px_per_m = pixel_distance / payload.real_distance_m
    scales = dict(plan.page_scales or {})
    scales[str(payload.page)] = round(px_per_m, 4)
    plan.page_scales = scales
    plan.scale_source = "manual"
    db.commit()
    db.refresh(plan)
    return plan


@router.post("/plans/{plan_id}/scale-direct", response_model=None)
def set_scale_direct(
    plan_id: int,
    payload: ScaleDirect,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Plan:
    """Setea la escala de una página a partir de un px_per_m ya calculado."""
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    if plan.page_count and payload.page > plan.page_count:
        raise HTTPException(status_code=400, detail="Página fuera de rango")
    scales = dict(plan.page_scales or {})
    scales[str(payload.page)] = round(payload.px_per_m, 4)
    plan.page_scales = scales
    plan.scale_source = payload.source
    db.commit()
    db.refresh(plan)
    return plan


@router.post("/plans/{plan_id}/scale-ratio", response_model=None)
def set_scale_by_ratio(
    plan_id: int,
    payload: ScaleByRatio,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Plan:
    """Setea la escala de una página dando directamente el denominador (1:N)."""
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
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


@router.post("/plans/{plan_id}/bulk-scale-ratio", response_model=None)
def set_bulk_scale_by_ratio(
    plan_id: int,
    payload: dict[str, float],
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Plan:
    """Setea la escala de varias páginas a la vez dando sus denominadores (1:N)."""
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
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
        scales[page_str] = round((dpi * 1000.0) / (25.4 * denominator), 4)

    plan.page_scales = scales
    plan.scale_source = "manual_ratio"
    db.commit()
    db.refresh(plan)
    return plan


@router.delete("/plans/{plan_id}/scale/{page}", response_model=None)
def clear_page_scale(
    plan_id: int,
    page: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Plan:
    """Borra la escala de una página puntual."""
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    scales = dict(plan.page_scales or {})
    scales.pop(str(page), None)
    plan.page_scales = scales or None
    db.commit()
    db.refresh(plan)
    return plan


@router.post("/plans/{plan_id}/auto-detect-scale", response_model=None)
def auto_detect_scale(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Plan:
    """Re-corre la detección automática de escalas leyendo el texto del PDF.

    Las calibraciones manuales previas tienen precedencia y no se sobreescriben.
    """
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    from pathlib import Path
    pdf_path = Path(plan.pdf_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF original no disponible")

    detected = detect_scales(pdf_path, plan.dpi or RASTER_DPI)
    existing = dict(plan.page_scales or {})
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
    """Escanea el texto del PDF y devuelve las escalas detectadas sin guardarlas."""
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    from pathlib import Path
    pdf_path = Path(plan.pdf_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF original no disponible")

    import fitz
    from app.services.auto_scale import _find_denominator
    doc = fitz.open(pdf_path)
    result = {}
    try:
        for i in range(doc.page_count):
            p_obj = doc.load_page(i)
            text = p_obj.get_text("text") or ""
            denominator = _find_denominator(text)
            if denominator is not None and denominator > 0:
                result[str(i + 1)] = int(denominator)
    finally:
        doc.close()
    return result


@router.get("/plans/{plan_id}/dimensions")
def list_page_dimensions(
    plan_id: int,
    page: int = 1,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Devuelve las cotas decimales detectadas en el texto vectorial del PDF."""
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    from pathlib import Path
    pdf_path = Path(plan.pdf_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF original no disponible")
    if plan.page_count and (page < 1 or page > plan.page_count):
        raise HTTPException(status_code=400, detail="Página fuera de rango")
    try:
        return extract_dimensions(pdf_path, page - 1, plan.dpi or RASTER_DPI)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Error leyendo cotas: {exc}") from exc
