"""Validación cruzada entre elementos vectoriales (CAD) y predicciones de IA.

Cuando un PDF vectorial ya aportó elementos exactos (source="dxf"), la IA
no se salta: corre igual y sus predicciones se cruzan geométricamente contra
lo que el CAD ya trajo.

  - Duplicado: la predicción IA se superpone con un elemento vectorial del
    mismo tipo → se descarta (el vector es geometría exacta, manda siempre).
  - Gap-filling: la IA encontró algo donde el CAD no tiene nada (capa mal
    nombrada, dibujo incompleto) → se persiste como candidato
    (is_candidate=True) que el usuario acepta o descarta en el visor.

El elemento vectorial NUNCA se degrada por desacuerdo de la IA: el dato CAD
es exacto y el modelo tiene falsos negativos frecuentes. La confianza es
asimétrica por diseño.

El matching no usa IoU directo porque los muros son polilíneas (ejes), no
polígonos: dos ejes del mismo muro darían IoU≈0. En cambio se rasterizan los
elementos vectoriales con un buffer al espesor típico de muro y se mide qué
fracción de la predicción IA cae dentro de esa máscara.
"""

from __future__ import annotations

import logging
import math

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Espesor del buffer con que se rasterizan los elementos vectoriales lineales.
# Holgado (35 cm) para absorber el corrimiento típico entre el eje CAD y la
# predicción del modelo sin dejar pasar muros paralelos cercanos.
_BUFFER_M = 0.35
# Fracción mínima de la predicción cubierta por la máscara vectorial para
# considerarla duplicado del elemento CAD.
_DUP_COVERAGE = 0.5
# Distancia máxima (m) entre centros para matchear aberturas.
_OPENING_MATCH_M = 0.6
# Confianza asignada a los candidatos gap-fill (IA sin respaldo CAD).
GAP_FILL_CONFIDENCE = 0.6
# Lado máximo de la máscara de trabajo; las páginas se trabajan downscaled.
_MAX_MASK_SIDE = 2048

# Tipos cuya geometría es un polígono cerrado (se rellenan, no se bufferean).
_POLYGON_TYPES = {"room", "roof", "escalera", "column"}


def _flat_points(geometry: dict) -> list[tuple[float, float]]:
    pts = geometry.get("points") or []
    return [(float(x), float(y)) for x, y in zip(pts[0::2], pts[1::2])]


def _build_vector_mask(
    vector_elements: list,
    el_type: str,
    px_per_m: float,
    img_w: int,
    img_h: int,
) -> tuple[np.ndarray | None, float]:
    """Máscara binaria (downscaled) de los elementos vectoriales de un tipo.

    Devuelve (mask, ds) donde ds es el factor de downscale aplicado.
    """
    if not vector_elements or img_w <= 0 or img_h <= 0:
        return None, 1.0

    ds = max(1.0, max(img_w, img_h) / _MAX_MASK_SIDE)
    mw, mh = max(1, int(img_w / ds)), max(1, int(img_h / ds))
    mask = np.zeros((mh, mw), dtype=np.uint8)

    thick = max(3, int(_BUFFER_M * px_per_m / ds))
    for el in vector_elements:
        xy = _flat_points(el.geometry or {})
        if len(xy) < 2:
            continue
        pts = [(int(round(x / ds)), int(round(y / ds))) for x, y in xy]
        if el_type in _POLYGON_TYPES and len(pts) >= 3:
            cv2.fillPoly(mask, [np.array(pts, dtype=np.int32)], 255)
            cv2.polylines(mask, [np.array(pts, dtype=np.int32)], True, 255, thickness=thick)
        else:
            for a, b in zip(pts, pts[1:]):
                cv2.line(mask, a, b, 255, thickness=thick)
    return mask, ds


def _candidate_coverage(
    mask: np.ndarray, ds: float, geometry: dict, el_type: str
) -> float:
    """Fracción [0..1] de la geometría del candidato cubierta por la máscara."""
    xy = _flat_points(geometry)
    if len(xy) < 2:
        return 0.0
    test = np.zeros_like(mask)
    pts = [(int(round(x / ds)), int(round(y / ds))) for x, y in xy]
    if el_type in _POLYGON_TYPES and len(pts) >= 3:
        # Para polígonos comparamos el contorno, no el relleno: dos recintos
        # vecinos comparten área si se rellenan pero sus bordes difieren.
        cv2.polylines(test, [np.array(pts, dtype=np.int32)], True, 255, thickness=3)
    else:
        for a, b in zip(pts, pts[1:]):
            cv2.line(test, a, b, 255, thickness=3)
    total = int(np.count_nonzero(test))
    if total == 0:
        return 0.0
    overlap = int(np.count_nonzero(cv2.bitwise_and(test, mask)))
    return overlap / total


def filter_gap_fill_candidates(
    vector_elements: list,
    ai_candidates: list[dict],
    el_type: str,
    px_per_m: float | None,
    img_w: int,
    img_h: int,
) -> list[dict]:
    """Devuelve los candidatos IA que NO duplican elementos vectoriales.

    `vector_elements`: DetectedElement existentes (source="dxf") del mismo
    tipo y página. `ai_candidates`: dicts crudos del detector (con "geometry").
    Si no hay elementos vectoriales de ese tipo, todos los candidatos son
    gap-fill (el CAD no trajo nada de ese tipo).
    """
    if not ai_candidates:
        return []
    if not vector_elements or not px_per_m:
        return list(ai_candidates)

    mask, ds = _build_vector_mask(vector_elements, el_type, px_per_m, img_w, img_h)
    if mask is None:
        return list(ai_candidates)

    kept: list[dict] = []
    dropped = 0
    for c in ai_candidates:
        geometry = c.get("geometry") or {}
        cov = _candidate_coverage(mask, ds, geometry, el_type)
        if cov >= _DUP_COVERAGE:
            dropped += 1
        else:
            kept.append(c)
    logger.info(
        "hybrid %s: %d candidatos IA → %d gap-fill, %d duplicados del CAD",
        el_type, len(ai_candidates), len(kept), dropped,
    )
    return kept


def filter_gap_fill_openings(
    vector_openings: list,
    ai_candidates: list[dict],
    px_per_m: float | None,
) -> list[dict]:
    """Aberturas: matching por distancia entre centros (los candidatos IA
    traen cx/cy, no geometry). Dentro de _OPENING_MATCH_M = duplicado."""
    if not ai_candidates:
        return []
    if not vector_openings or not px_per_m:
        return list(ai_candidates)

    centers: list[tuple[float, float]] = []
    for el in vector_openings:
        xy = _flat_points(el.geometry or {})
        if len(xy) >= 2:
            cx = sum(p[0] for p in xy) / len(xy)
            cy = sum(p[1] for p in xy) / len(xy)
            centers.append((cx, cy))
    if not centers:
        return list(ai_candidates)

    max_px = _OPENING_MATCH_M * px_per_m
    kept: list[dict] = []
    dropped = 0
    for c in ai_candidates:
        try:
            cx, cy = float(c["cx"]), float(c["cy"])
        except (KeyError, TypeError, ValueError):
            continue
        if any(math.hypot(cx - vx, cy - vy) <= max_px for vx, vy in centers):
            dropped += 1
        else:
            kept.append(c)
    logger.info(
        "hybrid opening: %d candidatos IA → %d gap-fill, %d duplicados del CAD",
        len(ai_candidates), len(kept), dropped,
    )
    return kept
