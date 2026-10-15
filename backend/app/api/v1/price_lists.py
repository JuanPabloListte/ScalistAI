from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.rule_set import RuleSet
from app.models.user import User
from app.services import budget_rules as br
from app.services.price_list_parse import parse_price_list
from app.services.project_access import require_project

router = APIRouter(prefix="/price-lists", tags=["price-lists"])
project_router = APIRouter(prefix="/projects", tags=["price-lists"])

MAX_PRICE_LIST_BYTES = 15 * 1024 * 1024


async def _read_and_parse(file: UploadFile, iva_included: bool | None) -> dict:
    data = await file.read()
    if len(data) > MAX_PRICE_LIST_BYTES:
        raise HTTPException(status_code=413, detail="El archivo supera los 15 MB.")
    try:
        return parse_price_list(file.filename or "", data, iva_included=iva_included)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/parse")
async def parse_price_list_preview(
    file: UploadFile = File(...),
    # "true"/"false" fuerza la base de IVA; vacío = detectar.
    iva_included: bool | None = Form(default=None),
    _: User = Depends(get_current_user),
) -> dict:
    """Previsualiza los renglones de un presupuesto de proveedor (PDF/Excel/CSV).
    No persiste nada."""
    return await _read_and_parse(file, iva_included)


@project_router.post("/{project_id}/price-list/preview")
async def preview_project_budget(
    project_id: int,
    file: UploadFile = File(...),
    rule_set_id: int | None = Form(default=None),
    iva_included: bool | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Presupuesto del proyecto = medidas de su IFC × juego de reglas × precios
    del archivo del proveedor. No persiste nada (la revisión lo confirma)."""
    project, _ = require_project(project_id, db, user, financials=True)

    measures = br.project_measures(project.id, db)
    if measures is None:
        raise HTTPException(
            status_code=400,
            detail="El proyecto no tiene un modelo IFC procesado. Subí el modelo primero.")

    br.ensure_default_rule_set(project.organization_id, db)
    q = select(RuleSet).where(RuleSet.organization_id == project.organization_id)
    if rule_set_id is not None:
        q = q.where(RuleSet.id == rule_set_id)
    else:
        q = q.order_by(RuleSet.is_default.desc(), RuleSet.id)
    rule_set = db.scalar(q.options(selectinload(RuleSet.rules)))
    if rule_set is None:
        raise HTTPException(status_code=404, detail="Juego de reglas no encontrado")
    db.commit()  # persiste el seed del juego por defecto si hizo falta

    price_list = await _read_and_parse(file, iva_included)
    budget = br.compute_budget(
        measures, [br.RuleSpec.of(r) for r in rule_set.rules], price_list["lines"])
    return {
        "rule_set": {"id": rule_set.id, "name": rule_set.name},
        "price_list": price_list,
        "measures": measures.as_dict(),
        "budget": budget,
    }
