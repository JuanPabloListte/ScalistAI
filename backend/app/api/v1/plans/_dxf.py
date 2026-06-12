from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models import Plan, User
from app.services.dxf_import import (
    apply_layer_mapping,
    get_dxf_info,
    get_dxf_overview,
    get_layer_preview,
)

router = APIRouter(tags=["plans"])

class DxfLayerMappingBody(BaseModel):
    mapping: dict[str, str | None]
    # Recortes [x1, y1, x2, y2] en unidades de dibujo; cada uno será una página.
    regions: list[list[float]] | None = None
    # Tipo de cada recorte, paralelo a `regions`: "planta" (genera elementos)
    # o "corte" (solo referencia visual de alturas, no computa).
    region_types: list[str] | None = None

def _get_plan(plan_id: int, db: Session, user: User) -> Plan:
    plan = db.get(Plan, plan_id)
    if plan is None or plan.project.organization_id != user.organization_id:
        raise HTTPException(404, "Plan no encontrado")
    return plan

@router.get("/plans/{plan_id}/dxf-info")
def get_dxf_plan_info(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    plan = _get_plan(plan_id, db, user)
    return get_dxf_info(plan)


@router.get("/plans/{plan_id}/dxf-overview")
def dxf_overview(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileResponse:
    """PNG de toda la lámina para que el usuario recorte las vistas a computar."""
    plan = _get_plan(plan_id, db, user)
    path = get_dxf_overview(plan)
    return FileResponse(path, media_type="image/png")


@router.get("/plans/{plan_id}/dxf-layer-preview")
def dxf_layer_preview(
    plan_id: int,
    layer: str = Query(..., description="Nombre exacto de la capa"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileResponse:
    plan = _get_plan(plan_id, db, user)
    path = get_layer_preview(plan, layer)
    return FileResponse(path, media_type="image/png")


@router.post("/plans/{plan_id}/dxf-layers/apply")
def apply_dxf_layer_mapping(
    plan_id: int,
    body: DxfLayerMappingBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    plan = _get_plan(plan_id, db, user)
    count = apply_layer_mapping(
        plan, body.mapping, db, regions=body.regions, region_types=body.region_types
    )
    db.commit()
    return {"created": count}

class DxfScaleBody(BaseModel):
    unit: str

@router.post("/plans/{plan_id}/dxf-scale")
def update_dxf_scale(
    plan_id: int,
    body: DxfScaleBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    plan = _get_plan(plan_id, db, user)
    
    if body.unit == "m": override = 1.0
    elif body.unit == "cm": override = 0.01
    elif body.unit == "mm": override = 0.001
    else: raise HTTPException(400, "Unidad inválida. Use m, cm, o mm.")

    plan.page_scales = plan.page_scales or {}
    plan.page_scales = {**plan.page_scales, "dxf_unit": override}
    
    db.commit()
    return {"success": True}

