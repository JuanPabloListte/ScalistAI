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
from app.models import DetectedElement, Plan, Project, User, Material, Assembly
from app.schemas.detected_element import (
    DetectedElementCreate,
    DetectedElementRead,
    DetectedElementUpdate,
)
from app.schemas.assembly import (
    AssemblyAssignRequest,
    AssemblyBulkAssignRequest,
    AssemblyBulkRemoveRequest,
)
from app.schemas.material import (
    MaterialSummaryItem,
)

from app.schemas.plan import (
    PageRolesUpdate,
    PlanRead,
    ScaleByRatio,
    ScaleCalibration,
    ScaleDirect,
)

from app.services.auto_detect_pipeline import get_ai_status, run_initial_detection
from app.services.ml_detector import get_ml_detector
from app.services.auto_scale import detect_scales
from app.services.dimension_text import extract_dimensions
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
    if project is None or project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    contents = await file.read()
    if len(contents) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="Archivo demasiado grande (máx 50 MB)")

    # DXF: las coordenadas ya están en metros. No se rasteriza on-demand ni se
    # corre IA — el servicio genera el PNG de fondo y los elementos a partir de
    # las capas. Se adjunta como plano al proyecto actual del wizard y se avanza
    # wizard_step a 3 para saltar el paso de roles/IA (que no aplica a un DXF).
    if (file.filename or "").lower().endswith(".dxf"):
        from app.services.dxf_import import build_dxf_plan

        plan, _ = build_dxf_plan(project_id, contents, file.filename or "plano.dxf", db)
        if project.wizard_step < 3:
            project.wizard_step = 3
        db.commit()
        db.refresh(plan)
        return plan

    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos PDF o DXF")

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
    # Avanzamos wizard_step del proyecto a 2 (plano subido) si todavía estaba
    # en el paso anterior. Permite reanudar el wizard en el paso siguiente.
    if project.wizard_step < 2:
        project.wizard_step = 2
    db.commit()
    db.refresh(plan)

    # Pre-warm las páginas en background. La primera request del navegador
    # también puede dispararse antes de que el background termine — en ese
    # caso el endpoint /raster cae al fallback síncrono y renderiza la página
    # individual que se pidió.
    background_tasks.add_task(prewarm_plan_pages, plan.id)
    # NOTA: el pipeline de IA NO se dispara acá. Se dispara en
    # PATCH /plans/{id}/page-roles cuando el usuario asigna explícitamente qué
    # páginas usar para qué (muros / aberturas / recintos). Antes, correr todo
    # sobre todas las páginas "recomendadas" producía detecciones imprecisas
    # porque cada tipo de plano sirve para una cosa distinta.

    return plan


@router.get("/projects/{project_id}/plans", response_model=list[PlanRead])
def list_plans(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Plan]:
    project = db.get(Project, project_id)
    if project is None or project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    stmt = select(Plan).where(Plan.project_id == project_id).order_by(Plan.created_at.desc())
    return list(db.scalars(stmt).all())


@router.get("/plans/training-stats")
def get_training_stats(
    user: User = Depends(get_current_user),
) -> dict:
    """Devuelve estadísticas del corpus de variaciones sintéticas acumulado.

    Útil para saber cuándo conviene re-entrenar (umbral típico: 500+ samples).

    Recorre `storage/synthetic/` contando archivos `image.png` y resumiendo
    los manifests de cada batch. No filtra por usuario — los snapshots son
    parte del corpus global que entrena UN modelo compartido.
    """
    import json as _json

    base = Path(settings.STORAGE_DIR) / "synthetic"
    total_samples = 0
    total_batches = 0
    plans_contributing: set[int] = set()
    projects_contributing: set[int] = set()
    latest_snapshot: str | None = None

    if base.exists():
        for manifest_path in base.rglob("_manifest.json"):
            total_batches += 1
            try:
                m = _json.loads(manifest_path.read_text())
            except Exception:  # noqa: BLE001
                continue
            total_samples += int(m.get("num_variations", 0))
            if (pid := m.get("plan_id")) is not None:
                plans_contributing.add(pid)
            if (proj_id := m.get("project_id")) is not None:
                projects_contributing.add(proj_id)
            snap = m.get("snapshot_at")
            if snap and (latest_snapshot is None or snap > latest_snapshot):
                latest_snapshot = snap

    return {
        "total_samples": total_samples,
        "total_batches": total_batches,
        "plans_contributing": len(plans_contributing),
        "projects_contributing": len(projects_contributing),
        "latest_snapshot_at": latest_snapshot,
        "ready_to_train": total_samples >= 200,
        "recommended_min_samples": 200,
    }


@router.get("/plans/ml-status")
def get_ml_model_status(
    user: User = Depends(get_current_user),
) -> dict:
    """Devuelve si el modelo ML (CubiCasa5K) está cargado y disponible.

    Útil para el frontend: si `available=False`, mostrar un banner "modelo
    ML no instalado, usando detección clásica". El detalle (`model_info`)
    sirve para debugging desde la UI de admin.
    """
    detector = get_ml_detector()
    info = detector.model_info()
    return {
        "available": detector.is_available(),
        **info,
    }


@router.get("/plans/{plan_id}", response_model=PlanRead)
def get_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Plan:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    return plan


@router.get("/plans/{plan_id}/recommend-pages")
def get_recommended_pages(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Escanea localmente el texto del PDF y devuelve recomendaciones de paginas."""
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    
    pdf_path = Path(plan.pdf_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF original no disponible")
    
    try:
        return recommend_pages(pdf_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Error analizando PDF: {exc}") from exc



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


@router.post("/plans/{plan_id}/scale", response_model=PlanRead)
def calibrate_scale(
    plan_id: int,
    payload: ScaleCalibration,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Plan:
    """Calibra la escala de UNA página manualmente y la guarda en page_scales[page]."""
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
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


@router.post("/plans/{plan_id}/scale-ratio", response_model=PlanRead)
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


@router.delete("/plans/{plan_id}/scale/{page}", response_model=PlanRead)
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
    if plan is None or plan.project.organization_id != user.organization_id:
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
    if plan is None or plan.project.organization_id != user.organization_id:
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
    """Analiza las paginas del PDF y devuelve las recomendaciones de paginas para calzar muros/recintos.

    Aplica los overrides manuales del usuario (plan.page_overrides) por encima
    del resultado del algoritmo: "recommended" fuerza la pagina como recomendada,
    "rejected" la descarta sin importar el score.
    """
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    pdf_path = Path(plan.pdf_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF original no disponible")

    try:
        recs = recommend_pages(pdf_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"Error analizando el PDF para recomendar paginas: {exc}"
        ) from exc

    overrides = plan.page_overrides or {}
    for rec in recs:
        page_key = str(rec["page"])
        override = overrides.get(page_key)
        if override == "recommended":
            rec["recommended"] = True
            rec["score"] = 1000
            rec["reason"] = "Marcada manualmente como planta"
            rec["override"] = "recommended"
        elif override == "rejected":
            rec["recommended"] = False
            rec["score"] = -1000
            rec["reason"] = "Marcada manualmente como NO planta"
            rec["override"] = "rejected"
        else:
            rec["override"] = None
    return recs


@router.post("/plans/{plan_id}/page-override", response_model=PlanRead)
def set_page_override(
    plan_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Plan:
    """Setea o quita el override manual para una pagina.

    Body: { "page": <int>, "override": "recommended" | "rejected" | null }
    Cuando override es null, se elimina el override y la pagina vuelve a la
    decision del algoritmo.
    """
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    try:
        page = int(payload["page"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Falta 'page' (int)")

    override = payload.get("override")
    if override not in (None, "recommended", "rejected"):
        raise HTTPException(
            status_code=400,
            detail="'override' debe ser 'recommended', 'rejected' o null",
        )

    if plan.page_count and (page < 1 or page > plan.page_count):
        raise HTTPException(status_code=400, detail="Pagina fuera de rango")

    overrides = dict(plan.page_overrides or {})
    page_key = str(page)
    if override is None:
        overrides.pop(page_key, None)
    else:
        overrides[page_key] = override
    plan.page_overrides = overrides or None
    flag_modified(plan, "page_overrides")
    db.commit()
    db.refresh(plan)
    return plan


@router.patch("/plans/{plan_id}/page-roles", response_model=PlanRead)
def set_page_roles(
    plan_id: int,
    payload: PageRolesUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Plan:
    """Guarda el mapeo página → roles para la detección de IA y dispara el
    pipeline en background. Cada detector corre **sólo** sobre las páginas
    asignadas a su rol — páginas sin rol no se procesan.

    Body:
    ```json
    { "page_roles": { "1": ["walls"], "3": ["openings", "rooms"] } }
    ```
    Roles válidos: "walls", "openings", "rooms". El frontend valida que las
    páginas sean 1-indexed válidas para el `page_count` del plan.
    """
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    # Limpieza: descartamos entradas con lista vacía y validamos rango
    cleaned: dict[str, list[str]] = {}
    max_page = plan.page_count or 0
    for raw_page, roles in payload.page_roles.items():
        try:
            page_num = int(raw_page)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400, detail=f"Página inválida: {raw_page!r}"
            )
        if max_page and (page_num < 1 or page_num > max_page):
            raise HTTPException(
                status_code=400,
                detail=f"Página {page_num} fuera de rango (1..{max_page})",
            )
        # Deduplicamos manteniendo orden
        unique = list(dict.fromkeys(roles))
        if unique:
            cleaned[str(page_num)] = unique

    plan.page_roles = cleaned or None
    flag_modified(plan, "page_roles")

    # Avanzamos wizard_step del proyecto a 3 (páginas asignadas).
    project = plan.project
    if project and project.wizard_step < 3:
        project.wizard_step = 3

    db.commit()
    db.refresh(plan)

    # Dispara el pipeline solo si hay al menos una página con algún rol y no se omitió la IA.
    if cleaned and not payload.skip_ai_detection:
        background_tasks.add_task(run_initial_detection, plan.id)

    return plan


@router.post("/plans/{plan_id}/bulk-scale-ratio", response_model=PlanRead)
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
    """Elimina físicamente una página del PDF original y migra todos los datos."""
    import fitz
    
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    if page < 1 or (plan.page_count and page > plan.page_count):
        raise HTTPException(status_code=400, detail="Número de página inválido")

    pdf_path = Path(plan.pdf_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF original no encontrado")

    # 1. Borrar elementos detectados o dibujados en la página objetivo
    db.query(DetectedElement).filter(
        DetectedElement.plan_id == plan_id,
        DetectedElement.page == page
    ).delete(synchronize_session=False)

    # 2. Modificar el PDF físicamente
    try:
        doc = fitz.open(pdf_path)
        if doc.page_count > 1:
            doc.delete_page(page - 1)
            # Guardamos temporalmente y reemplazamos
            tmp_path = pdf_path.with_suffix(".tmp.pdf")
            doc.save(tmp_path)
            doc.close()
            tmp_path.replace(pdf_path)
        else:
            doc.close()
            raise HTTPException(status_code=400, detail="No puedes eliminar la única página del documento")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error modificando PDF: {exc}") from exc

    # 3. Migrar elementos de páginas posteriores (restar 1 al número de página)
    elements_to_shift = db.query(DetectedElement).filter(
        DetectedElement.plan_id == plan_id,
        DetectedElement.page > page
    ).all()
    for el in elements_to_shift:
        el.page -= 1

    # 4. Actualizar diccionario de escalas
    if plan.page_scales:
        new_scales = {}
        for p_str, scale_val in plan.page_scales.items():
            p_num = int(p_str)
            if p_num < page:
                new_scales[str(p_num)] = scale_val
            elif p_num > page:
                new_scales[str(p_num - 1)] = scale_val
        plan.page_scales = new_scales
        flag_modified(plan, "page_scales")

    # 5. Actualizar el contador total y borrar el historial de ocultas
    plan.page_count -= 1
    plan.deleted_pages = []
    flag_modified(plan, "deleted_pages")

    # 6. Limpieza de imágenes cacheadas
    try:
        # Borrar caché de la página actual
        raster_file = _page_raster_path(pdf_path, page)
        raster_file.unlink(missing_ok=True)
        enhanced_file = raster_file.parent / f"{raster_file.stem}_enhanced{raster_file.suffix}"
        enhanced_file.unlink(missing_ok=True)

        # Renombrar cachés de las páginas siguientes para que coincidan con la nueva numeración
        for p in range(page + 1, plan.page_count + 2):
            old_raster = _page_raster_path(pdf_path, p)
            new_raster = _page_raster_path(pdf_path, p - 1)
            if old_raster.exists():
                old_raster.rename(new_raster)
            
            old_enh = old_raster.parent / f"{old_raster.stem}_enhanced{old_raster.suffix}"
            new_enh = new_raster.parent / f"{new_raster.stem}_enhanced{new_raster.suffix}"
            if old_enh.exists():
                old_enh.rename(new_enh)
    except Exception:
        pass

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
    if plan is None or plan.project.organization_id != user.organization_id:
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


def _ml_page_candidates(plan: Plan, page: int, kind: str) -> list[dict]:
    """Corre inferencia ML sobre una página y devuelve los candidatos del tipo
    pedido (`walls`/`rooms`/`openings`/`beams`/`columns`/`roofs`).

    Detección 100% ML: si el modelo no está disponible devuelve [] (el editor
    no muestra candidatos y el usuario dibuja a mano). No persiste nada.
    """
    detector = get_ml_detector()
    if not detector.is_available():
        return []

    # DXF: la geometría ya viene importada de las capas, no hay PDF que
    # rasterizar para correr inferencia ML.
    if (plan.scale_source == "dxf") or not str(plan.pdf_path).lower().endswith(".pdf"):
        return []

    import fitz
    import numpy as np

    pdf_path = Path(plan.pdf_path)
    scales = plan.page_scales or {}
    px_per_m = scales.get(str(page))
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


@router.get("/plans/{plan_id}/detect-openings")
def detect_openings_endpoint(
    plan_id: int,
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Devuelve candidatos de aberturas detectados por el modelo ML en la página.

    No crea elementos en la base de datos — solo propone. El frontend muestra
    los candidatos como markers y el usuario decide cuáles aceptar.
    """
    plan = _detect_endpoint_guard(db.get(Plan, plan_id), page, user)
    try:
        return _ml_page_candidates(plan, page, "openings")
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
    """Devuelve candidatos de muros detectados por el modelo ML en la página."""
    plan = _detect_endpoint_guard(db.get(Plan, plan_id), page, user)
    try:
        return _ml_page_candidates(plan, page, "walls")
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
    """Devuelve candidatos de recintos detectados por el modelo ML en la página."""
    plan = _detect_endpoint_guard(db.get(Plan, plan_id), page, user)
    try:
        return _ml_page_candidates(plan, page, "rooms")
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
    if plan is None or plan.project.organization_id != user.organization_id:
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
    if plan is None or plan.project.organization_id != user.organization_id:
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


@router.post("/plans/{plan_id}/generate-synthetic")
def generate_synthetic_dataset(
    plan_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Genera N variaciones sintéticas de una página a partir de los elementos
    confirmados. Usado para construir el dataset propio de fine-tuning sin
    depender de datasets externos restrictivos.

    Body:
    ```json
    { "page": 1, "num_variations": 50 }
    ```

    Salida persistida en `storage/synthetic/plan_<id>/page_<N>/var_<NNN>/`.
    """
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    try:
        page = int(payload.get("page", 1))
        num_variations = int(payload.get("num_variations", 50))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail="page y num_variations deben ser enteros",
        )

    if num_variations < 1 or num_variations > 500:
        raise HTTPException(
            status_code=400,
            detail="num_variations debe estar entre 1 y 500",
        )

    from app.services.synthetic_generator import generate_synthetic_variations

    try:
        metas = generate_synthetic_variations(plan_id, page, num_variations)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail=f"Error generando variaciones: {exc}",
        ) from exc

    return {
        "plan_id": plan_id,
        "page": page,
        "variations_generated": len(metas),
        # Devolvemos las primeras 5 como muestra; el resto está en disco.
        "sample": metas[:5],
    }





@router.get("/plans/{plan_id}/ai-status")
def get_ai_pipeline_status(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Devuelve el progreso del pipeline de IA: scales, walls, rooms, openings,
    columns, beams, roofs y ml.

    El frontend lo polea para mostrar un banner mientras la deteccion automatica
    se ejecuta en background despues del upload del PDF.
    """
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    return get_ai_status(plan_id)


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

    # Si la pagina fue marcada como eliminada, NO regenerar el cache.
    # Devolvemos 410 Gone para que el frontend salte a la siguiente pagina activa.
    if plan.deleted_pages and page in plan.deleted_pages:
        raise HTTPException(
            status_code=410,
            detail=f"Página {page} fue eliminada",
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
    if plan is None or plan.project.organization_id != user.organization_id:
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
    if plan is None or plan.project.organization_id != user.organization_id:
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
    if plan is None or plan.project.organization_id != user.organization_id:
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
    if plan is None or plan.project.organization_id != user.organization_id:
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
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    element = db.get(DetectedElement, element_id)
    if element is None or element.plan_id != plan_id:
        raise HTTPException(status_code=404, detail="Elemento no encontrado")

    db.delete(element)
    db.commit()







def _opening_overlaps_wall(
    opening: DetectedElement, wall: DetectedElement, scale_px_per_m: float
) -> bool:
    """Decide si una abertura cae sobre un muro proyectando el centro de la
    abertura sobre el segmento del muro.

    Devuelve True si:
      - la proyección cae dentro del segmento (t ∈ [0, 1]), y
      - la distancia perpendicular es ≤ 0.5 m (tolerancia para muros gruesos
        o pequeños desfasajes de dibujo).

    Funciona indistintamente con muros completos (manual) y muros ya partidos
    por el detector clásico: en este último caso la proyección del centro de
    la abertura cae *fuera* del segmento (t<0 o t>1), así que no hay
    doble-descuento.
    """
    o_pts = opening.geometry.get("points") if opening.geometry else None
    w_pts = wall.geometry.get("points") if wall.geometry else None
    if not o_pts or len(o_pts) < 4 or not w_pts or len(w_pts) < 4:
        return False
    ox = (float(o_pts[0]) + float(o_pts[2])) / 2.0
    oy = (float(o_pts[1]) + float(o_pts[3])) / 2.0
    x1, y1, x2, y2 = float(w_pts[0]), float(w_pts[1]), float(w_pts[2]), float(w_pts[3])
    dx = x2 - x1
    dy = y2 - y1
    l2 = dx * dx + dy * dy
    if l2 <= 0:
        return False
    t = ((ox - x1) * dx + (oy - y1) * dy) / l2
    if t < 0.0 or t > 1.0:
        return False
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    dist_px = math.hypot(ox - proj_x, oy - proj_y)
    max_dist_px = 0.5 * scale_px_per_m  # 0.5 m de tolerancia perpendicular
    return dist_px <= max_dist_px


# Subtipos de abertura que también restan al PERÍMETRO del muro (zócalo, etc).
# Las ventanas solo restan al área. Debe matchear `OPENING_SUBTYPES` del front
# (plan-viewer-inner.tsx).
_OPENING_SUBTYPES_SUBTRACT_PERIMETER = {"door", "sliding-door"}


def _get_materials_summary_data(plan_id: int, page: int | None, db: Session) -> list[dict]:
    plan = db.get(Plan, plan_id)
    page_scales: dict[str, float] = (plan.page_scales or {}) if plan else {}

    stmt = select(DetectedElement).where(DetectedElement.plan_id == plan_id)
    if page is not None:
        stmt = stmt.where(DetectedElement.page == page)
    elements = list(db.scalars(stmt).all())

    # Pre-agrupo aberturas por página para iterar O(W·O_page) en lugar de O(W·O_total).
    openings_by_page: dict[int, list[DetectedElement]] = {}
    for el in elements:
        if el.type == "opening":
            openings_by_page.setdefault(el.page, []).append(el)

    summary_dict = {}

    for element in elements:
        for assembly in element.assemblies:
            for am in assembly.assembly_materials:
                material = am.material
                qty = 0.0
                if assembly.applies_to == "wall" and element.type == "wall":
                    length = element.length_m or 0.0
                    height = element.height_m or 2.8
                    area = length * height
                    # Restar aberturas sobre este muro: el área (length × height)
                    # del muro queda descontada por (width × height) de cada
                    # abertura que cae sobre el segmento.
                    scale_px_per_m = page_scales.get(str(element.page))
                    if scale_px_per_m and scale_px_per_m > 0:
                        for op in openings_by_page.get(element.page, []):
                            if _opening_overlaps_wall(op, element, scale_px_per_m):
                                op_w = op.length_m or 0.0
                                op_h = op.height_m or 2.1
                                area -= op_w * op_h
                        if area < 0.0:
                            area = 0.0
                    qty = area * am.consumption * (1.0 + am.waste_factor)
                elif element.type == "room":
                    if assembly.applies_to == "room_floor":
                        area = element.area_m2 or 0.0
                        qty = area * am.consumption * (1.0 + am.waste_factor)
                    elif assembly.applies_to == "room_wall":
                        perimeter = element.length_m or 0.0
                        height = element.height_m or 2.8
                        area = perimeter * height
                        qty = area * am.consumption * (1.0 + am.waste_factor)
                    elif assembly.applies_to == "room_perimeter":
                        perimeter = element.length_m or 0.0
                        qty = perimeter * am.consumption * (1.0 + am.waste_factor)
                elif element.type == "opening":
                    if assembly.applies_to == "opening":
                        length = element.length_m or 0.0
                        height = element.height_m or 2.1
                        area = length * height
                        qty = area * am.consumption * (1.0 + am.waste_factor)
                    elif assembly.applies_to == "opening_perimeter":
                        length = element.length_m or 0.0
                        qty = length * am.consumption * (1.0 + am.waste_factor)
                elif element.type == "beam" and assembly.applies_to == "beam":
                    length = element.length_m or 0.0
                    qty = length * am.consumption * (1.0 + am.waste_factor)
                elif element.type == "roof" and assembly.applies_to == "roof":
                    area = element.area_m2 or 0.0
                    qty = area * am.consumption * (1.0 + am.waste_factor)
                elif element.type == "column" and assembly.applies_to == "column":
                    area = element.area_m2 or 0.0
                    qty = area * am.consumption * (1.0 + am.waste_factor)

                if qty > 0.0:
                    if material.id not in summary_dict:
                        summary_dict[material.id] = {
                            "material": material,
                            "quantity": 0.0,
                            "unit": material.unit,
                            "unit_price": material.unit_price,
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
    if plan is None or plan.project.organization_id != user.organization_id:
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
    if plan is None or plan.project.organization_id != user.organization_id:
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
    if plan is None or plan.project.organization_id != user.organization_id:
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


@router.post("/admin/train-now")
def trigger_training(
    epochs: int = 10,
    user: User = Depends(get_current_user),
) -> dict:
    """Dispara el re-entrenamiento (inicial o fine-tuning) del modelo ML en background."""
    if user.role != "admin" and user.email != "admin@gmail.com":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operación permitida únicamente a administradores.",
        )
    from app.services.training_manager import get_training_manager
    manager = get_training_manager()
    res = manager.start_training(epochs=epochs)
    if not res["success"]:
        raise HTTPException(status_code=400, detail=res["message"])
    return res


@router.post("/admin/gen-procedural")
def trigger_procedural_generation(
    count: int = 3000,
    user: User = Depends(get_current_user),
) -> dict:
    """Genera el dataset PROCEDURAL en background (planos inventados por código).

    Va SOLO al train del próximo reentrenamiento (nunca al holdout). Reusa el
    mismo streaming de logs/progreso que el entrenamiento (GET /admin/train-status).
    """
    if user.role != "admin" and user.email != "admin@gmail.com":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operación permitida únicamente a administradores.",
        )
    if count < 100 or count > 50000:
        raise HTTPException(status_code=400, detail="count debe estar entre 100 y 50000.")
    from app.services.training_manager import get_training_manager
    manager = get_training_manager()
    res = manager.start_procedural(count=count)
    if not res["success"]:
        raise HTTPException(status_code=400, detail=res["message"])
    return res


@router.get("/admin/train-status")
def get_training_status(
    user: User = Depends(get_current_user),
) -> dict:
    """Devuelve el estado de progreso y los logs del entrenamiento en background."""
    if user.role != "admin" and user.email != "admin@gmail.com":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operación permitida únicamente a administradores.",
        )
    from app.services.training_manager import get_training_manager
    manager = get_training_manager()
    status_data = manager.get_status()
    logs = manager.get_logs(limit=200)
    return {
        "status": status_data,
        "logs": logs,
    }




