"""Lector de listas de precios de proveedores (PDF con texto o Excel/CSV).

Determinístico, sin LLM: PyMuPDF da cada palabra con su posición → se
reconstruyen las filas de la tabla por coordenada Y y las columnas por el
encabezado ("Cantidad", "P. Unitario", "Total"...). El formato numérico
(1.234,56 vs 1,234.56) se decide por votación sobre todo el documento y el
IVA por aritmética contra los totales del pie (subtotal × 1,21 = total).

Salida: renglones con código, descripción, cantidad, precio unitario
efectivo (total / cantidad, así absorbe descuentos por renglón) y precio
NETO sin IVA, más la presentación de venta (25 KG, 6 M3, 12 MTS...).
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field

IVA_RATE = 0.21

# ---------------------------------------------------------------------------
# Utilidades de texto y números
# ---------------------------------------------------------------------------

_NUM_TOKEN = re.compile(r"^\$?-?\d[\d.,]*$")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[\s_]+", " ", s.lower()).strip()


def _is_num(tok: str) -> bool:
    return bool(_NUM_TOKEN.match(tok.strip()))


def _detect_decimal_sep(tokens: list[str]) -> str:
    """Vota el separador decimal del documento.

    Un token con '.' y ',' delata el formato (el último es el decimal). Si no
    hay ninguno, ',' seguido de exactamente 2 dígitos al final también vota.
    """
    votes = {".": 0, ",": 0}
    for t in tokens:
        t = t.lstrip("$-")
        if "." in t and "," in t:
            votes["." if t.rfind(".") > t.rfind(",") else ","] += 1
        elif re.fullmatch(r"\d+,\d{2}", t):
            votes[","] += 1
        elif re.fullmatch(r"\d+\.\d{2}", t):
            votes["."] += 1
    return "," if votes[","] > votes["."] else "."


def _to_float(tok: str, dec: str) -> float | None:
    t = tok.strip().lstrip("$").replace(" ", "")
    if not t:
        return None
    thou = "," if dec == "." else "."
    t = t.replace(thou, "").replace(dec, ".")
    try:
        return float(t)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Presentación de venta: "CEMENTO ... 25 KG", "ARENA CAMION 6M3", "12 MTS"
# ---------------------------------------------------------------------------

_PRES_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:kgs?|kilos?)\b\.?", re.I), "kg"),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*m3\b", re.I), "m3"),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:l|lts?|litros?)\b", re.I), "l"),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:mts|mt|metros|m)\b", re.I), "m"),
]
_PER_M3 = re.compile(r"\bx\s*m3\b", re.I)
_DIAM = re.compile(r"(\d+(?:[.,]\d+)?)\s*mm\b", re.I)
# "HIERRO 8 C/U": el número tras "hierro" es el diámetro aunque no diga MM.
_REBAR = re.compile(r"^\s*(?:hierro|acero)\s+(\d+(?:[.,]\d+)?)\s+(?:c/u|u|un|barra)?\b", re.I)
_DIMS = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*x\s*(\d+(?:[.,]\d+)?)(?:\s*x\s*(\d+(?:[.,]\d+)?))?\b", re.I)


_BARE_UNITS = {"m3": "m3", "m³": "m3", "kg": "kg", "kilo": "kg", "kilos": "kg",
               "m2": "m2", "m²": "m2", "ml": "m", "m": "m", "metro": "m"}


def _f(s: str) -> float:
    return float(s.replace(",", "."))


def _presentation_in(text: str) -> dict | None:
    if _PER_M3.search(text):
        return {"amount": 1.0, "unit": "m3"}
    for rx, unit in _PRES_PATTERNS:
        m = rx.search(text)
        if m:
            return {"amount": _f(m.group(1)), "unit": unit}
    return None


def parse_presentation(description: str, unit_hint: str | None = None) -> dict:
    """Cantidad y unidad que trae UNA unidad vendida + atributos útiles.

    {"amount": 25, "unit": "kg"} para una bolsa de 25 kg; {"amount": 1,
    "unit": "u"} si no se reconoce (se vende por unidad). attrs: diámetro en
    mm, medidas AxBxC (ladrillos, cerámicos).
    """
    # Descripción primero y la columna de unidad ("bolsa 30kg") por separado:
    # concatenarlas convertía "Hormigón H25" + "m3" en 25 m3.
    pres = _presentation_in(description) or _presentation_in(unit_hint or "") \
        or {"amount": 1.0, "unit": _BARE_UNITS.get(_norm(unit_hint or ""), "u")}

    attrs: dict = {}
    m = _DIAM.search(description) or _REBAR.search(description)
    if m:
        attrs["diameter_mm"] = _f(m.group(1))
    m = _DIMS.search(description)
    if m:
        attrs["dims"] = [_f(g) for g in m.groups() if g]
    return {**pres, "attrs": attrs}


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------

_TOTALS_KW = re.compile(
    r"\b(sub\s*total|total|i\.?\s*v\.?\s*a\.?|bonificaci|descuento|items|cant)\b", re.I)
_STOP_KW = re.compile(
    r"\b(items|sub\s*total|total|vendedor|formas?\s+de\s+pago|observaciones|"
    r"datos\s+bancarios|hoja\s*:|casa\s+central|tel\s*:)", re.I)
_CODE_PREFIX = re.compile(r"^([A-Z]{2,5}\d{3,})-(.+)$")
_INCLUDED_KW = re.compile(
    r"(con\s*i\.?\s*v\.?\s*a|i\.?\s*v\.?\s*a\.?\s*incl|c/\s*i\.?v\.?a|precio\s+final)", re.I)
_EXCLUDED_KW = re.compile(
    r"(sin\s*i\.?\s*v\.?\s*a|s/\s*i\.?v\.?a|\bneto\b|\+\s*i\.?v\.?a)", re.I)


@dataclass
class _Line:
    code: str | None
    description: str
    quantity: float
    unit_price: float | None   # precio unitario tal cual figura (lista)
    total: float | None
    y: float = 0.0

    def effective_unit(self) -> float | None:
        """total / cantidad: absorbe descuentos por renglón. Si no hay total,
        el precio de lista."""
        if self.total is not None and self.quantity:
            return self.total / self.quantity
        return self.unit_price


@dataclass
class _Doc:
    source: str
    lines: list[_Line] = field(default_factory=list)
    footer_numbers: list[tuple[str, float]] = field(default_factory=list)  # (texto, valor)
    text: str = ""
    decimal_sep: str = "."
    header_iva: bool | None = None  # Excel: lo dice el encabezado de la columna
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

_HEADER_COLS = {
    "qty": ("cantidad", "cant", "cant."),
    "desc": ("descripcion", "articulo", "detalle", "producto"),
    "code": ("codigo", "cod", "cod."),
    "unit": ("unitario", "p.unit", "precio"),
    "total": ("total", "importe"),
}


def _group_rows(words: list, tol: float = 4.0) -> list[list]:
    """Agrupa palabras de PyMuPDF en filas por cercanía del centro Y.

    Tolerancia > 1 línea de base: en algunos reportes la cantidad queda 1pt
    más abajo que la descripción del mismo renglón."""
    items = sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    rows: list[list] = []
    centers: list[float] = []
    for w in items:
        yc = (w[1] + w[3]) / 2
        if rows and abs(yc - centers[-1]) <= tol:
            rows[-1].append(w)
            n = len(rows[-1])
            centers[-1] = centers[-1] + (yc - centers[-1]) / n
        else:
            rows.append([w])
            centers.append(yc)
    return [sorted(r, key=lambda w: w[0]) for r in rows]


def _find_header(rows: list[list]) -> tuple[int, dict[str, tuple[float, float]]] | None:
    """Fila de encabezado de la tabla: la que nombra cantidad + total/unitario."""
    for i, row in enumerate(rows):
        cols: dict[str, tuple[float, float]] = {}
        for w in row:
            t = _norm(w[4]).strip(":")
            for key, names in _HEADER_COLS.items():
                if t in names and key not in cols:
                    cols[key] = (w[0], w[2])
        if "qty" in cols and ("total" in cols or "unit" in cols):
            return i, cols
    return None


def _parse_pdf(data: bytes) -> _Doc:
    import fitz  # PyMuPDF

    doc = _Doc(source="pdf")
    pdf = fitz.open(stream=data, filetype="pdf")
    all_text: list[str] = []
    pages_rows: list[list[list]] = []
    for page in pdf:
        words = page.get_text("words")
        all_text.append(page.get_text())
        pages_rows.append(_group_rows(words))
    doc.text = "\n".join(all_text)
    if not doc.text.strip():
        doc.warnings.append(
            "El PDF no tiene texto (¿es un escaneo?). Subí el PDF original del "
            "proveedor o un Excel.")
        return doc

    doc.decimal_sep = _detect_decimal_sep(
        [w[4] for rows in pages_rows for r in rows for w in r if _is_num(w[4])])

    for rows in pages_rows:
        found = _find_header(rows)
        if found is None:
            continue
        h_idx, cols = found
        qty_x = cols["qty"]
        desc_x0 = cols.get("desc", (0, 0))[0]
        # Columnas numéricas a la derecha de la descripción: todo lo que esté
        # a la izquierda de la primera de ellas es texto de la descripción.
        num_cols = [cols[k][0] for k in ("qty", "unit", "total") if k in cols
                    and cols[k][0] > desc_x0]
        money_x0 = min(num_cols) - 30 if num_cols else None

        last: _Line | None = None
        for row in rows[h_idx + 1:]:
            row_text = " ".join(w[4] for w in row)
            nums = [w for w in row if _is_num(w[4])]
            # Cantidad: el número más cercano a la columna "Cantidad".
            qty_w = None
            if nums:
                cand = min(nums, key=lambda w: abs((w[0] + w[2]) / 2 - (qty_x[0] + qty_x[1]) / 2))
                if abs(cand[0] - qty_x[0]) < 45:
                    qty_w = cand
            money = [w for w in nums if w is not qty_w and (money_x0 is None or w[0] >= money_x0)]
            text_words = [w for w in row if w is not qty_w and w not in money
                          and w[4] != "$"]
            desc = " ".join(w[4] for w in text_words).strip()
            letters = sum(c.isalpha() for c in desc)

            # Los precios siempre se imprimen con decimales: así se descartan
            # teléfonos, números de hoja, CBU, etc. que caen en esas columnas.
            priced = any(re.search(r"[.,]\d", w[4]) for w in money)
            is_item = (len(money) >= 2 or (len(money) == 1 and qty_w is not None)) \
                and priced and letters >= 3 and not _TOTALS_KW.match(_norm(desc)) \
                and not _STOP_KW.search(row_text)
            if is_item:
                code = None
                if text_words and "code" in cols and abs(text_words[0][0] - cols["code"][0]) < 20 \
                        and any(c.isdigit() for c in text_words[0][4]):
                    code = text_words[0][4]
                    desc = " ".join(w[4] for w in text_words[1:]).strip()
                m = _CODE_PREFIX.match(desc)
                if code is None and m:
                    code, desc = m.group(1), m.group(2)
                vals = [_to_float(w[4], doc.decimal_sep) for w in money]
                vals = [v for v in vals if v is not None]
                qty = _to_float(qty_w[4], doc.decimal_sep) if qty_w else 1.0
                last = _Line(
                    code=code,
                    description=desc.rstrip(" ,"),
                    quantity=qty or 1.0,
                    unit_price=vals[0] if vals else None,
                    total=vals[-1] if len(vals) >= 2 else None,
                    y=row[0][1],
                )
                doc.lines.append(last)
                continue

            # Continuación de la descripción ("Varios" en la línea de abajo).
            if last is not None and not nums and letters and not _STOP_KW.search(row_text) \
                    and row[0][1] - last.y < 30 and row[0][0] >= desc_x0 - 10:
                last.description = f"{last.description} {desc}".strip().rstrip(" ,")
                last.y = row[0][1]
                continue

            if nums:
                v = _to_float(nums[-1][4], doc.decimal_sep)
                if v is not None:
                    doc.footer_numbers.append((_norm(row_text), v))
            last = None if _STOP_KW.search(row_text) else last

    if not doc.lines:
        doc.warnings.append(
            "No se encontró la tabla de artículos (falta un encabezado con "
            "'Cantidad' y 'Total'/'Unitario').")
    return doc


# ---------------------------------------------------------------------------
# Excel / CSV
# ---------------------------------------------------------------------------

_XL_DESC = ("desc", "articulo", "producto", "detalle", "insumo", "material", "nombre", "item")
_XL_PRICE = ("precio", "costo", "unit", "importe", "valor", "p.u", "pu")
_XL_CODE = ("codigo", "cod", "id", "sku")
_XL_QTY = ("cantidad", "cant")
_XL_UNIT = ("um", "u.m", "unidad", "medida", "presentacion", "unid")


def _hdr_score(h: str, keys: tuple[str, ...]) -> bool:
    words = re.split(r"[^a-z0-9.]+", h)
    return any(k in words or h.startswith(k) for k in keys)


def _parse_table(rows: list[list], doc: _Doc) -> None:
    best = None
    for i, row in enumerate(rows[:30]):
        hdr = [_norm(str(c)) if c is not None else "" for c in row]
        d = [j for j, h in enumerate(hdr) if h and _hdr_score(h, _XL_DESC)]
        p = [j for j, h in enumerate(hdr) if h and _hdr_score(h, _XL_PRICE) and "total" not in h]
        if not p:
            p = [j for j, h in enumerate(hdr) if h and _hdr_score(h, _XL_PRICE)]
        if d and p:
            best = (i, hdr, d, p)
            break
    if best is None:
        doc.warnings.append(
            "No se encontró el encabezado (se necesita una columna de descripción "
            "y una de precio).")
        return
    h_idx, hdr, d_cols, p_cols = best
    # Si hay varias columnas de precio, preferir la unitaria / neta.
    p_col = next((j for j in p_cols if "unit" in hdr[j] or "neto" in hdr[j]), p_cols[0])
    # Prioridad por palabra clave: "articulo nombre" le gana a "tipo item".
    d_col = min(d_cols, key=lambda j: next(
        (k for k, key in enumerate(_XL_DESC) if _hdr_score(hdr[j], (key,))), len(_XL_DESC)))
    c_col = next((j for j, h in enumerate(hdr) if h and j not in (d_col, p_col)
                  and _hdr_score(h, _XL_CODE)), None)
    q_col = next((j for j, h in enumerate(hdr) if h and _hdr_score(h, _XL_QTY)), None)
    u_col = next((j for j, h in enumerate(hdr) if h and j not in (d_col, p_col)
                  and _hdr_score(h, _XL_UNIT)), None)

    price_hdr = hdr[p_col]
    if _EXCLUDED_KW.search(price_hdr) or "neto" in price_hdr:
        doc.header_iva = False
    elif _INCLUDED_KW.search(price_hdr):
        doc.header_iva = True

    for row in rows[h_idx + 1:]:
        def cell(j):
            return row[j] if j is not None and j < len(row) else None

        desc = cell(d_col)
        price = cell(p_col)
        if desc is None or str(desc).strip() == "":
            continue
        if isinstance(price, str):
            price = _to_float(price, _detect_decimal_sep([price]))
        if not isinstance(price, (int, float)) or price <= 0:
            continue
        qty = cell(q_col)
        if isinstance(qty, str):
            qty = _to_float(qty, _detect_decimal_sep([qty]))
        code = cell(c_col)
        unit = cell(u_col)
        ln = _Line(
            code=str(code).strip() if code not in (None, "") else None,
            description=str(desc).strip(),
            quantity=float(qty) if isinstance(qty, (int, float)) and qty > 0 else 1.0,
            unit_price=float(price),
            total=None,
        )
        ln.unit_hint = str(unit).strip() if unit not in (None, "") else None  # type: ignore[attr-defined]
        doc.lines.append(ln)


def _parse_excel(data: bytes) -> _Doc:
    import openpyxl

    doc = _Doc(source="excel")
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        before = len(doc.lines)
        sub = _Doc(source="excel")
        _parse_table(rows, sub)
        doc.lines.extend(sub.lines)
        if doc.header_iva is None:
            doc.header_iva = sub.header_iva
        if len(doc.lines) > before:
            break  # primera hoja con tabla
    if not doc.lines:
        doc.warnings.append("No se encontraron renglones con descripción y precio en el Excel.")
    return doc


def _parse_csv(data: bytes) -> _Doc:
    doc = _Doc(source="excel")
    text = data.decode("utf-8-sig", errors="replace")
    dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t") if text.strip() else csv.excel
    rows = [r for r in csv.reader(io.StringIO(text), dialect)]
    _parse_table(rows, doc)
    return doc


# ---------------------------------------------------------------------------
# IVA
# ---------------------------------------------------------------------------

def _close(a: float, b: float, rel: float = 0.005) -> bool:
    return abs(a - b) <= max(1.0, abs(b) * rel)


def _detect_iva(doc: _Doc, lines_sum: float) -> tuple[bool | None, str, float | None]:
    """(incluido?, método, total del documento)."""
    totals = [v for t, v in doc.footer_numbers if re.search(r"\btotal\b", t) and "sub" not in t]
    doc_total = max(totals) if totals else None

    if lines_sum > 0:
        for _, v in doc.footer_numbers:
            if _close(v, lines_sum * (1 + IVA_RATE)):
                return False, "aritmética: suma de renglones + 21% = total", v
        for t, v in doc.footer_numbers:
            if re.search(r"i\.?\s*v\.?\s*a", t) and _close(v, lines_sum * IVA_RATE):
                return False, "aritmética: renglón de IVA 21% sobre la suma", doc_total
    if doc.header_iva is not None:
        return doc.header_iva, "encabezado de la columna de precio", doc_total
    if _INCLUDED_KW.search(doc.text):
        return True, "el documento dice 'con IVA'", doc_total
    if _EXCLUDED_KW.search(doc.text):
        return False, "el documento dice 'sin IVA'", doc_total
    return None, "no determinado", doc_total


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

_EMAIL_DOMAIN = re.compile(r"[\w.+-]+@([\w-]+)\.", re.I)
_WEB_DOMAIN = re.compile(r"\b(?:www\.)?([\w-]+)\.com(?:\.ar)?\b", re.I)
_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")


def parse_price_list(filename: str, data: bytes, iva_included: bool | None = None) -> dict:
    """Parsea una lista de precios. `iva_included` fuerza la base de IVA
    (si None se detecta). Nunca lanza por contenido: los problemas van a
    `warnings` y `lines` puede quedar vacío."""
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        doc = _parse_pdf(data)
    elif name.endswith((".xlsx", ".xlsm")):
        doc = _parse_excel(data)
    elif name.endswith(".csv"):
        doc = _parse_csv(data)
    else:
        raise ValueError("Formato no soportado: subí un PDF, Excel (.xlsx) o CSV.")

    lines_sum = round(sum((ln.total if ln.total is not None
                           else (ln.unit_price or 0) * ln.quantity) for ln in doc.lines), 2)
    detected, method, doc_total = _detect_iva(doc, lines_sum)
    if iva_included is not None:
        included, method = iva_included, "indicado por el usuario"
    elif detected is None:
        included = False
        doc.warnings.append(
            "No se pudo determinar si los precios incluyen IVA: se asumen SIN IVA.")
    else:
        included = detected
    divisor = 1 + IVA_RATE if included else 1.0

    out_lines = []
    for i, ln in enumerate(doc.lines, start=1):
        eff = ln.effective_unit()
        out_lines.append({
            "row": i,
            "code": ln.code,
            "description": ln.description,
            "quantity": ln.quantity,
            "unit_price": round(ln.unit_price, 4) if ln.unit_price is not None else None,
            "total": round(ln.total, 4) if ln.total is not None else None,
            "unit_price_net": round(eff / divisor, 2) if eff is not None else None,
            "presentation": parse_presentation(ln.description, getattr(ln, "unit_hint", None)),
        })

    check = None
    if doc_total is not None and lines_sum > 0:
        expected = lines_sum * (1 if included else 1 + IVA_RATE)
        check = "ok" if _close(doc_total, expected, 0.01) else "mismatch"
        if check == "mismatch":
            doc.warnings.append(
                f"La suma de renglones ({lines_sum:,.2f}) no cierra con el total del "
                f"documento ({doc_total:,.2f}). Revisá que no falten renglones.")

    supplier = None
    m = _EMAIL_DOMAIN.search(doc.text) or _WEB_DOMAIN.search(doc.text)
    if m:
        supplier = m.group(1).capitalize()
    date = None
    m = _DATE.search(doc.text)
    if m:
        date = f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"

    return {
        "source": doc.source,
        "filename": filename,
        "supplier": supplier,
        "document_date": date,
        "number_format": "1.234,56" if doc.decimal_sep == "," else "1,234.56",
        "iva": {"included": included, "rate": IVA_RATE, "method": method},
        "totals": {"lines_sum": lines_sum, "document_total": doc_total, "check": check},
        "lines": out_lines,
        "warnings": doc.warnings,
    }
