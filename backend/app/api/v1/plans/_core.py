import uuid
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import DetectedElement, Plan, Project, User
from app.schemas.plan import PlanRead
from app.services.auto_scale import detect_scales
from app.services.pdf import classify_pages, page_count, recommend_pages
from app.services.prewarm import prewarm_plan_pages

from ._common import MAX_IFC_BYTES, MAX_PDF_BYTES, RASTER_DPI, _page_raster_path

router = APIRouter(tags=["plans"])


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
    fname_lower = (file.filename or "").lower()
    is_ifc = fname_lower.endswith(".ifc")
    max_bytes = MAX_IFC_BYTES if is_ifc else MAX_PDF_BYTES
    if len(contents) > max_bytes:
        mb = max_bytes // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"Archivo demasiado grande (máx {mb} MB)")

    # IFC (BIM): modelo exacto, sin páginas ni raster. Salta el visor -> presupuesto.
    if is_ifc:
        from app.services.ifc_import import build_ifc_plan, process_ifc

        plan = build_ifc_plan(project_id, contents, file.filename or "modelo.ifc", db)
        if project.wizard_step < 2:
            project.wizard_step = 2
        db.commit()
        db.refresh(plan)
        background_tasks.add_task(process_ifc, plan.id)
        return plan

    # DXF / DWG: se plotea a PDF vectorial; los elementos salen del mapeo de capas.
    if fname_lower.endswith(".dxf") or fname_lower.endswith(".dwg"):
        from app.services.dxf_import import build_dxf_plan

        ext = ".dwg" if fname_lower.endswith(".dwg") else ".dxf"
        plan, _ = build_dxf_plan(project_id, contents, file.filename or f"plano{ext}", db)
        if project.wizard_step < 2:
            project.wizard_step = 2
        db.commit()
        db.refresh(plan)
        return plan

    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos PDF, DXF o DWG")

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
    if project.wizard_step < 2:
        project.wizard_step = 2
    db.commit()
    db.refresh(plan)

    background_tasks.add_task(prewarm_plan_pages, plan.id)
    # Si el PDF es vectorial con capas CAD (muros/aberturas/etc.), extrae los
    # elementos exactos en background. Si no tiene capas, no hace nada.
    from app.services.pdf_vector_import import try_vector_import
    background_tasks.add_task(try_vector_import, plan.id)
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
def recommend_plan_pages(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Analiza el PDF y recomienda páginas aplicando overrides manuales del usuario."""
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
            status_code=500, detail=f"Error analizando el PDF para recomendar páginas: {exc}"
        ) from exc

    overrides = plan.page_overrides or {}
    for rec in recs:
        page_key = str(rec["page"])
        override = overrides.get(page_key)
        if override == "recommended":
            rec.update(recommended=True, score=1000, reason="Marcada manualmente como planta",
                       override="recommended")
        elif override == "rejected":
            rec.update(recommended=False, score=-1000, reason="Marcada manualmente como NO planta",
                       override="rejected")
        else:
            rec["override"] = None
    return recs


@router.get("/plans/{plan_id}/suggest-roles")
def suggest_page_roles(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Clasifica cada página del PDF y sugiere roles automáticamente.

    Usa heurísticas sobre el texto del rótulo y el contenido para determinar
    si una página es planta, corte, planilla, estructura, etc. y sugiere los
    roles apropiados para la detección.
    """
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")
    pdf_path = Path(plan.pdf_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF original no disponible")

    try:
        return classify_pages(pdf_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"Error clasificando páginas: {exc}"
        ) from exc


@router.post("/plans/{plan_id}/page-override", response_model=PlanRead)
def set_page_override(
    plan_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Plan:
    """Setea o quita el override manual para una página."""
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
        raise HTTPException(status_code=400, detail="Página fuera de rango")

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


@router.post("/plans/{plan_id}/delete-page/{page}", response_model=PlanRead)
def delete_page(
    plan_id: int,
    page: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Plan:
    """Elimina físicamente una página del PDF y migra todos los datos asociados."""
    import fitz

    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Plan no encontrado")

    if page < 1 or (plan.page_count and page > plan.page_count):
        raise HTTPException(status_code=400, detail="Número de página inválido")

    if plan.page_count == 1:
        raise HTTPException(status_code=400, detail="No puedes eliminar la única página del documento")

    pdf_path = Path(plan.pdf_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF original no encontrado")

    db.query(DetectedElement).filter(
        DetectedElement.plan_id == plan_id,
        DetectedElement.page == page,
    ).delete(synchronize_session=False)

    try:
        if plan.scale_source == "dxf":
            # Para planos DXF no se usa PDF (ni PyMuPDF).
            # Las páginas están divididas en archivos _p{n}.svg y _p{n}.png
            pass
        else:
            doc = fitz.open(pdf_path)
            if doc.page_count > 1:
                doc.delete_page(page - 1)
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

    for el in db.query(DetectedElement).filter(
        DetectedElement.plan_id == plan_id, DetectedElement.page > page
    ).all():
        el.page -= 1

    if plan.page_scales:
        new_scales = {}
        for p_str, scale_val in plan.page_scales.items():
            if not p_str.isdigit():
                new_scales[p_str] = scale_val
                continue
            p_num = int(p_str)
            if p_num < page:
                new_scales[str(p_num)] = scale_val
            elif p_num > page:
                new_scales[str(p_num - 1)] = scale_val
        plan.page_scales = new_scales
        flag_modified(plan, "page_scales")

    plan.page_count -= 1
    plan.deleted_pages = []
    flag_modified(plan, "deleted_pages")

    try:
        if plan.scale_source == "dxf":
            base_stem = pdf_path.stem
            if base_stem.endswith("_p1"):
                base_stem = base_stem[:-3]
            
            # Borrar los archivos de la página
            pdf_path.with_name(f"{base_stem}_p{page}.svg").unlink(missing_ok=True)
            pdf_path.with_name(f"{base_stem}_p{page}.png").unlink(missing_ok=True)
            
            # Renombrar los archivos de páginas siguientes (page+1 -> page)
            for p in range(page + 1, plan.page_count + 2):
                old_svg = pdf_path.with_name(f"{base_stem}_p{p}.svg")
                new_svg = pdf_path.with_name(f"{base_stem}_p{p - 1}.svg")
                old_png = pdf_path.with_name(f"{base_stem}_p{p}.png")
                new_png = pdf_path.with_name(f"{base_stem}_p{p - 1}.png")
                if old_svg.exists():
                    old_svg.rename(new_svg)
                if old_png.exists():
                    old_png.rename(new_png)
        else:
            raster_file = _page_raster_path(pdf_path, page)
            raster_file.unlink(missing_ok=True)
            enhanced = raster_file.parent / f"{raster_file.stem}_enhanced{raster_file.suffix}"
            enhanced.unlink(missing_ok=True)
            for p in range(page + 1, plan.page_count + 2):
                old_r = _page_raster_path(pdf_path, p)
                new_r = _page_raster_path(pdf_path, p - 1)
                if old_r.exists():
                    old_r.rename(new_r)
                old_e = old_r.parent / f"{old_r.stem}_enhanced{old_r.suffix}"
                new_e = new_r.parent / f"{new_r.stem}_enhanced{new_r.suffix}"
                if old_e.exists():
                    old_e.rename(new_e)
    except Exception:  # noqa: BLE001
        pass  # limpieza de caché es best-effort

    db.commit()
    db.refresh(plan)
    return plan
