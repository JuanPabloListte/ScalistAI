"""Generador PROCEDURAL de planos sintéticos para entrenar el detector ML.

A diferencia de `synthetic_generator.py` (que deriva variaciones de planos REALES
del usuario), este módulo inventa plantas arquitectónicas/estructurales desde
cero por código. No usa ningún dato externo ni con licencia — es 100% propio.

Para qué sirve:
- **Volumen ilimitado** de samples con ground-truth perfecto.
- **Balance de clases**: garantiza muchísimos ejemplos de las clases que hoy
  escasean (openings, columns, roofs), que es donde el modelo falla.
- Complementa (no reemplaza) a los planos reales: el procedural enseña el
  *concepto* (un muro es una línea que limita recintos, una columna es un
  cuadrado chico, etc.) y los reales aportan el realismo del estilo CAD.

IMPORTANTE: estos samples van SOLO al train, nunca al holdout/val. El holdout
debe ser de planos reales, o medirías "aprendí mi generador" en vez de
"aprendí planos reales". Por eso se escriben en un directorio aparte y los
scripts de training los suman vía `--extra-data-dir`.

Cada sample sale como (imagen RGB uint8, máscara uint8) ya a `TARGET_SIZE`, con
el MISMO esquema de clases que `synthetic_generator`:
    0=fondo 1=muro 2=recinto 3=abertura 4=viga 5=columna 6=losa

Dos estilos de página, para que la co-ocurrencia de clases imite la realidad:
  - "arch"  (arquitectónico): muros + recintos + aberturas + alguna columna.
  - "struct" (estructural): losa + grilla de columnas + vigas + muros perimetrales.
"""
from __future__ import annotations

import math
import random
from typing import Any

import numpy as np

# Constantes replicadas de `synthetic_generator` a propósito: este módulo es
# función pura de cv2+numpy y NO debe arrastrar el stack del backend (config/DB).
# DEBEN matchear synthetic_generator.MASK_* y scripts._common.CLASS_NAMES:
#   0=fondo 1=muro 2=recinto 3=abertura 4=viga 5=columna 6=losa
TARGET_SIZE = 512
MASK_WALL = 1
MASK_ROOM = 2
MASK_OPENING = 3
MASK_BEAM = 4
MASK_COLUMN = 5
MASK_ROOF = 6
# Espesores de trazo en la máscara (deben matchear synthetic_generator).
DEFAULT_WALL_THICK_PX = 4
DEFAULT_OPENING_THICK_PX = 5
DEFAULT_BEAM_THICK_PX = 18
DEFAULT_COLUMN_RADIUS_PX = 14

Rect = tuple[int, int, int, int]
Point = tuple[int, int]

# Texto típico que se ve en planos — se dibuja en la imagen pero NO en la
# máscara, así el modelo aprende a IGNORAR el texto (robustez de dominio).
_ROOM_NAMES = [
    "DORM", "DORM 1", "DORM 2", "BAÑO", "COCINA", "ESTAR", "COMEDOR",
    "LIVING", "HALL", "ESCRIT", "LAVAD", "TOILET", "PLAYROOM", "SUITE",
]
_COLUMN_LABELS = ["C1", "C2", "C3", "P1", "P2", "C4", "C5"]
_BEAM_LABELS = ["V1", "V2", "V3", "V4", "V101", "V102"]
_ROOF_LABELS = ["LOSA", "L1", "L2", "LOSA H=20"]


# ----------------------------------------------------------------------
# API pública
# ----------------------------------------------------------------------
def generate_sample(rng: random.Random, size: int = TARGET_SIZE) -> tuple[np.ndarray, np.ndarray, dict]:
    """Genera un sample procedural. Devuelve (image_rgb uint8, mask uint8, meta).

    `rng` es un `random.Random` propio para reproducibilidad por-sample.
    """
    import cv2  # import lazy

    style = "struct" if rng.random() < 0.30 else "arch"
    img = np.full((size, size, 3), 255, dtype=np.uint8)
    mask = np.zeros((size, size), dtype=np.uint8)

    # Footprint (perímetro del edificio) con margen aleatorio.
    margin = rng.randint(18, 64)
    foot: Rect = (margin, margin, size - margin, size - margin)

    if style == "arch":
        counts = _draw_architectural(img, mask, foot, rng)
    else:
        counts = _draw_structural(img, mask, foot, rng)

    _apply_photometric_noise(img, rng)

    meta: dict[str, Any] = {
        "source": "procedural",
        "style": style,
        "image_size": size,
        "element_counts": counts,
    }
    return img, mask, meta


# ----------------------------------------------------------------------
# Estilo arquitectónico: recintos + muros + aberturas
# ----------------------------------------------------------------------
def _draw_architectural(img, mask, foot: Rect, rng: random.Random) -> dict[str, int]:
    import cv2

    min_size = rng.randint(58, 84)
    max_depth = rng.randint(2, 4)
    rooms = _bsp_split(foot, 0, max_depth, min_size, rng)

    counts = {"wall": 0, "room": 0, "opening": 0, "beam": 0, "column": 0, "roof": 0}

    # 1) Recintos (fill) — al fondo; los muros se dibujan encima.
    for (x0, y0, x1, y1) in rooms:
        cv2.rectangle(mask, (x0, y0), (x1, y1), MASK_ROOM, -1)
        counts["room"] += 1
        if rng.random() < 0.7:
            _draw_room_label(img, (x0, y0, x1, y1), rng)

    # 2) Columnas ocasionales en esquinas de recintos (alguna estructura).
    if rng.random() < 0.5:
        corners = _collect_corners(rooms)
        rng.shuffle(corners)
        for cpt in corners[: rng.randint(0, min(6, len(corners)))]:
            _draw_column(img, mask, cpt, rng)
            counts["column"] += 1

    # 3) Muros: bordes de cada recinto.
    edges = _collect_edges(rooms)
    for (p1, p2) in edges:
        _draw_wall(img, mask, p1, p2, rng)
    counts["wall"] += len(edges)

    # 4) Aberturas: una puerta por recinto en un muro interior + alguna ventana.
    fx0, fy0, fx1, fy1 = foot
    for (x0, y0, x1, y1) in rooms:
        room_edges = [
            ((x0, y0), (x1, y0)),
            ((x1, y0), (x1, y1)),
            ((x1, y1), (x0, y1)),
            ((x0, y1), (x0, y0)),
        ]
        interior = [
            e for e in room_edges
            if not _edge_on_boundary(e, foot)
        ]
        if interior and rng.random() < 0.85:
            e = rng.choice(interior)
            if _add_opening(img, mask, e[0], e[1], rng, is_door=True):
                counts["opening"] += 1
    # Ventanas en el perímetro
    for _ in range(rng.randint(1, 4)):
        e = _random_boundary_edge(foot, rng)
        if _add_opening(img, mask, e[0], e[1], rng, is_door=False):
            counts["opening"] += 1

    return counts


# ----------------------------------------------------------------------
# Estilo estructural: losa + grilla de columnas + vigas
# ----------------------------------------------------------------------
def _draw_structural(img, mask, foot: Rect, rng: random.Random) -> dict[str, int]:
    import cv2

    counts = {"wall": 0, "room": 0, "opening": 0, "beam": 0, "column": 0, "roof": 0}
    x0, y0, x1, y1 = foot

    # 0) Losa: el footprint entero (a veces un poco recortado).
    rx0 = x0 + rng.randint(0, 12)
    ry0 = y0 + rng.randint(0, 12)
    rx1 = x1 - rng.randint(0, 12)
    ry1 = y1 - rng.randint(0, 12)
    cv2.rectangle(mask, (rx0, ry0), (rx1, ry1), MASK_ROOF, -1)
    counts["roof"] += 1
    if rng.random() < 0.6:
        _draw_label(img, ((rx0 + rx1) // 2, (ry0 + ry1) // 2), rng.choice(_ROOF_LABELS), rng)

    # Grilla de columnas.
    ncols = rng.randint(3, 6)
    nrows = rng.randint(3, 6)
    xs = np.linspace(x0, x1, ncols).round().astype(int)
    ys = np.linspace(y0, y1, nrows).round().astype(int)

    # 2) Vigas (antes que columnas en el orden de pintado): conectan columnas
    #    adyacentes en grilla, formando el reticulado estructural.
    for j, yy in enumerate(ys):
        for i, xx in enumerate(xs):
            if i + 1 < ncols:
                _draw_beam(img, mask, (int(xx), int(yy)), (int(xs[i + 1]), int(yy)), rng)
                counts["beam"] += 1
            if j + 1 < nrows:
                _draw_beam(img, mask, (int(xx), int(yy)), (int(xx), int(ys[j + 1])), rng)
                counts["beam"] += 1

    # 3) Columnas en cada nodo.
    for yy in ys:
        for xx in xs:
            _draw_column(img, mask, (int(xx), int(yy)), rng)
            counts["column"] += 1
            if rng.random() < 0.25:
                _draw_label(img, (int(xx) + 10, int(yy) - 6), rng.choice(_COLUMN_LABELS), rng)

    # 4) Muros perimetrales.
    perim = [
        ((x0, y0), (x1, y0)),
        ((x1, y0), (x1, y1)),
        ((x1, y1), (x0, y1)),
        ((x0, y1), (x0, y0)),
    ]
    for (p1, p2) in perim:
        _draw_wall(img, mask, p1, p2, rng)
    counts["wall"] += len(perim)

    return counts


# ----------------------------------------------------------------------
# BSP de particionado en recintos
# ----------------------------------------------------------------------
def _bsp_split(rect: Rect, depth: int, max_depth: int, min_size: int, rng: random.Random) -> list[Rect]:
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    if depth >= max_depth or (w < 2 * min_size and h < 2 * min_size):
        return [rect]

    # Partir el lado más largo, con algo de azar cuando son parecidos.
    if w > h * 1.15:
        vertical = True
    elif h > w * 1.15:
        vertical = False
    else:
        vertical = rng.random() < 0.5

    if vertical and w < 2 * min_size:
        vertical = False
    if (not vertical) and h < 2 * min_size:
        vertical = True

    if vertical and w >= 2 * min_size:
        cut = rng.randint(x0 + min_size, x1 - min_size)
        return (
            _bsp_split((x0, y0, cut, y1), depth + 1, max_depth, min_size, rng)
            + _bsp_split((cut, y0, x1, y1), depth + 1, max_depth, min_size, rng)
        )
    if (not vertical) and h >= 2 * min_size:
        cut = rng.randint(y0 + min_size, y1 - min_size)
        return (
            _bsp_split((x0, y0, x1, cut), depth + 1, max_depth, min_size, rng)
            + _bsp_split((x0, cut, x1, y1), depth + 1, max_depth, min_size, rng)
        )
    return [rect]


def _collect_edges(rooms: list[Rect]) -> list[tuple[Point, Point]]:
    edges: list[tuple[Point, Point]] = []
    for (x0, y0, x1, y1) in rooms:
        edges.append(((x0, y0), (x1, y0)))
        edges.append(((x1, y0), (x1, y1)))
        edges.append(((x1, y1), (x0, y1)))
        edges.append(((x0, y1), (x0, y0)))
    return edges


def _collect_corners(rooms: list[Rect]) -> list[Point]:
    corners: set[Point] = set()
    for (x0, y0, x1, y1) in rooms:
        corners.update([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
    return list(corners)


# ----------------------------------------------------------------------
# Primitivas de dibujo (imagen + máscara en paralelo)
# ----------------------------------------------------------------------
def _draw_wall(img, mask, p1: Point, p2: Point, rng: random.Random) -> None:
    import cv2

    # Imagen: línea negra un poco más gruesa que la etiqueta (como un muro real
    # se ve más grueso que su centerline). La máscara usa el centerline fino,
    # consistente con synthetic_generator y con el skeletonize del postproceso.
    img_thick = rng.choice([3, 4, 5, 6])
    cv2.line(img, p1, p2, (0, 0, 0), img_thick, lineType=cv2.LINE_AA)
    cv2.line(mask, p1, p2, MASK_WALL, DEFAULT_WALL_THICK_PX)


def _draw_beam(img, mask, p1: Point, p2: Point, rng: random.Random) -> None:
    import cv2

    # Viga: línea ancha. En la imagen, dos líneas paralelas finas (doble línea
    # típica de viga) + relleno gris claro; en la máscara, banda gruesa.
    cv2.line(mask, p1, p2, MASK_BEAM, DEFAULT_BEAM_THICK_PX)
    gray = rng.randint(90, 160)
    cv2.line(img, p1, p2, (gray, gray, gray), DEFAULT_BEAM_THICK_PX, lineType=cv2.LINE_AA)
    # Bordes de la viga (las dos líneas paralelas).
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length  # normal unitaria
    off = DEFAULT_BEAM_THICK_PX / 2.0
    for s in (off, -off):
        a = (int(round(p1[0] + nx * s)), int(round(p1[1] + ny * s)))
        b = (int(round(p2[0] + nx * s)), int(round(p2[1] + ny * s)))
        cv2.line(img, a, b, (0, 0, 0), 1, lineType=cv2.LINE_AA)


def _draw_column(img, mask, center: Point, rng: random.Random) -> None:
    import cv2

    half = rng.randint(max(4, DEFAULT_COLUMN_RADIUS_PX - 6), DEFAULT_COLUMN_RADIUS_PX + 2)
    cx, cy = center
    p0 = (cx - half, cy - half)
    p1 = (cx + half, cy + half)
    # Columna: cuadrado relleno (sección maciza). Imagen negra, máscara COLUMN.
    cv2.rectangle(mask, p0, p1, MASK_COLUMN, -1)
    cv2.rectangle(img, p0, p1, (0, 0, 0), -1)


def _add_opening(img, mask, p1: Point, p2: Point, rng: random.Random, is_door: bool) -> bool:
    """Dibuja una abertura (puerta/ventana) sobre un muro: hueco en la imagen +
    arco de barrido si es puerta, y segmento MASK_OPENING en la máscara.

    Devuelve False si el muro es muy corto para una abertura."""
    import cv2

    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = math.hypot(dx, dy)
    width = rng.randint(20, 36) if is_door else rng.randint(16, 30)
    if length < width + 14:
        return False
    ux, uy = dx / length, dy / length
    t = rng.uniform(0.30, 0.70)
    cx = p1[0] + ux * length * t
    cy = p1[1] + uy * length * t
    half = width / 2.0
    d1 = (int(round(cx - ux * half)), int(round(cy - uy * half)))
    d2 = (int(round(cx + ux * half)), int(round(cy + uy * half)))

    # Hueco blanco en la imagen (la puerta/ventana "corta" el muro).
    cv2.line(img, d1, d2, (255, 255, 255), DEFAULT_WALL_THICK_PX + 3)
    if is_door:
        # Arco de barrido (estético; no afecta la máscara).
        nx, ny = -uy, ux
        hinge = d1
        end = (int(round(d1[0] + nx * width)), int(round(d1[1] + ny * width)))
        cv2.line(img, hinge, end, (0, 0, 0), 1, lineType=cv2.LINE_AA)
        ang = math.degrees(math.atan2(uy, ux))
        cv2.ellipse(img, hinge, (width, width), ang, 0, 90, (0, 0, 0), 1, lineType=cv2.LINE_AA)
    else:
        # Ventana: doble línea fina dentro del hueco.
        cv2.line(img, d1, d2, (0, 0, 0), 1, lineType=cv2.LINE_AA)

    cv2.line(mask, d1, d2, MASK_OPENING, DEFAULT_OPENING_THICK_PX)
    return True


# ----------------------------------------------------------------------
# Texto (solo imagen — robustez: el modelo debe ignorarlo)
# ----------------------------------------------------------------------
def _draw_room_label(img, rect: Rect, rng: random.Random) -> None:
    x0, y0, x1, y1 = rect
    if (x1 - x0) < 50 or (y1 - y0) < 36:
        return
    cx = (x0 + x1) // 2 - rng.randint(8, 20)
    cy = (y0 + y1) // 2
    _draw_label(img, (cx, cy), rng.choice(_ROOM_NAMES), rng)


def _draw_label(img, org: Point, text: str, rng: random.Random) -> None:
    import cv2

    scale = rng.uniform(0.32, 0.5)
    gray = rng.randint(40, 110)
    cv2.putText(
        img, text, (int(org[0]), int(org[1])), cv2.FONT_HERSHEY_SIMPLEX,
        scale, (gray, gray, gray), 1, lineType=cv2.LINE_AA,
    )


# ----------------------------------------------------------------------
# Helpers geométricos / ruido
# ----------------------------------------------------------------------
def _edge_on_boundary(edge: tuple[Point, Point], foot: Rect) -> bool:
    (ax, ay), (bx, by) = edge
    fx0, fy0, fx1, fy1 = foot
    # Borde vertical sobre x0/x1, u horizontal sobre y0/y1.
    if ax == bx and (ax == fx0 or ax == fx1):
        return True
    if ay == by and (ay == fy0 or ay == fy1):
        return True
    return False


def _random_boundary_edge(foot: Rect, rng: random.Random) -> tuple[Point, Point]:
    x0, y0, x1, y1 = foot
    sides = [
        ((x0, y0), (x1, y0)),
        ((x1, y0), (x1, y1)),
        ((x1, y1), (x0, y1)),
        ((x0, y1), (x0, y0)),
    ]
    return rng.choice(sides)


def _apply_photometric_noise(img, rng: random.Random) -> None:
    """Ruido leve para acercar el sintético al dominio real (scan/foto)."""
    import cv2

    if rng.random() < 0.4:
        sigma = rng.uniform(2.0, 9.0)
        noise = np.random.normal(0, sigma, img.shape).astype(np.float32)
        img[:] = np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    if rng.random() < 0.3:
        beta = rng.randint(-25, 15)
        img[:] = np.clip(img.astype(np.int16) + beta, 0, 255).astype(np.uint8)
    if rng.random() < 0.2:
        k = rng.choice([3, 5])
        img[:] = cv2.GaussianBlur(img, (k, k), 0)
