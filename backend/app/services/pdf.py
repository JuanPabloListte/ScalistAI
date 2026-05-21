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
