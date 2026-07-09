"""Importar factura (PDF) → PROPUESTA de costo real.

Las facturas electrónicas argentinas (post-2019) son PDF con capa de texto:
las leemos con PyMuPDF de forma DETERMINÍSTICA (extraemos lo impreso, no
inventamos nada). Coherente con "solo data real": el parser PROPONE monto/
fecha/proveedor; el humano revisa y confirma antes de crear el ActualCost.

No es OCR de imagen: si el PDF no tiene texto (factura escaneada), se devuelve
ok=False con un motivo claro (OCR de imagen queda como mejora futura).
"""
from __future__ import annotations

import datetime as dt
import re

import fitz  # PyMuPDF

# Monto en formato AR: miles con punto y centavos con coma (1.234.567,89),
# o simple con centavos (1234,56). Exige separador para no confundir con
# cantidades/CUIT/números sueltos.
_MONEY = re.compile(r"\$?\s*(\d{1,3}(?:\.\d{3})+(?:,\d{2})?|\d+,\d{2})")
_DATE = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b")
_CUIT = re.compile(r"\b(\d{2}-?\d{8}-?\d)\b")
# "total" pero NO "subtotal" (lookbehind excluye una letra previa, p.ej. la 'b').
_TOTAL_HINT = re.compile(r"(?<![a-z])(?:importe\s+total|total\s+a\s+pagar|total\s+final|total)", re.I)
_FECHA_HINT = re.compile(r"fecha(?:\s+de\s+emisi[oó]n)?\s*:?", re.I)


def _to_float_ar(s: str) -> float | None:
    """'1.234.567,89' → 1234567.89. Solo formato AR (punto=miles, coma=decimal)."""
    s = s.strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_date(d: str, m: str, y: str) -> dt.date | None:
    yy = int(y)
    if yy < 100:
        yy += 2000
    try:
        return dt.date(yy, int(m), int(d))
    except ValueError:
        return None


def parse_invoice(pdf_bytes: bytes) -> dict:
    """Extrae una propuesta de costo desde el texto de la factura. Nunca
    fabrica: si no encuentra un dato lo deja en None y ofrece candidatos."""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = "\n".join(p.get_text() for p in doc)
        doc.close()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"No se pudo leer el PDF: {exc}"}

    if len(text.strip()) < 10:
        return {"ok": False, "reason": (
            "El PDF no tiene texto legible (¿factura escaneada como imagen?). "
            "El OCR de imágenes no está soportado todavía: cargá el costo a mano.")}

    # --- Montos ---
    amounts = [(_to_float_ar(mm.group(1)), mm.start()) for mm in _MONEY.finditer(text)]
    amounts = [(v, pos) for v, pos in amounts if v is not None and v > 0]

    # Por cada etiqueta "TOTAL" tomamos el monto que la sigue más de cerca, y
    # nos quedamos con el mayor (el total general supera a los parciales).
    total_hinted = []
    for hint in _TOTAL_HINT.finditer(text):
        after = [(v, pos) for v, pos in amounts if pos >= hint.start()]
        if after:
            total_hinted.append(min(after, key=lambda a: a[1] - hint.start())[0])
    if total_hinted:
        total = max(total_hinted)
    elif amounts:
        total = max(v for v, _ in amounts)
    else:
        total = None

    # --- Fechas ---
    dates: list[dt.date] = []
    for mm in _DATE.finditer(text):
        d = _parse_date(*mm.groups())
        if d and 2015 <= d.year <= dt.date.today().year + 1:
            dates.append(d)
    # Preferencia: fecha cerca de una etiqueta "Fecha". Si no, la primera del doc.
    date = None
    for hint in _FECHA_HINT.finditer(text):
        near = _DATE.search(text, hint.end(), hint.end() + 40)
        if near:
            date = _parse_date(*near.groups())
            if date:
                break
    if date is None and dates:
        date = dates[0]

    cuit_m = _CUIT.search(text)
    lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) > 3]
    vendor = lines[0] if lines else None

    return {
        "ok": True,
        "amount": round(total, 2) if total else None,
        "date": date.isoformat() if date else None,
        "vendor": vendor,
        "cuit": cuit_m.group(1) if cuit_m else None,
        "amount_candidates": sorted({v for v, _ in amounts}, reverse=True)[:8],
        "date_candidates": [d.isoformat() for d in sorted(set(dates))][:8],
        "note": ("Propuesta extraída de la factura. Revisá monto y fecha antes de "
                 "guardar: el costo solo se registra cuando lo confirmás."),
    }
