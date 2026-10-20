"""Presupuesto de obra por rubros en PDF, con el membrete del estudio.

Dos versiones:
- comitente: precio por rubro con gastos generales y beneficio ya repartidos
  (coeficiente de pase), subtotal sin IVA, IVA y total. Es el que se manda.
- interno: costo de materiales y mano de obra por rubro, redondeo de compra,
  gastos generales, beneficio y precio de venta, para revisar márgenes.

Función pura sobre la vista de project_budget.build_view (no toca la DB).
"""
from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

_INK = colors.HexColor("#0F172A")
_BRAND = colors.HexColor("#075985")
_MUTED = colors.HexColor("#64748B")
_LINE = colors.HexColor("#E2E8F0")
_ZEBRA = colors.HexColor("#F8FAFC")
_UNIT = {"m2": "m²", "m3": "m³", "m": "m", "kg": "kg", "u": "u", "l": "l"}
_WIDTH = A4[0] - 36 * mm  # ancho útil


def _money(n: float | None) -> str:
    if n is None:
        return "—"
    return "$ " + f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _qty(n: float | None) -> str:
    if n is None:
        return "—"
    return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(n: float) -> str:
    return f"{n * 100:.1f}".replace(".", ",") + " %"


def _styles() -> dict:
    base = getSampleStyleSheet()

    def s(name, **kw):
        kw.setdefault("fontName", "Helvetica")
        kw.setdefault("fontSize", 9)
        kw.setdefault("leading", 12)
        kw.setdefault("textColor", _INK)
        return ParagraphStyle(name, parent=base["Normal"], **kw)

    return {
        "org": s("org", fontName="Helvetica-Bold", fontSize=13, leading=16, alignment=2),
        "contact": s("contact", fontSize=8, leading=10.5, textColor=_MUTED, alignment=2),
        "title": s("title", fontName="Helvetica-Bold", fontSize=18, leading=22),
        "meta": s("meta", fontSize=9, textColor=_MUTED),
        "h2": s("h2", fontName="Helvetica-Bold", fontSize=11.5, leading=15, textColor=_BRAND,
                spaceBefore=10, spaceAfter=5),
        "h3": s("h3", fontName="Helvetica-Bold", fontSize=10, leading=13, spaceBefore=8,
                spaceAfter=3),
        "cell": s("cell"),
        "cell_r": s("cell_r", alignment=2),
        "hdr": s("hdr", fontName="Helvetica-Bold", fontSize=8, textColor=_MUTED),
        "hdr_r": s("hdr_r", fontName="Helvetica-Bold", fontSize=8, textColor=_MUTED, alignment=2),
        "tot": s("tot", fontName="Helvetica-Bold"),
        "tot_r": s("tot_r", fontName="Helvetica-Bold", alignment=2),
        "big": s("big", fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=_BRAND),
        "big_r": s("big_r", fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=_BRAND,
                   alignment=2),
        "note": s("note", fontSize=8, leading=11, textColor=_MUTED),
    }


def _rubros(view: dict) -> tuple[list[dict], float]:
    """Ítems con precio agrupados por rubro, en el orden en que aparecen.
    Devuelve (rubros, redondeo): el redondeo es lo que suma comprar unidades
    enteras (la lista de compras) sobre lo que consumen las reglas."""
    rubros: dict[str, dict] = {}

    def add(stage: str, row: dict, kind: str):
        r = rubros.setdefault(stage, {"stage": stage, "materials": 0.0, "labor": 0.0, "rows": []})
        r[kind] += row["amount"]
        r["rows"].append(row)

    budget = view.get("budget") or {}
    for it in budget.get("items", []):
        if it.get("status") != "ok" or not it.get("subtotal"):
            continue
        q = it.get("quantity") or 0
        add(it.get("stage") or "Sin rubro", {
            "label": it["label"], "unit": _UNIT.get(it.get("unit"), it.get("unit")),
            "qty": q, "unit_price": it["subtotal"] / q if q else None,
            "amount": it["subtotal"], "kind": "Material",
        }, "materials")
    for it in (view.get("labor") or {}).get("items", []):
        if it.get("status") != "ok" or not it.get("cost"):
            continue
        add(it.get("stage") or "Sin rubro", {
            "label": it["label"], "unit": _UNIT.get(it.get("measure_unit"), it.get("measure_unit")),
            "qty": it["quantity"], "unit_price": it.get("unit_price"), "amount": it["cost"],
            "kind": "Mano de obra",
        }, "labor")
    items_materials = sum(r["materials"] for r in rubros.values())
    rounding = round(((budget.get("totals") or {}).get("net") or 0.0) - items_materials, 2)
    return list(rubros.values()), rounding


def _table(rows: list[list], widths: list[float], st: dict, *, right_from: int,
           total_rows: int = 0, zebra: bool = True) -> Table:
    def cell(v, i, r, header=False):
        if isinstance(v, Paragraph):
            return v
        if header:
            return Paragraph(str(v), st["hdr_r"] if i >= right_from else st["hdr"])
        bold = r >= len(rows) - total_rows
        style = ("tot_r" if bold else "cell_r") if i >= right_from else ("tot" if bold else "cell")
        return Paragraph(str(v), st[style])

    data = [[cell(v, i, r, header=(r == 0)) for i, v in enumerate(row)]
            for r, row in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, _INK),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    body_end = len(rows) - 1 - total_rows
    if zebra:
        for r in range(1, body_end + 1):
            if r % 2 == 0:
                style.append(("BACKGROUND", (0, r), (-1, r), _ZEBRA))
    if total_rows:
        style.append(("LINEABOVE", (0, body_end + 1), (-1, body_end + 1), 0.6, _LINE))
    t.setStyle(TableStyle(style))
    return t


def _header(org: dict, st: dict) -> Table:
    logo = None
    path = org.get("logo_path")
    if path and Path(path).exists():
        try:
            from reportlab.lib.utils import ImageReader

            w, h = ImageReader(path).getSize()
            scale = min(45 * mm / w, 20 * mm / h)
            logo = Image(path, width=w * scale, height=h * scale)
        except Exception:  # noqa: BLE001 — un logo roto no frena el presupuesto
            logo = None
    right = [Paragraph(org.get("name") or "", st["org"])]
    for line in (org.get("contact_info") or "").splitlines():
        if line.strip():
            right.append(Paragraph(line.strip(), st["contact"]))
    t = Table([[logo or "", right]], colWidths=[_WIDTH * 0.45, _WIDTH * 0.55])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, _BRAND), ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
    ]))
    return t


def build_budget_pdf(project: dict, org: dict, view: dict, audience: str = "comitente") -> bytes:
    """`project`: {id, name, address}; `org`: {name, contact_info, logo_path}."""
    st = _styles()
    price = view.get("price") or {}
    rubros, rounding = _rubros(view)
    internal = audience == "interno"
    today = date.today().strftime("%d/%m/%Y")

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=18 * mm,
                            title=f"Presupuesto {project.get('name')}", author=org.get("name") or "")
    story: list = [_header(org, st), Spacer(1, 8 * mm)]
    story.append(Paragraph("Presupuesto de obra" + (" — uso interno" if internal else ""),
                           st["title"]))
    meta = [f"Presupuesto Nº {project['id']:04d}", f"Fecha: {today}"]
    story.append(Paragraph(" · ".join(meta), st["meta"]))
    story.append(Spacer(1, 4 * mm))

    obra = [["Obra", project.get("name") or "—"]]
    if project.get("address"):
        obra.append(["Ubicación", project["address"]])
    cubierta = next((m["value"] for m in (view.get("measures") or {}).get("measures", [])
                     if m["key"] == "sup_cubierta_m2" and m["value"]), None)
    if cubierta:
        obra.append(["Superficie cubierta", f"{_qty(cubierta)} m²"])
    ot = Table([[Paragraph(a, st["hdr"]), Paragraph(b, st["cell"])] for a, b in obra],
               colWidths=[38 * mm, _WIDTH - 38 * mm])
    ot.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0),
                            ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]))
    story.append(ot)

    # Coeficiente de pase: lleva el costo de cada rubro al precio sin IVA.
    cost_sum = sum(r["materials"] + r["labor"] for r in rubros)
    k = (price.get("net") or 0) / cost_sum if cost_sum else 1.0

    story.append(Paragraph("Resumen por rubros", st["h2"]))
    if internal:
        rows = [["Rubro", "Materiales", "Mano de obra", "Subtotal", "Incidencia"]]
        direct = price.get("direct") or 0
        for r in rubros:
            sub = r["materials"] + r["labor"]
            rows.append([r["stage"], _money(r["materials"]), _money(r["labor"]), _money(sub),
                         _pct(sub / direct) if direct else "—"])
        if abs(rounding) >= 1:
            rows.append(["Redondeo a unidades de venta", _money(rounding), "", _money(rounding),
                         _pct(rounding / direct) if direct else "—"])
        totals = [
            ["Costo directo", "", "", _money(price.get("direct")), ""],
            [f"Gastos generales ({_pct(price.get('overhead_pct', 0))})", "", "",
             _money(price.get("overhead")), ""],
            [f"Beneficio ({_pct(price.get('profit_pct', 0))})", "", "", _money(price.get("profit")), ""],
            ["Precio sin IVA", "", "", _money(price.get("net")), ""],
            [f"IVA ({_pct(price.get('iva_pct', 0.21))})", "", "", _money(price.get("iva")), ""],
        ]
        story.append(_table(rows + totals, [_WIDTH * 0.34, _WIDTH * 0.17, _WIDTH * 0.17,
                                            _WIDTH * 0.19, _WIDTH * 0.13],
                            st, right_from=1, total_rows=len(totals)))
    else:
        rows = [["Rubro", "Importe", "Incidencia"]]
        amounts = [round((r["materials"] + r["labor"]) * k, 2) for r in rubros]
        if amounts:  # el último rubro absorbe la diferencia de redondeo
            amounts[-1] = round((price.get("net") or 0) - sum(amounts[:-1]), 2)
        net = price.get("net") or 0
        for r, amount in zip(rubros, amounts):
            rows.append([r["stage"], _money(amount), _pct(amount / net) if net else "—"])
        totals = [["Subtotal (sin IVA)", _money(net), ""],
                  [f"IVA ({_pct(price.get('iva_pct', 0.21))})", _money(price.get("iva")), ""]]
        story.append(_table(rows + totals, [_WIDTH * 0.6, _WIDTH * 0.25, _WIDTH * 0.15],
                            st, right_from=1, total_rows=len(totals)))

    total = Table([[Paragraph("Precio total" if not internal else "Precio de venta", st["big"]),
                    Paragraph(_money(price.get("total")), st["big_r"])]],
                  colWidths=[_WIDTH * 0.6, _WIDTH * 0.4])
    total.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 1.2, _BRAND),
                               ("TOPPADDING", (0, 0), (-1, -1), 6),
                               ("LEFTPADDING", (0, 0), (-1, -1), 4),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 4)]))
    story.append(total)

    story.append(Paragraph("Detalle por rubro", st["h2"]))
    f = 1.0 if internal else k
    for r in rubros:
        head = ["Ítem", "Unidad", "Cantidad", "Precio unitario", "Importe"]
        if internal:
            head = ["Ítem", "Tipo", "Unidad", "Cantidad", "Costo unitario", "Importe"]
        rows = [head]
        for row in r["rows"]:
            unit_price = row["unit_price"] * f if row["unit_price"] is not None else None
            line = [row["label"], row["unit"], _qty(row["qty"]), _money(unit_price),
                    _money(row["amount"] * f)]
            if internal:
                line.insert(1, row["kind"])
            rows.append(line)
        rows.append(["Total " + r["stage"].lower()] + [""] * (len(head) - 2)
                    + [_money((r["materials"] + r["labor"]) * f)])
        widths = ([_WIDTH * 0.40, _WIDTH * 0.08, _WIDTH * 0.14, _WIDTH * 0.19, _WIDTH * 0.19]
                  if not internal else
                  [_WIDTH * 0.30, _WIDTH * 0.13, _WIDTH * 0.09, _WIDTH * 0.12, _WIDTH * 0.17,
                   _WIDTH * 0.19])
        story.append(KeepTogether([Paragraph(r["stage"], st["h3"]),
                                   _table(rows, widths, st, right_from=len(head) - 3,
                                          total_rows=1)]))

    story.append(Spacer(1, 6 * mm))
    notes = ["Cantidades calculadas a partir del modelo BIM (IFC) del proyecto. "
             "Importes en pesos argentinos."]
    if not internal:
        notes.append("Los precios por rubro incluyen gastos generales y beneficio.")
    pending = (((view.get("budget") or {}).get("counts") or {}).get("sin_precio", 0)
               + ((view.get("labor") or {}).get("counts") or {}).get("pendientes", 0))
    if internal and pending:
        notes.append(f"{pending} ítems sin precio no están incluidos.")
    if internal and abs(rounding) >= 1:
        notes.append("El redondeo es lo que suma comprar unidades enteras (bolsas, camiones, "
                     "barras) sobre lo que consume la obra.")
    for n in notes:
        story.append(Paragraph(n, st["note"]))

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(_MUTED)
        canvas.drawString(18 * mm, 10 * mm, f"{org.get('name') or ''} · Presupuesto Nº "
                                            f"{project['id']:04d} · {project.get('name') or ''}")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Página {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
