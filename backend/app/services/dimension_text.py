"""Extracción de cotas (dimensiones numéricas) del texto vectorial del PDF.

No usa OCR — PyMuPDF puede leer las cadenas de texto con sus bounding boxes
directamente del stream del PDF cuando el documento fue exportado por un CAD.
Esto cubre el 95% de los planos profesionales y es órdenes de magnitud más
barato que correr un modelo de OCR. Para PDFs escaneados habrá que agregar
una pasada con Tesseract/PaddleOCR (Sprint 6).
"""

import re
from pathlib import Path

import fitz

# Matchea solo cotas con formato decimal: "8.11", "0,30", "12.5", "2.80".
# No matchea enteros sueltos (probables ejes "1", "2", "A", "B") ni "1:100"
# (eso es la notación de escala, no una cota).
_DIM_PATTERN = re.compile(r"^\d{1,4}[.,]\d{1,3}$")

# Rango razonable de longitudes en metros para una cota arquitectónica.
# Valores fuera de esto suelen ser ruido (ej. cotas en cm, números de plano).
_MIN_METERS = 0.05
_MAX_METERS = 500.0


def extract_dimensions(pdf_path: str | Path, page_index: int, dpi: int) -> list[dict]:
    """Devuelve las cotas con formato decimal de una página, en coordenadas del raster.

    Args:
        pdf_path: ruta al PDF original.
        page_index: 0-indexed.
        dpi: el DPI con el que se rasterizó la página (necesario para mapear
             puntos PDF → píxeles del PNG que ve el visor).

    Returns:
        Lista de dicts con:
          - text  (str)  : texto crudo como aparece en el PDF
          - value (float): el número parseado, con coma normalizada a punto
          - bbox  (list[float,4]): [x0, y0, x1, y1] en píxeles del raster
          - cx, cy (float): centro del bbox en píxeles del raster
    """
    factor = dpi / 72.0  # PDF points (1/72") → píxeles a `dpi`
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
                if not _DIM_PATTERN.match(text):
                    continue
                try:
                    value = float(text.replace(",", "."))
                except ValueError:
                    continue
                if value < _MIN_METERS or value > _MAX_METERS:
                    continue
                x0, y0, x1, y1 = span["bbox"]
                bbox_px = [x0 * factor, y0 * factor, x1 * factor, y1 * factor]
                cx = (bbox_px[0] + bbox_px[2]) / 2
                cy = (bbox_px[1] + bbox_px[3]) / 2
                results.append(
                    {
                        "text": text,
                        "value": round(value, 4),
                        "bbox": bbox_px,
                        "cx": round(cx, 2),
                        "cy": round(cy, 2),
                    }
                )
    return results
