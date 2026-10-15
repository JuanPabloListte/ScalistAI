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


# ---------------------------------------------------------------------------
# Exportación a Excel
# ---------------------------------------------------------------------------

_UNIT_LABEL = {"kg": "kg", "m3": "m³", "m2": "m²", "m": "m", "l": "l", "u": "u"}
_STATUS_LABEL = {"ok": "Con precio", "sin_precio": "Sin precio",
                 "sin_medida": "El modelo no lo trae",
                 "unidad_incompatible": "Unidad incompatible",
                 "regla_invalida": "Regla inválida"}


def budget_xlsx(project: Project, view: dict) -> bytes:
    """Presupuesto de materiales: resumen, lista de compras, detalle por regla
    y medidas del modelo. `view` es la salida de build_view (con budget)."""
    import io

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    budget, pl, measures = view["budget"], view["price_list"], view["measures"]
    money = '"$" #,##0.00'
    qty = "#,##0.00"
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="1E293B")
    unit = lambda u: _UNIT_LABEL.get(u, u)  # noqa: E731

    wb = Workbook()

    def table(ws, headers, rows, widths, formats):
        ws.append(headers)
        for c in ws[1]:
            c.font, c.fill = head_font, head_fill
            c.alignment = Alignment(vertical="center")
        for r in rows:
            ws.append(r)
            for col, fmt in formats.items():
                ws.cell(row=ws.max_row, column=col).number_format = fmt
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = "A2"

    # --- Resumen
    ws = wb.active
    ws.title = "Resumen"
    t = budget["totals"]
    ws.append(["Presupuesto de materiales"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([])
    info = [
        ("Proyecto", project.name),
        ("Proveedor", pl.get("supplier") or "—"),
        ("Archivo", pl.get("filename")),
        ("Fecha del presupuesto", pl.get("document_date") or "—"),
        ("Reglas de cómputo", (view.get("rule_set") or {}).get("name", "—")),
        ("Precios del archivo",
         "con IVA (se pasaron a neto)" if pl["iva"]["included"] else "sin IVA"),
        None,
        ("Materiales (neto)", t["net"]),
        (f"IVA {round(t['iva_rate'] * 100)}%", t["iva"]),
        ("Total con IVA", t["total"]),
        None,
        ("Ítems con precio", budget["counts"]["ok"]),
        ("Ítems sin precio", budget["counts"]["sin_precio"]),
        ("Ítems sin medida en el modelo", budget["counts"]["sin_medida"]),
    ]
    for entry in info:
        if entry is None:
            ws.append([])
            continue
        ws.append(list(entry))
        if isinstance(entry[1], float):
            ws.cell(row=ws.max_row, column=2).number_format = money
        if entry[0] == "Total con IVA":
            for col in (1, 2):
                ws.cell(row=ws.max_row, column=col).font = Font(bold=True)
    ws.column_dimensions["A"].width = 32
    ws.column_dimensions["B"].width = 48

    # --- Lista de compras
    rows = [[s.get("code") or "", s["description"],
             f"{s['presentation']['amount']:g} {unit(s['presentation']['unit'])}",
             s["units_to_buy"], s["unit_price_net"], s["subtotal"]]
            for s in budget["shopping_list"]]
    rows.append(["", "TOTAL NETO", "", None, None, t["net"]])
    table(wb.create_sheet("Lista de compras"),
          ["Código", "Producto del proveedor", "Presentación", "Unidades",
           "Precio unit. neto", "Subtotal neto"],
          rows, [14, 60, 14, 12, 18, 18], {4: "#,##0", 5: money, 6: money})

    # --- Detalle por regla
    rows = []
    for it in budget["items"]:
        status = _STATUS_LABEL.get(it.get("status"), it.get("status") or "")
        if it.get("manual"):
            status += " (a mano)"
        rows.append([
            it.get("measure_label"), it["label"], it.get("measure_value"),
            unit(it.get("measure_unit")), it.get("factor"), it.get("waste_pct"),
            it.get("quantity"), unit(it.get("unit")),
            (it.get("line") or {}).get("description", ""),
            it.get("units_to_buy"), it.get("subtotal"), status,
        ])
    table(wb.create_sheet("Detalle"),
          ["Medida", "Producto", "Medida del modelo", "Unidad", "Factor", "Desperdicio %",
           "Cantidad", "Unidad", "Renglón del proveedor", "Unidades", "Subtotal neto", "Estado"],
          rows, [30, 34, 14, 8, 10, 12, 14, 8, 50, 12, 16, 18],
          {3: qty, 5: "0.0000", 7: qty, 10: qty, 11: money})

    # --- Medidas del modelo
    rows = [[m["label"], m["value"], unit(m["unit"]), m["count"]] for m in measures["measures"]]
    rows += [[f"  Hierro Ø{r['diameter_mm']:g}", r["kg"], "kg", None]
             for r in measures["rebar_by_diameter"]]
    rows += [[f"Aviso: {w}", None, "", None] for w in measures["warnings"]]
    table(wb.create_sheet("Medidas del modelo"), ["Medida", "Valor", "Unidad", "Elementos"],
          rows, [60, 14, 8, 10], {2: qty})

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
