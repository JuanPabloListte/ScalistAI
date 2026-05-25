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
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import DetectedElement, Plan, Project, User, Material
from app.schemas.detected_element import (
    DetectedElementCreate,
    DetectedElementRead,
    DetectedElementUpdate,
)
from app.schemas.material import (
    MaterialAssignRequest,
    MaterialRead,
    MaterialSummaryItem,
    MaterialPriceUpdateRequest,
    MaterialBulkAssignRequest,
    MaterialBulkRemoveRequest,
)

from app.schemas.plan import PlanRead, ScaleByRatio, ScaleCalibration, ScaleDirect

from app.services.auto_scale import detect_scales
from app.services.dimension_text import extract_dimensions
from app.services.opening_detection import detect_opening_labels
from app.services.wall_room_detection import detect_walls, detect_rooms
from app.services.pdf import page_count, rasterize, recommend_pages
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


@router.post("/plans/{plan_id}/scale-direct", response_model=PlanRead)
def set_scale_direct(
    plan_id: int,
    payload: ScaleDirect,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Plan:
    """Setea la escala de una página a partir de un px_per_m ya calculado.

    Lo usa la calibración multi-referencia del visor: el frontend marca varias
    cotas, calcula la mediana de px_per_m y la manda acá. El backend no necesita
    saber cuántas referencias había ni dónde estaban.
    """
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
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


@router.get("/plans/{plan_id}/recommend-pages")
def recommend_plan_pages(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Analiza las paginas del PDF y devuelve las recomendaciones de paginas para calzar muros/recintos."""
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    pdf_path = Path(plan.pdf_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF original no disponible")

    try:
        return recommend_pages(pdf_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"Error analizando el PDF para recomendar paginas: {exc}"
        ) from exc


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


@router.post("/plans/{plan_id}/delete-page/{page}", response_model=PlanRead)
def delete_page(
    plan_id: int,
    page: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Plan:
    """Marca una página como eliminada, borrando sus elementos y caché de imagen."""
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    if page < 1 or (plan.page_count and page > plan.page_count):
        raise HTTPException(status_code=400, detail="Número de página inválido")

    deleted = list(plan.deleted_pages or [])
    if page not in deleted:
        deleted.append(page)
        plan.deleted_pages = deleted
        flag_modified(plan, "deleted_pages")

    # Borrar elementos detectados o dibujados en esta página
    db.query(DetectedElement).filter(
        DetectedElement.plan_id == plan_id,
        DetectedElement.page == page
    ).delete(synchronize_session=False)

    # Eliminar imagen rasterizada cacheada para ahorrar espacio
    try:
        pdf_path = Path(plan.pdf_path)
        raster_file = _page_raster_path(pdf_path, page)
        raster_file.unlink(missing_ok=True)
        enhanced_file = raster_file.parent / f"{raster_file.stem}_enhanced{raster_file.suffix}"
        enhanced_file.unlink(missing_ok=True)
    except Exception:
        pass

    db.commit()
    db.refresh(plan)
    return plan


@router.post("/plans/{plan_id}/restore-page/{page}", response_model=PlanRead)
def restore_page(
    plan_id: int,
    page: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Plan:
    """Restaura una página eliminada previamente."""
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    if page < 1 or (plan.page_count and page > plan.page_count):
        raise HTTPException(status_code=400, detail="Número de página inválido")

    deleted = list(plan.deleted_pages or [])
    if page in deleted:
        deleted.remove(page)
        plan.deleted_pages = deleted
        flag_modified(plan, "deleted_pages")

    db.commit()
    db.refresh(plan)
    return plan


@router.get("/plans/{plan_id}/dimensions")
def list_page_dimensions(
    plan_id: int,
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Devuelve las cotas decimales detectadas en el texto vectorial del PDF
    de la página indicada, en coordenadas del raster.

    Sirve para asistir la calibración manual: el visor encuentra la cota más
    cercana al segmento que el usuario marca y pre-llena el modal con su valor.
    """
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    pdf_path = Path(plan.pdf_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF original no disponible")
    if plan.page_count and (page < 1 or page > plan.page_count):
        raise HTTPException(status_code=400, detail="Página fuera de rango")
    try:
        return extract_dimensions(pdf_path, page - 1, plan.dpi or RASTER_DPI)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"Error leyendo cotas: {exc}"
        ) from exc


@router.get("/plans/{plan_id}/detect-openings")
def detect_openings_endpoint(
    plan_id: int,
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Devuelve candidatos de aberturas detectados por sus labels en el PDF
    (P1, V1, PV3, PF1, etc.) para la página indicada.

    No crea elementos en la base de datos — solo propone. El frontend muestra
    los candidatos como markers y el usuario decide cuáles aceptar.
    """
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    pdf_path = Path(plan.pdf_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF original no disponible")
    if plan.page_count and (page < 1 or page > plan.page_count):
        raise HTTPException(status_code=400, detail="Página fuera de rango")
    scales = plan.page_scales or {}
    px_per_m = scales.get(str(page))
    try:
        return detect_opening_labels(
            pdf_path, page - 1, plan.dpi or RASTER_DPI, px_per_m
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"Error detectando aberturas: {exc}"
        ) from exc


@router.get("/plans/{plan_id}/detect-walls")
def detect_walls_endpoint(
    plan_id: int,
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Devuelve candidatos de muros detectados por la IA en la página indicada."""
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    pdf_path = Path(plan.pdf_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF original no disponible")
    if plan.page_count and (page < 1 or page > plan.page_count):
        raise HTTPException(status_code=400, detail="Página fuera de rango")

    scales = plan.page_scales or {}
    px_per_m = scales.get(str(page))

    try:
        return detect_walls(
            pdf_path, page - 1, plan.dpi or RASTER_DPI, px_per_m
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"Error detectando muros: {exc}"
        ) from exc


@router.get("/plans/{plan_id}/detect-rooms")
def detect_rooms_endpoint(
    plan_id: int,
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Devuelve candidatos de recintos detectados por la IA en la página indicada."""
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    pdf_path = Path(plan.pdf_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF original no disponible")
    if plan.page_count and (page < 1 or page > plan.page_count):
        raise HTTPException(status_code=400, detail="Página fuera de rango")

    scales = plan.page_scales or {}
    px_per_m = scales.get(str(page))

    try:
        return detect_rooms(
            pdf_path, page - 1, plan.dpi or RASTER_DPI, px_per_m
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"Error detectando recintos: {exc}"
        ) from exc



@router.post(
    "/plans/{plan_id}/elements-bulk",
    response_model=list[DetectedElementRead],
    status_code=status.HTTP_201_CREATED,
)
def create_elements_bulk(
    plan_id: int,
    payload: list[dict],
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DetectedElement]:
    """Crea N elementos (muros, recintos o aberturas) a partir de candidatos aceptados."""
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    created: list[DetectedElement] = []
    for item in payload:
        try:
            page = int(item["page"])
            el_type = str(item["type"])
            geometry = dict(item["geometry"])
            length_m = float(item["length_m"]) if item.get("length_m") is not None else None
            area_m2 = float(item["area_m2"]) if item.get("area_m2") is not None else None
            height_m = float(item.get("height_m") or 2.8)
        except (KeyError, TypeError, ValueError):
            continue

        element = DetectedElement(
            plan_id=plan_id,
            page=page,
            type=el_type,
            geometry=geometry,
            length_m=length_m,
            area_m2=area_m2,
            height_m=height_m,
            source="ai",
        )
        db.add(element)
        created.append(element)

    if created:
        db.commit()
        for el in created:
            db.refresh(el)

    return created


@router.post(
    "/plans/{plan_id}/openings-bulk",
    response_model=list[DetectedElementRead],
    status_code=status.HTTP_201_CREATED,
)
def create_openings_bulk(
    plan_id: int,
    payload: list[dict],
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DetectedElement]:
    """Crea N elementos type="opening" a partir de candidatos aceptados.

    Cada item del payload debe traer:
      - page (int)
      - cx, cy (float)        : centro en píxeles del raster
      - default_width_m (float): ancho a aplicar
      - label (str)           : etiqueta P1/V1/etc.
      - subtype (str)         : door/window/sliding_door/fixed_window

    Por simplicidad el segmento se traza HORIZONTAL centrado en (cx, cy):
    `p1 = (cx - half_w, cy)`, `p2 = (cx + half_w, cy)` en píxeles, donde
    `half_w = (default_width_m / 2) * px_per_m`. El usuario puede luego
    rotar/ajustar arrastrando los vértices.
    """
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    scales = plan.page_scales or {}
    created: list[DetectedElement] = []
    existing_count_per_page: dict[int, int] = {}

    for item in payload:
        try:
            page = int(item["page"])
            cx = float(item["cx"])
            cy = float(item["cy"])
            width_m = float(item.get("default_width_m") or 0.8)
            label = str(item.get("label") or "")
            subtype = str(item.get("subtype") or "door")
        except (KeyError, TypeError, ValueError):
            continue

        px_per_m = scales.get(str(page))
        if not px_per_m:
            continue  # sin escala no podemos posicionar; skip

        orientation = str(item.get("orientation") or "h").lower()
        half_px = (width_m / 2.0) * px_per_m
        if orientation == "v":
            p1 = (cx, cy - half_px)
            p2 = (cx, cy + half_px)
        else:
            p1 = (cx - half_px, cy)
            p2 = (cx + half_px, cy)

        if page not in existing_count_per_page:
            existing_count_per_page[page] = (
                db.query(DetectedElement)
                .filter(
                    DetectedElement.plan_id == plan_id,
                    DetectedElement.page == page,
                    DetectedElement.type == "opening",
                )
                .count()
            )
        existing_count_per_page[page] += 1
        display_label = label or f"Abertura {existing_count_per_page[page]}"

        element = DetectedElement(
            plan_id=plan_id,
            page=page,
            type="opening",
            geometry={
                "points": [p1[0], p1[1], p2[0], p2[1]],
                "label": display_label,
                "subtype": subtype,
            },
            length_m=width_m,
            height_m=2.1,
            source="ai",
        )
        db.add(element)
        created.append(element)

    if created:
        db.commit()
        for el in created:
            db.refresh(el)

    return created


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


@router.post(
    "/plans/{plan_id}/elements",
    response_model=DetectedElementRead,
    status_code=status.HTTP_201_CREATED,
)
def create_element(
    plan_id: int,
    payload: DetectedElementCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DetectedElement:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    element = DetectedElement(
        plan_id=plan_id,
        page=payload.page,
        type=payload.type,
        geometry=payload.geometry,
        length_m=payload.length_m,
        area_m2=payload.area_m2,
        height_m=payload.height_m,
        source=payload.source,
    )
    db.add(element)
    db.commit()
    db.refresh(element)
    return element


@router.get("/plans/{plan_id}/elements", response_model=list[DetectedElementRead])
def list_elements(
    plan_id: int,
    page: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DetectedElement]:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    stmt = select(DetectedElement).where(DetectedElement.plan_id == plan_id)
    if page is not None:
        stmt = stmt.where(DetectedElement.page == page)

    stmt = stmt.order_by(DetectedElement.created_at.asc())
    return list(db.scalars(stmt).all())


@router.post("/plans/{plan_id}/elements/bulk/delete", status_code=status.HTTP_204_NO_CONTENT)
def bulk_delete_elements(
    plan_id: int,
    payload: list[int],
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    if not payload:
        return

    db.query(DetectedElement).filter(
        DetectedElement.plan_id == plan_id,
        DetectedElement.id.in_(payload)
    ).delete(synchronize_session=False)
    db.commit()


@router.patch("/plans/{plan_id}/elements/{element_id}", response_model=DetectedElementRead)
def update_element(
    plan_id: int,
    element_id: int,
    payload: DetectedElementUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DetectedElement:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    element = db.get(DetectedElement, element_id)
    if element is None or element.plan_id != plan_id:
        raise HTTPException(status_code=404, detail="Elemento no encontrado")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(element, field, value)

    db.commit()
    db.refresh(element)
    return element


@router.delete("/plans/{plan_id}/elements/{element_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_element(
    plan_id: int,
    element_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    element = db.get(DetectedElement, element_id)
    if element is None or element.plan_id != plan_id:
        raise HTTPException(status_code=404, detail="Elemento no encontrado")

    db.delete(element)
    db.commit()



@router.post(
    "/plans/{plan_id}/elements/bulk/materials",
    response_model=list[DetectedElementRead],
)
def bulk_assign_material(
    plan_id: int,
    payload: MaterialBulkAssignRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DetectedElement]:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    material = db.get(Material, payload.material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="Material no encontrado")

    updated_elements = []
    for el_id in payload.element_ids:
        element = db.get(DetectedElement, el_id)
        if element is None or element.plan_id != plan_id:
            continue
        if material not in element.materials:
            element.materials.append(material)
            updated_elements.append(element)

    if updated_elements:
        db.commit()
        for element in updated_elements:
            db.refresh(element)

    return updated_elements


@router.post(
    "/plans/{plan_id}/elements/bulk/materials/remove",
    response_model=list[DetectedElementRead],
)
def bulk_remove_material(
    plan_id: int,
    payload: MaterialBulkRemoveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DetectedElement]:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    material = db.get(Material, payload.material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="Material no encontrado")

    updated_elements = []
    for el_id in payload.element_ids:
        element = db.get(DetectedElement, el_id)
        if element is None or element.plan_id != plan_id:
            continue
        if material in element.materials:
            element.materials.remove(material)
            updated_elements.append(element)

    if updated_elements:
        db.commit()
        for element in updated_elements:
            db.refresh(element)

    return updated_elements



@router.post(
    "/plans/{plan_id}/elements/{element_id}/materials",
    response_model=DetectedElementRead,
)
def assign_material(
    plan_id: int,
    element_id: int,
    payload: MaterialAssignRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DetectedElement:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    element = db.get(DetectedElement, element_id)
    if element is None or element.plan_id != plan_id:
        raise HTTPException(status_code=404, detail="Elemento no encontrado")

    material = db.get(Material, payload.material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="Material no encontrado")

    if material not in element.materials:
        element.materials.append(material)
        db.commit()
        db.refresh(element)

    return element


@router.delete(
    "/plans/{plan_id}/elements/{element_id}/materials/{material_id}",
    response_model=DetectedElementRead,
)
def remove_material(
    plan_id: int,
    element_id: int,
    material_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DetectedElement:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    element = db.get(DetectedElement, element_id)
    if element is None or element.plan_id != plan_id:
        raise HTTPException(status_code=404, detail="Elemento no encontrado")

    material = db.get(Material, material_id)
    if material is None:
        raise HTTPException(status_code=404, detail="Material no encontrado")

    if material in element.materials:
        element.materials.remove(material)
        db.commit()
        db.refresh(element)

    return element





def _get_materials_summary_data(plan_id: int, page: int | None, db: Session) -> list[dict]:
    stmt = select(DetectedElement).where(DetectedElement.plan_id == plan_id)
    if page is not None:
        stmt = stmt.where(DetectedElement.page == page)
    elements = db.scalars(stmt).all()

    summary_dict = {}

    for element in elements:
        for material in element.materials:
            for y in material.yields:
                qty = 0.0
                if y.applies_to == "wall" and element.type == "wall":
                    length = element.length_m or 0.0
                    height = element.height_m or 2.8
                    area = length * height
                    qty = area * y.consumption * (1.0 + y.waste_factor)
                elif element.type == "room":
                    if y.applies_to == "room_floor":
                        area = element.area_m2 or 0.0
                        qty = area * y.consumption * (1.0 + y.waste_factor)
                    elif y.applies_to == "room_wall":
                        perimeter = element.length_m or 0.0
                        height = element.height_m or 2.8
                        area = perimeter * height
                        qty = area * y.consumption * (1.0 + y.waste_factor)
                    elif y.applies_to == "room_perimeter":
                        perimeter = element.length_m or 0.0
                        qty = perimeter * y.consumption * (1.0 + y.waste_factor)
                elif element.type == "opening":
                    if y.applies_to == "opening":
                        length = element.length_m or 0.0
                        height = element.height_m or 2.1
                        area = length * height
                        qty = area * y.consumption * (1.0 + y.waste_factor)
                    elif y.applies_to == "opening_perimeter":
                        length = element.length_m or 0.0
                        qty = length * y.consumption * (1.0 + y.waste_factor)

                if qty > 0.0:
                    if material.id not in summary_dict:
                        summary_dict[material.id] = {
                            "material": material,
                            "quantity": 0.0,
                            "unit": material.unit,
                            "unit_price": y.unit_price,
                        }
                    summary_dict[material.id]["quantity"] += qty

    result = []
    for item in summary_dict.values():
        qty = round(item["quantity"], 2)
        unit_price = item.get("unit_price", 0.0)
        subtotal = round(qty * unit_price, 2)
        result.append({
            "material": item["material"],
            "quantity": qty,
            "unit": item["unit"],
            "unit_price": unit_price,
            "subtotal": subtotal,
        })

    result.sort(key=lambda x: x["material"].name)
    return result


@router.get(
    "/plans/{plan_id}/materials-summary",
    response_model=list[MaterialSummaryItem],
)
def get_materials_summary(
    plan_id: int,
    page: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    return _get_materials_summary_data(plan_id, page, db)


@router.get("/plans/{plan_id}/export/xlsx")
def export_xlsx(
    plan_id: int,
    page: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    summary_items = _get_materials_summary_data(plan_id, page, db)

    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Presupuesto"
    ws.views.sheetView[0].showGridLines = True

    title_font = Font(name="Segoe UI", size=16, bold=True, color="1B365D")
    header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Segoe UI", size=11, color="000000")
    total_font = Font(name="Segoe UI", size=11, bold=True, color="1B365D")

    header_fill = PatternFill(start_color="1B365D", end_color="1B365D", fill_type="solid")
    total_fill = PatternFill(start_color="E9EFF5", end_color="E9EFF5", fill_type="solid")

    thin_border = Border(
        left=Side(style='thin', color='D3D3D3'),
        right=Side(style='thin', color='D3D3D3'),
        top=Side(style='thin', color='D3D3D3'),
        bottom=Side(style='thin', color='D3D3D3')
    )
    total_border = Border(
        top=Side(style='thin', color='1B365D'),
        bottom=Side(style='double', color='1B365D')
    )

    plan_label = plan.project.name if plan.project else plan.original_filename
    ws.merge_cells("A1:E1")
    ws["A1"] = f"Presupuesto de Materiales - {plan_label}"
    ws["A1"].font = title_font
    ws["A1"].alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 40

    headers = ["Material", "Cantidad", "Unidad", "Precio Unitario", "Subtotal"]
    ws.row_dimensions[3].height = 25
    for col_idx, text in enumerate(headers, 1):
        cell = ws.cell(row=3, column=col_idx, value=text)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center" if col_idx > 1 else "left", vertical="center")
        cell.border = thin_border

    current_row = 4
    total_budget = 0.0
    for item in summary_items:
        ws.row_dimensions[current_row].height = 20

        c1 = ws.cell(row=current_row, column=1, value=item["material"].name)
        c1.font = data_font
        c1.alignment = Alignment(horizontal="left", vertical="center")
        c1.border = thin_border

        c2 = ws.cell(row=current_row, column=2, value=item["quantity"])
        c2.font = data_font
        c2.number_format = "#,##0.00"
        c2.alignment = Alignment(horizontal="right", vertical="center")
        c2.border = thin_border

        c3 = ws.cell(row=current_row, column=3, value=item["unit"])
        c3.font = data_font
        c3.alignment = Alignment(horizontal="center", vertical="center")
        c3.border = thin_border

        c4 = ws.cell(row=current_row, column=4, value=item["unit_price"])
        c4.font = data_font
        c4.number_format = "$#,##0.00"
        c4.alignment = Alignment(horizontal="right", vertical="center")
        c4.border = thin_border

        c5 = ws.cell(row=current_row, column=5, value=item["subtotal"])
        c5.font = data_font
        c5.number_format = "$#,##0.00"
        c5.alignment = Alignment(horizontal="right", vertical="center")
        c5.border = thin_border

        total_budget += item["subtotal"]
        current_row += 1

    ws.row_dimensions[current_row].height = 25
    ws.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=4)
    total_label_cell = ws.cell(row=current_row, column=1, value="Total General")
    total_label_cell.font = total_font
    total_label_cell.alignment = Alignment(horizontal="right", vertical="center")
    total_label_cell.fill = total_fill

    for col_idx in range(1, 5):
        ws.cell(row=current_row, column=col_idx).border = total_border
        ws.cell(row=current_row, column=col_idx).fill = total_fill

    total_val_cell = ws.cell(row=current_row, column=5, value=total_budget)
    total_val_cell.font = total_font
    total_val_cell.number_format = "$#,##0.00"
    total_val_cell.alignment = Alignment(horizontal="right", vertical="center")
    total_val_cell.border = total_border
    total_val_cell.fill = total_fill

    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            if cell.row == 1:
                continue
            if cell.value:
                max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    ws.column_dimensions["A"].width = max(ws.column_dimensions["A"].width, 30)

    out = BytesIO()
    wb.save(out)
    out.seek(0)

    filename = f"presupuesto_{plan_label.replace(' ', '_')}.xlsx"
    return StreamingResponse(
        out,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/plans/{plan_id}/export/pdf")
def export_pdf(
    plan_id: int,
    page: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.user_id != user.id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    summary_items = _get_materials_summary_data(plan_id, page, db)

    from io import BytesIO
    from datetime import datetime
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#1B365D"),
        spaceAfter=15,
    )

    subtitle_style = ParagraphStyle(
        "DocSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#666666"),
        spaceAfter=25,
    )

    body_style = ParagraphStyle(
        "TableBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=12,
        textColor=colors.HexColor("#333333"),
    )

    body_bold_style = ParagraphStyle(
        "TableBodyBold",
        parent=body_style,
        fontName="Helvetica-Bold",
    )

    body_right_style = ParagraphStyle(
        "TableBodyRight",
        parent=body_style,
        alignment=2,
    )

    body_right_bold_style = ParagraphStyle(
        "TableBodyRightBold",
        parent=body_style,
        fontName="Helvetica-Bold",
        alignment=2,
    )

    header_style = ParagraphStyle(
        "TableHeader",
        parent=body_bold_style,
        textColor=colors.white,
    )

    header_right_style = ParagraphStyle(
        "TableHeaderRight",
        parent=body_right_bold_style,
        textColor=colors.white,
    )

    story = []

    plan_label = plan.project.name if plan.project else plan.original_filename
    date_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    story.append(Paragraph("Presupuesto de Materiales", title_style))
    page_txt = f" - Página {page}" if page else ""
    story.append(
        Paragraph(
            f"Plano: {plan_label}{page_txt}<br/>Generado el: {date_str}",
            subtitle_style,
        )
    )

    table_data = [
        [
            Paragraph("Material", header_style),
            Paragraph("Cantidad", header_right_style),
            Paragraph("Unidad", header_style),
            Paragraph("Precio Unitario", header_right_style),
            Paragraph("Subtotal", header_right_style),
        ]
    ]

    total_budget = 0.0
    for item in summary_items:
        qty_str = f"{item['quantity']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        price_str = f"${item['unit_price']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        subtotal_str = f"${item['subtotal']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

        table_data.append([
            Paragraph(item["material"].name, body_style),
            Paragraph(qty_str, body_right_style),
            Paragraph(item["unit"], body_style),
            Paragraph(price_str, body_right_style),
            Paragraph(subtotal_str, body_right_style),
        ])
        total_budget += item["subtotal"]

    total_budget_str = f"${total_budget:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    table_data.append([
        Paragraph("Total General", body_right_bold_style),
        "",
        "",
        "",
        Paragraph(total_budget_str, body_right_bold_style),
    ])

    col_widths = [240, 70, 50, 80, 92]
    t = Table(table_data, colWidths=col_widths)

    t_style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B365D")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("GRID", (0, 0), (-1, -2), 0.5, colors.HexColor("#E2E8F0")),
        ("SPAN", (0, -1), (3, -1)),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F8FAFC")),
        ("TOPPADDING", (0, -1), (-1, -1), 10),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 10),
        ("LINEABOVE", (0, -1), (-1, -1), 1.5, colors.HexColor("#1B365D")),
        ("LINEBELOW", (0, -1), (-1, -1), 2, colors.HexColor("#1B365D")),
    ])

    t.setStyle(t_style)
    story.append(t)

    doc.build(story)
    buffer.seek(0)

    filename = f"presupuesto_{plan_label.replace(' ', '_')}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )



