from pathlib import Path

MAX_PDF_BYTES = 50 * 1024 * 1024
# 150 DPI da ~30 MP por página A3 — tamaño que el browser muestra sin pérdida
# de líneas finas al hacer fit-zoom.
RASTER_DPI = 150


def _page_raster_path(pdf_path: Path, page: int) -> Path:
    """Path donde cacheamos el PNG binarizado de una página (1-indexed)."""
    return pdf_path.with_name(f"{pdf_path.stem}_p{page}.png")
