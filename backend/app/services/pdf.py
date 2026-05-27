from pathlib import Path

import fitz  # PyMuPDF


def rasterize(pdf_path: str | Path, page_index: int = 0, dpi: int = 300) -> bytes:
    """Rasteriza una página del PDF a PNG en memoria."""
    doc = fitz.open(pdf_path)
    try:
        if page_index >= doc.page_count:
            raise ValueError(f"Página {page_index} fuera de rango (PDF tiene {doc.page_count})")
        page = doc[page_index]
        zoom = dpi / 72
        matrix = fitz.Matrix(zoom, zoom)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        return pixmap.tobytes("png")
    finally:
        doc.close()


def page_count(pdf_path: str | Path) -> int:
    doc = fitz.open(pdf_path)
    try:
        return doc.page_count
    finally:
        doc.close()


# --------------------------------------------------------------------------------------
# Heuristico de "Paginas recomendadas para marcar muros/recintos"
#
# Combina cinco senales:
#  1. Rotulo (title block): texto en la esquina inferior-derecha de la pagina.
#     Es el indicador mas fuerte — si dice "Planilla de aberturas" o "Detalle",
#     se descarta directamente. Si dice "Planta de arquitectura", se acepta.
#  2. Lista negra/blanca de palabras a lo largo del texto de la pagina.
#  3. Conteo de menciones de recintos (dormitorio, cocina, etc.) — solo
#     vale si superan un umbral, sino una tabla con dos celdas "DORMITORIO"
#     falsea el resultado.
#  4. Firma de tabla: muchas lineas horizontales cortas equiespaciadas indican
#     una tabla (planilla), no una planta.
#  5. Poligonos cerrados de area significativa: las plantas tienen muchos
#     (recintos), las planillas/detalles tienen pocos.
# --------------------------------------------------------------------------------------

# Palabras cuya presencia en el rotulo DESCARTA la pagina directamente.
HARD_NEGATIVE_TITLE = [
    "planilla", "aberturas", "carpinteria", "carpinteria",
    "detalle", "detalles", "corte", "cortes", "fachada", "fachadas",
    "elevacion", "elevaciones", "vista", "vistas",
    "esquema", "memoria", "replanteo", "luceras", "ventiluz",
    "sanitaria", "electrica", "eléctrica", "estructura", "estructuras",
    "cimentacion", "cimentación", "fundacion", "fundación",
    "instalacion", "instalación", "techo", "cubierta", "pluvial",
    "cenefa", "tapacanto",
]

# Palabras cuya presencia en el rotulo CONFIRMA que es una planta.
# Incluye variantes "plano de arquitectura" (singular) y "planta de arquitectura"
# (femenino) — ambas se usan en planos reales en Argentina.
HARD_POSITIVE_TITLE = [
    "plano de arquitectura", "plano arquitectura",
    "planta de arquitectura", "planta arquitectura",
    "planta general", "planta tipo", "planta de distribucion",
    "planta de distribución", "planta baja", "planta alta",
    "planta primer piso", "planta segundo piso", "planta de techos",
    "layout", "floor plan",
    "distribucion", "distribución",
]

# Menciones de recintos (necesitan >= MIN_ROOM_MENTIONS apariciones para contar).
ROOM_KEYWORDS = [
    "dormitorio", "cocina", "baño", "bano", "comedor", "estar", "living",
    "toilette", "suite", "vestidor", "playroom", "cochera", "habitacion",
    "habitación", "lavadero", "patio", "balcon", "balcón",
]
MIN_ROOM_MENTIONS = 3


def _title_block_text(page) -> str:
    """Extrae el texto del rotulo (esquina inferior-derecha de la pagina).

    El rotulo arquitectonico tipico ocupa el 30-40% inferior-derecho. Tomamos
    la mitad derecha y el 30% inferior y concatenamos todo el texto que cae ahi.
    Retorna en minusculas para comparacion.
    """
    rect = page.rect
    x_threshold = rect.x0 + rect.width * 0.5
    y_threshold = rect.y0 + rect.height * 0.70
    parts: list[str] = []
    try:
        blocks = page.get_text("blocks") or []
    except Exception:  # noqa: BLE001
        return ""
    for b in blocks:
        if len(b) < 5:
            continue
        x0, y0, x1, y1, text = b[0], b[1], b[2], b[3], b[4]
        if x1 > x_threshold and y1 > y_threshold and isinstance(text, str):
            parts.append(text)
    return " ".join(parts).lower()


def _table_grid_score(page) -> tuple[bool, int]:
    """Detecta firma de tabla: muchas lineas horizontales similares y cortas.

    Una tabla tiene celdas regulares -> longitudes con baja varianza.
    Una planta tiene muros de tamanos variados -> alta varianza.

    Filtros:
     - Menos de 40 horizontales: no hay como ser tabla.
     - Mas de 800 horizontales: es una planta densa (cada muro suma lineas).
     - En el rango medio: tabla si la mediana es chica y la varianza relativa
       es baja (todas las celdas miden parecido).

    Retorna (es_probable_tabla, total_lineas_horizontales).
    """
    horizontals: list[float] = []
    try:
        drawings = page.get_drawings() or []
    except Exception:  # noqa: BLE001
        return (False, 0)
    for d in drawings:
        for item in d.get("items", []) or []:
            if not item:
                continue
            kind = item[0]
            try:
                if kind == "l":
                    p1, p2 = item[1], item[2]
                    if abs(p2.y - p1.y) < 0.5:
                        horizontals.append(abs(p2.x - p1.x))
                elif kind == "re":
                    r = item[1]
                    width = float(r.x1 - r.x0)
                    horizontals.append(width)
                    horizontals.append(width)
            except Exception:  # noqa: BLE001
                continue
    total = len(horizontals)
    # Muy pocas: no es tabla
    if total < 40:
        return (False, total)
    # Muchisimas: planta densa, no tabla
    if total > 800:
        return (False, total)
    horizontals.sort()
    median = horizontals[total // 2]
    page_width = float(page.rect.width) or 1.0
    # Varianza relativa baja = todas las lineas miden parecido (celdas)
    mean = sum(horizontals) / total
    variance = sum((x - mean) ** 2 for x in horizontals) / total
    stdev = variance ** 0.5
    relative_stdev = (stdev / mean) if mean > 0 else 1.0
    is_table = (
        median < page_width * 0.15
        and total > 60
        and relative_stdev < 0.7
    )
    return (is_table, total)


def _large_closed_polygons(page) -> int:
    """Cuenta paths de drawing con un bounding box "tipo recinto".

    Un recinto tipico ocupa entre 0.3% y 25% del area de la pagina. Las
    planillas tienen muchos rectangulos chicos (celdas) y las plantas tienen
    polygonos en ese rango.
    """
    try:
        drawings = page.get_drawings() or []
    except Exception:  # noqa: BLE001
        return 0
    page_area = float(page.rect.width) * float(page.rect.height) or 1.0
    min_area = page_area * 0.003
    max_area = page_area * 0.25
    count = 0
    for d in drawings:
        rect = d.get("rect")
        if rect is None:
            continue
        try:
            area = float(rect.width) * float(rect.height)
        except Exception:  # noqa: BLE001
            continue
        if min_area < area < max_area:
            # Debe tener varios segmentos para parecer un poligono real
            items = d.get("items", []) or []
            if len(items) >= 3:
                count += 1
    return count


def recommend_pages(pdf_path: str | Path) -> list[dict]:
    """Analiza las paginas del PDF y devuelve cuales son plantas de arquitectura.

    Usa cinco senales combinadas: rotulo, lista negra/blanca de palabras,
    menciones de recintos, firma de tabla y poligonos cerrados grandes.
    """
    doc = fitz.open(pdf_path)
    recommendations: list[dict] = []
    try:
        for i in range(doc.page_count):
            page = doc.load_page(i)
            full_text = (page.get_text("text") or "").lower()
            title_text = _title_block_text(page)

            title_negative = [k for k in HARD_NEGATIVE_TITLE if k in title_text]
            title_positive = [k for k in HARD_POSITIVE_TITLE if k in title_text]

            # 1) Veto fuerte: si el rotulo dice "planilla", "detalle", "corte"...
            #    descartamos sin importar otras senales. El rotulo es definitivo.
            if title_negative and not title_positive:
                recommendations.append({
                    "page": i + 1,
                    "score": -100,
                    "recommended": False,
                    "reason": f"Rotulo: {', '.join(sorted(set(title_negative))[:3])}",
                })
                continue

            # 2) Conteo de menciones de recintos (con frecuencia minima)
            room_mentions = sum(full_text.count(k) for k in ROOM_KEYWORDS)

            # 3) Senales geometricas
            is_table, horiz_count = _table_grid_score(page)
            polygons = _large_closed_polygons(page)
            try:
                drawings_count = len(page.get_drawings() or [])
            except Exception:  # noqa: BLE001
                drawings_count = 0

            # 4) Score combinado
            score = 0
            if title_positive:
                score += 60  # rotulo positivo es muy fuerte
            if room_mentions >= MIN_ROOM_MENTIONS:
                score += min(room_mentions * 3, 30)
            score += min(polygons * 2, 30)

            # Penalizaciones
            if is_table:
                score -= 50
            if drawings_count < 10:
                score -= 50
            # Penalizacion suave por palabras negativas en el cuerpo
            body_negative = [k for k in HARD_NEGATIVE_TITLE if k in full_text]
            if body_negative and not title_positive:
                score -= min(len(body_negative) * 5, 30)

            recommended = score >= 30

            reasons: list[str] = []
            if title_positive:
                reasons.append(f"Rotulo: {', '.join(sorted(set(title_positive))[:2])}")
            if room_mentions >= MIN_ROOM_MENTIONS:
                reasons.append(f"{room_mentions} menciones de recintos")
            if polygons >= 5:
                reasons.append(f"{polygons} poligonos tipo recinto")
            if is_table:
                reasons.append("firma de tabla")
            if drawings_count < 10:
                reasons.append("pocos dibujos")
            if body_negative and not title_positive:
                reasons.append(
                    f"keywords negativos: {', '.join(sorted(set(body_negative))[:2])}"
                )

            recommendations.append({
                "page": i + 1,
                "score": score,
                "recommended": recommended,
                "reason": ", ".join(reasons) or "Sin senales relevantes",
            })
    finally:
        doc.close()
    return recommendations

