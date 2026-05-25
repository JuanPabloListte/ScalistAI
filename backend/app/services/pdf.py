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


def recommend_pages(pdf_path: str | Path) -> list[dict]:
    """Analiza las paginas del PDF usando PyMuPDF localmente
    para recomendar las paginas mas optimas para el marcaje de muros y recintos.
    """
    doc = fitz.open(pdf_path)
    recommendations = []

    # Palabras clave de recintos
    ROOM_KEYS = ["dormitorio", "dorm", "cocina", "baño", "comedor", "estar", "living", "toilette", "suite", "vestidor", "habitacion"]
    # Palabras clave de plano/nivel
    PLANTA_KEYS = ["planta", "arquitectura", "distribucion", "layout", "piso", "nivel", "floor plan"]
    # Palabras clave de planos tecnicos/detalles (penalizacion)
    PENALTY_KEYS = ["estructuras", "detalles", "corte", "vista", "fachada", "elevacion", "instalacion", "electrica", "sanitaria", "gas", "pluvial", "pliego", "esquema", "cimentacion", "fundacion"]

    try:
        for i in range(doc.page_count):
            page = doc.load_page(i)
            text = (page.get_text("text") or "").lower()

            room_matches = sum(1 for key in ROOM_KEYS if key in text)
            planta_matches = sum(1 for key in PLANTA_KEYS if key in text)
            penalty_matches = sum(1 for key in PENALTY_KEYS if key in text)

            drawings_count = len(page.get_drawings())

            score = (room_matches * 15) + (planta_matches * 10) - (penalty_matches * 12)

            if drawings_count < 10:
                score -= 50

            recommended = score > 15

            reasons = []
            if room_matches > 0:
                reasons.append("Contiene etiquetas de recintos")
            if planta_matches > 0:
                reasons.append("Contiene palabras clave de distribucion")
            if penalty_matches > 0:
                reasons.append("Contiene terminos de estructuras/detalles")
            if drawings_count < 10:
                reasons.append("Pocos dibujos vectoriales")

            reason_str = ", ".join(reasons) if reasons else "Sin palabras clave relevantes"

            recommendations.append({
                "page": i + 1,
                "score": score,
                "recommended": recommended,
                "reason": reason_str
            })
    finally:
        doc.close()

    return recommendations

