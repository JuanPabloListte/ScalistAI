"""Importar factura (PDF) → PROPUESTA de costo real.

Las facturas electrónicas argentinas (post-2019) son PDF con capa de texto:
las leemos con PyMuPDF de forma DETERMINÍSTICA (extraemos lo impreso, no
inventamos nada). Coherente con "solo data real": el parser PROPONE monto/
fecha/proveedor; el humano revisa y confirma antes de crear el ActualCost.

Si el PDF NO tiene capa de texto (factura escaneada / foto), caemos a OCR con
tesseract (rasterizamos las páginas y las leemos). El OCR también extrae, no
fabrica; se marca `source="ocr"` para avisar que conviene revisar con más ojo.
Si tesseract no está disponible o la imagen es ilegible, ok=False (nunca se
inventa un monto).
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


def _ocr_pdf(pdf_bytes: bytes) -> str:
    """OCR de las páginas (facturas escaneadas). Rasteriza con PyMuPDF a 300 DPI
    y corre tesseract en español (fallback a idioma por defecto). '' si tesseract
    no está instalado o falla — nunca inventa texto."""
    try:
        import io

        import pytesseract
        from PIL import Image
    except Exception:  # noqa: BLE001 — pytesseract/PIL no disponibles
        return ""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:  # noqa: BLE001
        return ""
    parts: list[str] = []
    try:
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(300 / 72, 300 / 72))
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            try:
                parts.append(pytesseract.image_to_string(img, lang="spa"))
            except Exception:  # noqa: BLE001 — paquete de idioma spa ausente
                parts.append(pytesseract.image_to_string(img))
    except Exception:  # noqa: BLE001 — tesseract no instalado en el sistema
        return ""
    finally:
        doc.close()
    return "\n".join(parts)


def parse_invoice(pdf_bytes: bytes) -> dict:
    """Extrae una propuesta de costo desde la factura. Primero la capa de texto
    del PDF; si no hay, OCR. Nunca fabrica: si no encuentra un dato lo deja en
    None y ofrece candidatos."""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = "\n".join(p.get_text() for p in doc)
        doc.close()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"No se pudo leer el PDF: {exc}"}

    source = "text"
    if len(text.strip()) < 10:
        ocr = _ocr_pdf(pdf_bytes)
        if len(ocr.strip()) < 10:
            return {"ok": False, "reason": (
                "El PDF no tiene texto y no se pudo leer por OCR (imagen ilegible o "
                "tesseract no disponible). Cargá el costo a mano.")}
        text, source = ocr, "ocr"

    result = _extract_fields(text)
    result["source"] = source
    if source == "ocr":
        result["note"] = ("Leído por OCR de una factura escaneada — revisá monto y "
                          "fecha con atención antes de guardar.")
    return result


def _extract_fields(text: str) -> dict:
    """Heurísticas de extracción sobre el texto (venga de la capa PDF o del OCR)."""
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
