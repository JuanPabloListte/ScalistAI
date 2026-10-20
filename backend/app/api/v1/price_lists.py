from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.uploads import read_upload
from app.models.user import User
from app.services import budget_rules as br
from app.services import project_budget as pb
from app.services.price_list_parse import parse_price_list
from app.services.project_access import require_project

router = APIRouter(prefix="/price-lists", tags=["price-lists"])
project_router = APIRouter(prefix="/projects", tags=["price-lists"])

MAX_PRICE_LIST_BYTES = 15 * 1024 * 1024


async def _read_and_parse(file: UploadFile, iva_included: bool | None) -> dict:
    data = await read_upload(file, MAX_PRICE_LIST_BYTES)
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

    try:
        rule_set = pb.resolve_rule_set(project, db, rule_set_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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


# --- Lista del proveedor guardada en el proyecto (paso "Precios" del wizard) ---

class LinePatch(BaseModel):
    amount: float = Field(gt=0)
    unit: Literal["kg", "m3", "m2", "m", "l", "u"]


class PriceListPatch(BaseModel):
    rule_set_id: int | None = None
    iva_mode: Literal["auto", "included", "excluded"] | None = None
    # Reemplazan el dict completo (item_key → row | null; row → {amount, unit}).
    overrides: dict[str, int | None] | None = None
    line_patches: dict[str, LinePatch] | None = None


@project_router.get("/{project_id}/price-list")
def get_project_price_list(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Lista del proveedor del proyecto + presupuesto recalculado en vivo.
    `price_list` es null si todavía no se subió; `budget` es null mientras el
    IFC no esté procesado (`model_status`)."""
    project, _ = require_project(project_id, db, user, financials=True)
    view = pb.build_view(project, db)
    db.commit()  # seed del juego por defecto, si hizo falta
    return view


@project_router.post("/{project_id}/price-list")
async def upload_project_price_list(
    project_id: int,
    file: UploadFile = File(...),
    rule_set_id: int | None = Form(default=None),
    iva_included: bool | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    project, _ = require_project(project_id, db, user, financials=True)
    data = await read_upload(file, MAX_PRICE_LIST_BYTES)
    try:
        pb.save_price_list(project, file.filename or "presupuesto", data, db,
                           rule_set_id=rule_set_id, iva_included=iva_included)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return pb.build_view(project, db)


@project_router.patch("/{project_id}/price-list")
def update_project_price_list(
    project_id: int,
    payload: PriceListPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    project, _ = require_project(project_id, db, user, financials=True)
    pl = pb.get_price_list(project.id, db)
    try:
        if pl is None:
            # Sin archivo todavía solo se puede elegir el juego de reglas.
            if payload.rule_set_id is None:
                raise HTTPException(status_code=404, detail="El proyecto no tiene presupuesto de proveedor")
            project.rule_set_id = pb.resolve_rule_set(project, db, payload.rule_set_id).id
        else:
            pb.update_price_list(
                project, pl, db,
                rule_set_id=payload.rule_set_id,
                iva_mode=payload.iva_mode,
                overrides=payload.overrides,
                line_patches=({k: v.model_dump() for k, v in payload.line_patches.items()}
                              if payload.line_patches is not None else None),
            )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return pb.build_view(project, db)


class LaborSetting(BaseModel):
    mode: Literal["unit", "daily"] | None = None
    unit_price: float | None = Field(default=None, ge=0)


class BudgetSettingsPatch(BaseModel):
    # rule_id → ajuste del rubro; null = volver a lo que dice la regla.
    labor: dict[str, LaborSetting | None] | None = None
    overhead_pct: float | None = Field(default=None, ge=0, le=5)
    profit_pct: float | None = Field(default=None, ge=0, le=5)
    # True = volver a los márgenes de la empresa.
    reset_margins: bool = False


@project_router.patch("/{project_id}/budget-settings")
def update_project_budget_settings(
    project_id: int,
    payload: BudgetSettingsPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Mano de obra de esta obra (modo y precio por rubro) y márgenes propios."""
    project, _ = require_project(project_id, db, user, financials=True, edit_plan=True)
    pb.update_budget_settings(
        project, db,
        labor=({k: (v.model_dump(exclude_unset=True) if v is not None else None)
                for k, v in payload.labor.items()} if payload.labor is not None else None),
        overhead_pct=payload.overhead_pct, profit_pct=payload.profit_pct,
        reset_margins=payload.reset_margins)
    db.commit()
    return pb.build_view(project, db)


@project_router.delete("/{project_id}/price-list", status_code=204)
def delete_project_price_list(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    project, _ = require_project(project_id, db, user, financials=True)
    pl = pb.get_price_list(project.id, db)
    if pl is not None:
        path = pl.file_path
        db.delete(pl)
        db.commit()
        Path(path).unlink(missing_ok=True)


@project_router.get("/{project_id}/price-list/export.xlsx")
def export_project_budget_xlsx(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    project, _ = require_project(project_id, db, user, financials=True)
    if project.status != "active":
        raise HTTPException(
            status_code=400,
            detail="El Excel se descarga cuando el proyecto está creado (terminá el asistente).")
    view = pb.build_view(project, db)
    if view["budget"] is None:
        raise HTTPException(
            status_code=400,
            detail="Todavía no hay presupuesto: falta el presupuesto del proveedor "
                   "o el modelo IFC procesado.")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in project.name)[:60]
    return Response(
        content=pb.budget_xlsx(project, view),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f'attachment; filename="presupuesto_{safe or project.id}.xlsx"'},
    )


@project_router.get("/{project_id}/price-list/export.pdf")
def export_project_budget_pdf(
    project_id: int,
    audience: Literal["comitente", "interno"] = "comitente",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Presupuesto por rubros con el membrete del estudio. `comitente`: precios
    con gastos generales y beneficio repartidos; `interno`: costos y márgenes."""
    from app.models.organization import Organization
    from app.services.budget_pdf import build_budget_pdf

    project, _ = require_project(project_id, db, user, financials=True)
    if project.status != "active":
        raise HTTPException(
            status_code=400,
            detail="El PDF se descarga cuando el proyecto está creado (terminá el asistente).")
    view = pb.build_view(project, db)
    if not view.get("price") or not (view["price"]["materials"] or view["price"]["labor"]):
        raise HTTPException(
            status_code=400,
            detail="Todavía no hay importes: cargá el presupuesto del proveedor o los precios "
                   "de la mano de obra.")
    org = db.get(Organization, project.organization_id)
    pdf = build_budget_pdf(
        {"id": project.id, "name": project.name, "address": project.address},
        {"name": org.name if org else "", "contact_info": org.contact_info if org else None,
         "logo_path": org.logo_path if org else None},
        view, audience)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in project.name)[:60]
    suffix = "_interno" if audience == "interno" else ""
    db.commit()
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="presupuesto_{safe or project.id}{suffix}.pdf"'},
    )
