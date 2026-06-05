import cv2
import numpy as np


def enhance_for_display(png_bytes: bytes) -> bytes:
    """Rescata trazos finos antialiaseados por PyMuPDF para que se vean en pantalla.

    PyMuPDF rasteriza líneas CAD de 0.1mm con antialiasing → quedan en gris muy
    claro. Cuando el browser hace downscale a fit-zoom, ese gris desaparece.

    1) Lee en color (BGR) para preservar instalaciones coloreadas (cloacas, electricidad…).
    2) Gamma 0.55 por canal: líneas claras se oscurecen sin cambiar el tono.
    3) Dilatación 2×2 sobre el inverso: engrosa líneas de 1 px a 2 px.
    4) Reencoda como PNG.
    """
    arr = np.frombuffer(png_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return png_bytes

    gamma = 0.55
    table = np.array([((i / 255.0) ** gamma) * 255 for i in range(256)], dtype=np.uint8)
    darkened = cv2.LUT(img, table)

    inv = 255 - darkened
    kernel = np.ones((2, 2), np.uint8)
    dilated = cv2.dilate(inv, kernel, iterations=1)
    result = 255 - dilated

    ok, encoded = cv2.imencode(".png", result)
    if not ok:
        return png_bytes
    return encoded.tobytes()


def binarize(png_bytes: bytes) -> bytes:
    """Convierte un PNG a blanco y negro puro usando Otsu.

    El umbral Otsu encuentra el corte óptimo entre fondo y trazo del plano,
    funcionando tanto en planos digitales (líneas nítidas) como escaneados
    (con ruido y gradientes).
    """
    arr = np.frombuffer(png_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError("No se pudo decodificar el PNG")

    # Suavizado ligero para reducir ruido sin tapar líneas finas
    denoised = cv2.GaussianBlur(img, (3, 3), 0)

    _, binary = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    ok, encoded = cv2.imencode(".png", binary)
    if not ok:
        raise RuntimeError("No se pudo codificar el PNG binarizado")
    return encoded.tobytes()
