from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import Plan, User
from app.services.pdf import page_count, rasterize
from app.services.preprocess import enhance_for_display
from app.services.prewarm import prewarm_plan_pages

from ._common import RASTER_DPI, _page_raster_path

router = APIRouter(tags=["plans"])


@router.post("/plans/{plan_id}/prewarm", status_code=status.HTTP_202_ACCEPTED)
def start_prewarm(
    plan_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, int | str]:
    """Dispara (idempotente) el pre-render de todas las páginas en background."""
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
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


@router.get("/plans/{plan_id}/raster")
def get_plan_raster(
    plan_id: int,
    page: int = Query(default=1, ge=1, description="Número de página, base 1"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileResponse:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
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

    if page > plan.page_count:
        raise HTTPException(
            status_code=400,
            detail=f"Página {page} fuera de rango (1..{plan.page_count})",
        )

    if plan.deleted_pages and page in plan.deleted_pages:
        raise HTTPException(status_code=410, detail=f"Página {page} fue eliminada")

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


@router.get("/plans/{plan_id}/render-status")
def get_render_status(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, int]:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    total = plan.page_count or 0
    pdf_path = Path(plan.pdf_path)
    if not pdf_path.exists() or total == 0:
        return {"rendered": 0, "total": total}
    rendered = sum(1 for _ in pdf_path.parent.glob(f"{pdf_path.stem}_p*.png"))
    return {"rendered": min(rendered, total), "total": total}
