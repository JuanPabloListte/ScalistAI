"""Detección de aberturas (puertas y ventanas) por sus labels en el PDF.

Los planos arquitectónicos profesionales etiquetan cada abertura con códigos
estándar al lado del símbolo:

    P1, P2, P3...   → puertas (doors)
    V1, V2, V3...   → ventanas (windows)
    PV1, PV2, PV3... → puertas-ventana (sliding doors)
    PF, PF1...      → paños fijos / puertas fijas

PyMuPDF nos devuelve cada texto con su bounding box, así que podemos
proponer al usuario candidatos con posición aproximada y un ancho por defecto
según convenciones argentinas (puerta=0.80m, ventana=1.50m, ventanal=3.00m).

Para conseguir las dimensiones REALES habría que parsear la "planilla de
aberturas" del plano y cruzarla con cada label — eso queda para una iteración
posterior. Por ahora, ancho default + el usuario ajusta.
"""

import re
from pathlib import Path

import fitz

# (prefijo, regex anclado, type lógico, ancho_default_m, descripcion)
# El orden importa: PV antes que P, PF antes que P, para que matchee el prefijo más largo.
_PATTERNS: list[tuple[str, re.Pattern[str], str, float, str]] = [
    ("PV", re.compile(r"^PV\d+$", re.IGNORECASE), "sliding_door", 3.0, "Puerta-ventana"),
    ("PF", re.compile(r"^PF\d+$", re.IGNORECASE), "fixed_window", 1.5, "Paño fijo"),
    ("P", re.compile(r"^P\d+$", re.IGNORECASE), "door", 0.8, "Puerta"),
    ("V", re.compile(r"^V\d+$", re.IGNORECASE), "window", 1.5, "Ventana"),
]


def detect_opening_labels(
    pdf_path: str | Path,
    page_index: int,
    dpi: int,
    px_per_m: float | None = None,
    align_to_walls: bool = True,
) -> list[dict]:
    """Devuelve los candidatos de abertura encontrados como labels en el texto del PDF.

    Returns lista de dicts con:
      - label (str)          : el texto del label, ej "V1", "PV3"
      - subtype (str)        : door / window / sliding_door / fixed_window
      - description (str)    : "Puerta", "Ventana", etc. (display)
      - default_width_m (float): ancho por defecto sugerido en metros
      - bbox (list[4 float]) : [x0, y0, x1, y1] en píxeles del raster
      - cx, cy (float)       : centro del bbox en píxeles
      - orientation (str)    : "h" (horizontal) / "v" (vertical)
    """
    import math
    factor = dpi / 72.0
    doc = fitz.open(pdf_path)
    try:
        if page_index < 0 or page_index >= doc.page_count:
            return []
        page = doc.load_page(page_index)
        data = page.get_text("dict")
    finally:
        doc.close()

    results: list[dict] = []
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = (span.get("text") or "").strip()
                match = _classify(text)
                if match is None:
                    continue
                _prefix, _re, subtype, default_w, description = match
                x0, y0, x1, y1 = span["bbox"]
                bbox_px = [x0 * factor, y0 * factor, x1 * factor, y1 * factor]
                cx = (bbox_px[0] + bbox_px[2]) / 2
                cy = (bbox_px[1] + bbox_px[3]) / 2
                results.append(
                    {
                        "label": text.upper(),
                        "subtype": subtype,
                        "description": description,
                        "default_width_m": default_w,
                        "bbox": bbox_px,
                        "cx": round(cx, 2),
                        "cy": round(cy, 2),
                        "orientation": "h",
                    }
                )
    
    results = _dedupe(results)

    if align_to_walls and len(results) > 0:
        from app.services.wall_room_detection import detect_walls
        scale = px_per_m if (px_per_m and px_per_m > 0) else 150.0
        try:
            # Llamamos a detect_walls desactivando split_by_openings para evitar bucle infinito
            walls = detect_walls(pdf_path, page_index, dpi, px_per_m, split_by_openings=False)
        except Exception:
            walls = []

        if len(walls) > 0:
            max_dist_px = 1.5 * scale  # 1.5 metros máximo de distancia de proyección
            for c in results:
                cx, cy = c["cx"], c["cy"]
                best_wall = None
                best_proj = None
                best_dist = float("inf")

                for w in walls:
                    pts = w["geometry"]["points"]
                    x1, y1, x2, y2 = pts[0], pts[1], pts[2], pts[3]

                    dx = x2 - x1
                    dy = y2 - y1
                    line_len_sq = dx * dx + dy * dy
                    if line_len_sq == 0:
                        continue

                    t = ((cx - x1) * dx + (cy - y1) * dy) / line_len_sq
                    t = max(0.0, min(1.0, t))

                    proj_x = x1 + t * dx
                    proj_y = y1 + t * dy
                    dist = math.sqrt((cx - proj_x) ** 2 + (cy - proj_y) ** 2)

                    if dist < best_dist:
                        best_dist = dist
                        best_proj = (proj_x, proj_y)
                        best_wall = w

                if best_wall is not None and best_dist <= max_dist_px:
                    pts = best_wall["geometry"]["points"]
                    x1, y1, x2, y2 = pts[0], pts[1], pts[2], pts[3]
                    is_h = abs(x1 - x2) > abs(y1 - y2)
                    c["cx"] = round(best_proj[0], 2)
                    c["cy"] = round(best_proj[1], 2)
                    c["orientation"] = "h" if is_h else "v"

    return results


def _classify(text: str):
    """Devuelve la primera tupla de _PATTERNS que matchea, o None."""
    if not text or not text[0].isalpha():
        return None
    for entry in _PATTERNS:
        if entry[1].match(text):
            return entry
    return None


def _dedupe(candidates: list[dict]) -> list[dict]:
    """En CAD-exportados el mismo label aparece duplicado a veces. Eliminamos
    duplicados cuyo centro esté a < 6 px (a 150 DPI son ~1 mm de papel)."""
    out: list[dict] = []
    for c in candidates:
        is_dup = False
        for o in out:
            if c["label"] != o["label"]:
                continue
            if abs(c["cx"] - o["cx"]) < 6 and abs(c["cy"] - o["cy"]) < 6:
                is_dup = True
                break
        if not is_dup:
            out.append(c)
    return out
