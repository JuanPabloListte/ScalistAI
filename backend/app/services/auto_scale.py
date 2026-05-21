import re
from pathlib import Path

import fitz

# Cubrimos las notaciones más comunes en planos ES/AR:
#   "Escala: 1:100", "Esc. 1/75", "ESC 1:50", "Escala 1 : 25"
# El número que nos importa es el denominador.
_SCALE_PATTERN = re.compile(
    r"esc(?:ala)?\.?\s*1\s*[:/]\s*(\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)


def detect_scales(pdf_path: str | Path, dpi: int) -> dict[str, float]:
    """Escanea el texto extraído de cada página buscando notaciones tipo "1:N".

    Devuelve {page_str: px_per_m} con páginas 1-indexed para las páginas en
    las que se detectó una escala. Páginas sin escala identificable no quedan
    en el dict (el usuario puede calibrarlas a mano).

    Fórmula: en un plano impreso a escala 1:N a `dpi` puntos por pulgada,
    1 m real corresponde a (1000 / N) mm en el papel = (1000 / N) * (dpi / 25.4)
    píxeles en la rasterización.
    """
    doc = fitz.open(pdf_path)
    result: dict[str, float] = {}
    try:
        for i in range(doc.page_count):
            page = doc.load_page(i)
            text = page.get_text("text") or ""
            denominator = _find_denominator(text)
            if denominator is None or denominator <= 0:
                continue
            px_per_m = (dpi * 1000.0) / (25.4 * denominator)
            result[str(i + 1)] = round(px_per_m, 4)
    finally:
        doc.close()
    return result


def _find_denominator(text: str) -> float | None:
    """Busca el primer match plausible y devuelve el denominador de la escala."""
    for match in _SCALE_PATTERN.finditer(text):
        raw = match.group(1).replace(",", ".")
        try:
            value = float(raw)
        except ValueError:
            continue
        # Filtramos valores absurdos. Escalas arquitectónicas típicas
        # van de 1:10 (detalles) a 1:500 (urbanismo).
        if 1 <= value <= 5000:
            return value
    return None
