import asyncio
import logging
from pathlib import Path

from app.core.database import SessionLocal
from app.models.plan import Plan
from app.services.pdf import rasterize
from app.services.preprocess import enhance_for_display

logger = logging.getLogger(__name__)


async def prewarm_plan_pages(plan_id: int) -> None:
    """Renderiza en background todas las páginas de un plan que no estén cacheadas.

    Corre como BackgroundTask de FastAPI (después de devolver la respuesta al cliente).
    Usa `asyncio.to_thread` para que el trabajo CPU-bound (PyMuPDF + OpenCV) no
    bloquee el event loop y la API siga sirviendo otras requests mientras tanto.

    Es idempotente: si el archivo PNG ya existe, salta la página.
    """
    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        if plan is None or not plan.page_count:
            return
        pdf_path = Path(plan.pdf_path)
        if not pdf_path.exists():
            return
        dpi = plan.dpi or 300
        total = plan.page_count
        deleted_pages = set(plan.deleted_pages or [])

    for page in range(1, total + 1):
        # No regenerar paginas que el usuario marco como eliminadas — sino el
        # prewarm "revive" su raster despues de un delete-page.
        if page in deleted_pages:
            continue
        cached = pdf_path.with_name(f"{pdf_path.stem}_p{page}.png")
        if cached.exists():
            continue
        try:
            raster_bytes = await asyncio.to_thread(rasterize, pdf_path, page - 1, dpi)
            enhanced = await asyncio.to_thread(enhance_for_display, raster_bytes)
            cached.write_bytes(enhanced)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "prewarm page %s of plan %s failed: %s", page, plan_id, exc
            )
