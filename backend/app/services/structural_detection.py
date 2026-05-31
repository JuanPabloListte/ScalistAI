"""Detectores clásicos (OpenCV) para elementos estructurales:

- `detect_columns`: columnas (rectángulos / círculos rellenos etiquetados C\\d+ / P\\d+).
- `detect_beams`: vigas (rectángulos finos largos etiquetados V\\d+).
- `detect_roofs`: techos / losas (polígonos cerrados etiquetados L\\d+, LOSA/LOZA).

El enfoque es **label-driven**: primero extraemos las etiquetas de texto del PDF
(que son confiables: si dice "C3" es porque hay una columna ahí), y después
buscamos la geometría más probable cerca de cada etiqueta. Esto evita las
falsas detecciones que tendría un connected-components puro sobre el raster
(que captura texto, cotas, hatching, etc.).

El formato de salida coincide con `detect_walls` / `detect_rooms` —
`auto_detect_pipeline._create_*_elements` los persiste como DetectedElement
con `source="ai"`.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Iterable

import fitz


# Patrones de label aceptados por cada tipo. Toleramos separadores (espacio,
# punto, guión) entre la letra y el número porque las fuentes CAD a veces
# espacian raro.
COLUMN_LABEL_PATTERNS = (
    re.compile(r"^\s*[cp][\s\.\-]*\d+[a-z']?\s*$", re.IGNORECASE),
    re.compile(r"^\s*col(?:umna)?[\s\.\-]*\d*\s*$", re.IGNORECASE),
    re.compile(r"^\s*pilar[\s\.\-]*\d*\s*$", re.IGNORECASE),
)
BEAM_LABEL_PATTERNS = (
    re.compile(r"^\s*v[\s\.\-]*\d+[a-z']?\s*$", re.IGNORECASE),
    re.compile(r"^\s*viga[\s\.\-]*\d*\s*$", re.IGNORECASE),
)
ROOF_LABEL_PATTERNS = (
    re.compile(r"^\s*l[\s\.\-]*\d+[a-z']?\s*$", re.IGNORECASE),
    re.compile(r"^\s*lo[sz]a[\s\.\-]*\d*\s*$", re.IGNORECASE),
)


def _render_page(pdf_path: str | Path, page_index: int, dpi: int):
    """Renderiza la página a (ndarray RGB uint8, text_dict). Devuelve None en
    los dos slots si la página está fuera de rango."""
    import numpy as np

    doc = fitz.open(pdf_path)
    try:
        if page_index < 0 or page_index >= doc.page_count:
            return None, None
        page = doc.load_page(page_index)
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        img = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
            pixmap.height, pixmap.width, 3
        )
        text_page = page.get_text("dict")
        return img, text_page
    finally:
        doc.close()


def _collect_pattern_labels(
    text_page: dict, factor: float, patterns: Iterable[re.Pattern]
) -> list[dict]:
    """Extrae spans de texto que matcheen cualquiera de los regex dados.

    Devuelve dicts con `text`, `cx_px`, `cy_px`, `bbox_px` ya escalados al
    raster (multiplicados por `factor` = dpi/72).
    """
    pats = tuple(patterns)
    labels: list[dict] = []
    seen: set[tuple[str, float, float]] = set()
    for block in text_page.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = (span.get("text") or "").strip()
                if not text or len(text) > 12:
                    continue
                if not any(p.match(text) for p in pats):
                    continue
                x0, y0, x1, y1 = span["bbox"]
                cx = (x0 + x1) / 2.0 * factor
                cy = (y0 + y1) / 2.0 * factor
                # Deduplicar: el mismo label dibujado dos veces casi encima
                # cuenta como uno.
                key = (text.upper(), round(cx, 0), round(cy, 0))
                if key in seen:
                    continue
                seen.add(key)
                labels.append({
                    "text": text,
                    "cx_px": cx,
                    "cy_px": cy,
                    "bbox_px": (
                        x0 * factor, y0 * factor, x1 * factor, y1 * factor,
                    ),
                })
    return labels


# ----------------------------------------------------------------------
# Columnas
# ----------------------------------------------------------------------
def detect_columns(
    pdf_path: str | Path,
    page_index: int,
    dpi: int,
    px_per_m: float | None = None,
) -> list[dict]:
    """Detecta candidatos a Columnas.

    Pipeline:
      1. Extrae labels C\\d+ / P\\d+ / COL / PILAR del texto vectorial.
      2. Binariza el raster (Otsu inverso) y encuentra componentes conexos.
      3. Filtra componentes por dimensión típica de columna (15-80 cm de lado,
         área 0.03-1.0 m², solidez > 0.6) y aspect ratio cercano a 1.
      4. Para cada label, busca el blob filtrado más cercano dentro de 2 m
         y lo asigna como columna. Un mismo blob no puede asignarse a dos
         labels distintos.
    """
    import cv2
    import numpy as np

    if not pdf_path:
        return []
    scale = px_per_m if (px_per_m and px_per_m > 0) else 150.0
    factor = dpi / 72.0

    img, text_page = _render_page(pdf_path, page_index, dpi)
    if img is None or text_page is None:
        return []

    column_labels = _collect_pattern_labels(
        text_page, factor, COLUMN_LABEL_PATTERNS
    )
    if not column_labels:
        return []

    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    _, thresh = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )

    num_labels, _labels_arr, stats, centroids = cv2.connectedComponentsWithStats(
        thresh, connectivity=8
    )

    min_dim_m, max_dim_m = 0.15, 0.80
    min_area_m, max_area_m = 0.03, 1.0
    min_solidity = 0.60

    blobs: list[dict] = []
    for i in range(1, num_labels):
        x, y, w, h, area = stats[i]
        w_m = w / scale
        h_m = h / scale
        area_m = area / (scale * scale)
        if not (min_dim_m <= w_m <= max_dim_m and min_dim_m <= h_m <= max_dim_m):
            continue
        if not (min_area_m <= area_m <= max_area_m):
            continue
        # Aspecto cuadrado-ish: w/h en [0.4, 2.5]. Filtra letras alargadas.
        ratio = max(w_m, h_m) / max(min(w_m, h_m), 1e-3)
        if ratio > 2.5:
            continue
        bbox_area = max(w * h, 1)
        if area / bbox_area < min_solidity:
            continue
        cx, cy = centroids[i]
        blobs.append({
            "x": int(x), "y": int(y), "w": int(w), "h": int(h),
            "cx": float(cx), "cy": float(cy),
            "area_m2": area_m,
        })

    if not blobs:
        return []

    max_dist_px = 2.0 * scale
    candidates: list[dict] = []
    matched: set[int] = set()
    for label in column_labels:
        lx, ly = label["cx_px"], label["cy_px"]
        best_idx, best_d = -1, float("inf")
        for idx, blob in enumerate(blobs):
            if idx in matched:
                continue
            d = math.hypot(lx - blob["cx"], ly - blob["cy"])
            if d < best_d and d <= max_dist_px:
                best_d = d
                best_idx = idx
        if best_idx < 0:
            continue
        matched.add(best_idx)
        blob = blobs[best_idx]
        x, y, w, h = blob["x"], blob["y"], blob["w"], blob["h"]
        pts = [
            float(x), float(y),
            float(x + w), float(y),
            float(x + w), float(y + h),
            float(x), float(y + h),
        ]
        pts = [round(p, 2) for p in pts]
        candidates.append({
            "id": f"column_candidate_{len(candidates) + 1}",
            "type": "column",
            "geometry": {
                "points": pts,
                "label": label["text"].upper(),
            },
            "length_m": None,
            "area_m2": round(blob["area_m2"], 3),
            "height_m": 2.8,
            "page": page_index + 1,
        })
    return candidates


# ----------------------------------------------------------------------
# Vigas
# ----------------------------------------------------------------------
def detect_beams(
    pdf_path: str | Path,
    page_index: int,
    dpi: int,
    px_per_m: float | None = None,
) -> list[dict]:
    """Detecta candidatos a Vigas.

    Pipeline:
      1. Extrae labels V\\d+ / VIGA del texto vectorial.
      2. Binariza y busca componentes conexos.
      3. Filtra por dimensiones de viga: lado corto 12-90 cm, lado largo
         0.8-25 m, ratio largo/corto > 3 (forma alargada).
      4. Para cada label asigna el blob alargado más cercano cuyo bbox
         envuelve o queda muy cerca del label.
    """
    import cv2
    import numpy as np

    if not pdf_path:
        return []
    scale = px_per_m if (px_per_m and px_per_m > 0) else 150.0
    factor = dpi / 72.0

    img, text_page = _render_page(pdf_path, page_index, dpi)
    if img is None or text_page is None:
        return []

    beam_labels = _collect_pattern_labels(text_page, factor, BEAM_LABEL_PATTERNS)
    if not beam_labels:
        return []

    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    _, thresh = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )

    num_labels, _labels_arr, stats, centroids = cv2.connectedComponentsWithStats(
        thresh, connectivity=8
    )

    min_minor_m, max_minor_m = 0.12, 0.90
    min_major_m, max_major_m = 0.80, 25.0
    min_aspect = 3.0
    min_density = 0.30  # rect outlineado con hatching debería superarlo

    blobs: list[dict] = []
    for i in range(1, num_labels):
        x, y, w, h, area = stats[i]
        w_m = w / scale
        h_m = h / scale
        major = max(w_m, h_m)
        minor = min(w_m, h_m)
        if not (min_minor_m <= minor <= max_minor_m):
            continue
        if not (min_major_m <= major <= max_major_m):
            continue
        if minor < 1e-3 or major / minor < min_aspect:
            continue
        bbox_area = max(w * h, 1)
        if area / bbox_area < min_density:
            continue
        cx, cy = centroids[i]
        blobs.append({
            "x": int(x), "y": int(y), "w": int(w), "h": int(h),
            "cx": float(cx), "cy": float(cy),
            "major_m": major,
            "w_m": w_m, "h_m": h_m,
            "horizontal": w > h,
        })

    if not blobs:
        return []

    candidates: list[dict] = []
    matched: set[int] = set()
    # Para vigas el match debe ser "label sobre la viga" o muy cerca de uno de
    # sus extremos. Usamos una banda alrededor del bbox.
    margin_px = 0.50 * scale
    max_center_dist_px = 4.0 * scale

    for label in beam_labels:
        lx, ly = label["cx_px"], label["cy_px"]
        best_idx, best_d = -1, float("inf")
        for idx, blob in enumerate(blobs):
            if idx in matched:
                continue
            x0 = blob["x"] - margin_px
            y0 = blob["y"] - margin_px
            x1 = blob["x"] + blob["w"] + margin_px
            y1 = blob["y"] + blob["h"] + margin_px
            if not (x0 <= lx <= x1 and y0 <= ly <= y1):
                continue
            d = math.hypot(lx - blob["cx"], ly - blob["cy"])
            if d < best_d and d <= max_center_dist_px:
                best_d = d
                best_idx = idx
        if best_idx < 0:
            continue
        matched.add(best_idx)
        blob = blobs[best_idx]
        x, y, w, h = blob["x"], blob["y"], blob["w"], blob["h"]
        pts = [
            float(x), float(y),
            float(x + w), float(y),
            float(x + w), float(y + h),
            float(x), float(y + h),
        ]
        pts = [round(p, 2) for p in pts]
        candidates.append({
            "id": f"beam_candidate_{len(candidates) + 1}",
            "type": "beam",
            "geometry": {
                "points": pts,
                "label": label["text"].upper(),
            },
            "length_m": round(blob["major_m"], 2),
            "area_m2": round(blob["w_m"] * blob["h_m"], 3),
            "height_m": 0.40,  # peralte default; el usuario puede ajustar
            "page": page_index + 1,
        })
    return candidates


# ----------------------------------------------------------------------
# Techos / Losas
# ----------------------------------------------------------------------
def detect_roofs(
    pdf_path: str | Path,
    page_index: int,
    dpi: int,
    px_per_m: float | None = None,
) -> list[dict]:
    """Detecta candidatos a Techos / Losas.

    Reutiliza el mismo enfoque watershed que `detect_rooms`, pero usa labels
    L\\d+ / LOSA / LOZA como semillas en lugar de keywords de ambientes.

    Esto funciona bien en planos estructurales donde cada losa está rotulada
    y delimitada por muros / vigas perimetrales.
    """
    import cv2
    import numpy as np

    # Imports diferidos al runtime para evitar ciclos y para que el costo de
    # importar OpenCV no pague en tests que no usan este detector.
    from app.services.wall_room_detection import (
        _build_wall_mask,
        _contour_to_points,
        _render_pdf_vector_walls,
        _segment_rooms_watershed,
    )

    if not pdf_path:
        return []
    scale = px_per_m if (px_per_m and px_per_m > 0) else 150.0
    factor = dpi / 72.0

    img, text_page = _render_page(pdf_path, page_index, dpi)
    if img is None or text_page is None:
        return []

    roof_labels = _collect_pattern_labels(text_page, factor, ROOF_LABEL_PATTERNS)
    if not roof_labels:
        return []

    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    raster_mask = _build_wall_mask(gray, scale)
    vector_mask = _render_pdf_vector_walls(
        pdf_path, page_index, dpi, min_stroke_pt=0.3
    )
    if vector_mask is not None:
        if vector_mask.shape != raster_mask.shape:
            vh, vw = raster_mask.shape
            vector_mask = cv2.resize(
                vector_mask, (vw, vh), interpolation=cv2.INTER_NEAREST
            )
        walls_mask = cv2.bitwise_or(raster_mask, vector_mask)
    else:
        walls_mask = raster_mask

    regions = _segment_rooms_watershed(walls_mask, roof_labels, scale)

    candidates: list[dict] = []
    for idx, region in enumerate(regions, start=1):
        label = region["label"]
        approx = region["contour"]
        candidates.append({
            "id": f"roof_candidate_{idx}",
            "type": "roof",
            "geometry": {
                "points": _contour_to_points(approx),
                "label": label["text"].upper(),
            },
            "length_m": None,
            "area_m2": round(region["area_m2"], 2),
            "height_m": 0.20,  # espesor default de losa
            "page": page_index + 1,
        })
    return candidates
