"""Presupuesto del proyecto: lista del proveedor guardada × reglas × IFC.

La vista se recalcula siempre en vivo (si cambia el juego de reglas o se
re-procesa el IFC, el presupuesto se actualiza solo); lo único persistido
son el archivo, su lectura y las decisiones del usuario en la revisión.
"""
from __future__ import annotations

import copy
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.plan import Plan
from app.models.project import Project
from app.models.project_price_list import ProjectPriceList
from app.models.rule_set import RuleSet
from app.services import budget_rules as br
from app.services.price_list_parse import parse_price_list


def model_status(project_id: int, db: Session) -> str:
    """Estado del último IFC del proyecto: ready / processing / error / missing."""
    plans = db.scalars(
        select(Plan)
        .where(Plan.project_id == project_id, Plan.original_filename.ilike("%.ifc"))
        .order_by(Plan.id.desc())
    ).all()
    if not plans:
        return "missing"
    if any(p.status == "ready" for p in plans):
        return "ready"
    if plans[0].status == "processing":
        return "processing"
    return "error"


def resolve_rule_set(project: Project, db: Session, rule_set_id: int | None = None) -> RuleSet:
    """El juego pedido, el del proyecto, o el predeterminado de la org."""
    br.ensure_default_rule_set(project.organization_id, db)
    for rid in (rule_set_id, project.rule_set_id):
        if rid is None:
            continue
        rs = db.scalar(select(RuleSet).where(
            RuleSet.id == rid, RuleSet.organization_id == project.organization_id)
            .options(selectinload(RuleSet.rules)))
        if rs is not None:
            return rs
        if rid == rule_set_id:
            raise LookupError("Juego de reglas no encontrado")
    return db.scalar(
        select(RuleSet).where(RuleSet.organization_id == project.organization_id)
        .order_by(RuleSet.is_default.desc(), RuleSet.id)
        .options(selectinload(RuleSet.rules)))


def get_price_list(project_id: int, db: Session) -> ProjectPriceList | None:
    return db.scalar(select(ProjectPriceList).where(ProjectPriceList.project_id == project_id))


def _patched_lines(pl: ProjectPriceList) -> list[dict]:
    lines = copy.deepcopy(pl.parsed.get("lines") or [])
    for ln in lines:
        patch = (pl.line_patches or {}).get(str(ln["row"]))
        if patch:
            pres = ln.setdefault("presentation", {"attrs": {}})
            pres["amount"] = float(patch["amount"])
            pres["unit"] = patch["unit"]
            ln["patched"] = True
    return lines


def build_view(project: Project, db: Session) -> dict:
    rule_set = resolve_rule_set(project, db)
    pl = get_price_list(project.id, db)
    status = model_status(project.id, db)
    view: dict = {
        "rule_set": {"id": rule_set.id, "name": rule_set.name} if rule_set else None,
        "model_status": status,
        "price_list": None,
        "measures": None,
        "budget": None,
    }
    if pl is None:
        return view
    lines = _patched_lines(pl)
    view["price_list"] = {
        **{k: v for k, v in pl.parsed.items() if k != "lines"},
        "lines": lines,
        "filename": pl.original_filename,
        "iva_mode": "auto" if pl.iva_included is None else (
            "included" if pl.iva_included else "excluded"),
        "overrides": pl.overrides or {},
        "line_patches": pl.line_patches or {},
        "updated_at": pl.updated_at.isoformat() if pl.updated_at else None,
    }
    if status != "ready" or rule_set is None:
        return view
    measures = br.project_measures(project.id, db)
    if measures is None:
        return view
    view["measures"] = measures.as_dict()
    view["budget"] = br.compute_budget(
        measures, [br.RuleSpec.of(r) for r in rule_set.rules], lines,
        overrides=pl.overrides or {})
    return view


def _store_file(project_id: int, filename: str, data: bytes) -> str:
    folder = Path(settings.STORAGE_DIR) / "price_lists" / str(project_id)
    folder.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in Path(filename).name)[-120:]
    path = folder / f"{uuid.uuid4().hex[:8]}_{safe}"
    path.write_bytes(data)
    return str(path)


def save_price_list(project: Project, filename: str, data: bytes, db: Session, *,
                    rule_set_id: int | None, iva_included: bool | None) -> ProjectPriceList:
    """Sube/reemplaza la lista del proyecto. Reemplazar borra las decisiones
    de la revisión anterior (eran sobre otros renglones)."""
    parsed = parse_price_list(filename, data, iva_included=iva_included)  # ValueError → 400
    if rule_set_id is not None:
        project.rule_set_id = resolve_rule_set(project, db, rule_set_id).id
    elif project.rule_set_id is None:
        rs = resolve_rule_set(project, db)
        project.rule_set_id = rs.id if rs else None

    pl = get_price_list(project.id, db)
    old_path = pl.file_path if pl else None
    if pl is None:
        pl = ProjectPriceList(project_id=project.id)
        db.add(pl)
    pl.original_filename = filename
    pl.file_path = _store_file(project.id, filename, data)
    pl.iva_included = iva_included
    pl.parsed = parsed
    pl.overrides = {}
    pl.line_patches = {}
    project.wizard_step = max(project.wizard_step, 3)
    db.flush()
    if old_path and old_path != pl.file_path:
        Path(old_path).unlink(missing_ok=True)
    return pl


def update_price_list(project: Project, pl: ProjectPriceList, db: Session, *,
                      rule_set_id: int | None = None, iva_mode: str | None = None,
                      overrides: dict | None = None, line_patches: dict | None = None) -> None:
    if rule_set_id is not None:
        project.rule_set_id = resolve_rule_set(project, db, rule_set_id).id
    if iva_mode is not None:
        forced = {"auto": None, "included": True, "excluded": False}[iva_mode]
        if forced != pl.iva_included:
            data = Path(pl.file_path).read_bytes()
            pl.parsed = parse_price_list(pl.original_filename, data, iva_included=forced)
            pl.iva_included = forced
    if overrides is not None:
        pl.overrides = overrides
    if line_patches is not None:
        pl.line_patches = line_patches
    db.flush()
