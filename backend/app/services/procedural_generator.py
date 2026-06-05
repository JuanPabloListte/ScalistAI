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
    0=bg 1=wall 2=room 3=door 4=window 5=sliding_door 6=beam 7=column 8=roof
    9=riostra 10=cloaca 11=electricidad

Estilos de página:
  - "arch"   (arquitectónico): muros + recintos + aberturas + alguna columna.
  - "struct" (estructural): losa + grilla de columnas + vigas + muros perimetrales.
  - "mixed"  (mixto): arquitectónico con grilla estructural superpuesta.
"""
from __future__ import annotations

import math
import random
from typing import Any

import numpy as np

TARGET_SIZE = 512
MASK_WALL = 1
MASK_ROOM = 2
MASK_OPENING = 3   # se mapea a "door" — abertura genérica
MASK_BEAM = 6
MASK_COLUMN = 7
MASK_ROOF = 8
MASK_RIOSTRA = 9
MASK_CLOACA = 10
MASK_ELECTRICIDAD = 11

DEFAULT_WALL_THICK_PX = 4
DEFAULT_OPENING_THICK_PX = 5
DEFAULT_BEAM_THICK_PX = 18
DEFAULT_COLUMN_RADIUS_PX = 14
DEFAULT_RIOSTRA_THICK_PX = 18
DEFAULT_CLOACA_THICK_PX = 6
DEFAULT_ELECTRICIDAD_THICK_PX = 4

# Colores BGR que coinciden con planos reales argentinos:
#   cloacas  → naranja/rojo   (como en planos de instalaciones sanitarias)
#   electr.  → amarillo       (como en planos eléctricos)
#   riostras → marrón-naranja (como en planos de fundaciones)
_COLOR_CLOACA_BGR = (0, 90, 230)       # naranja en BGR
_COLOR_ELECTRICIDAD_BGR = (0, 210, 230) # amarillo en BGR
_COLOR_RIOSTRA_BGR = (30, 110, 190)    # marrón-naranja en BGR

Rect = tuple[int, int, int, int]
Point = tuple[int, int]

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
    """Genera un sample procedural. Devuelve (image_rgb uint8, mask uint8, meta)."""
    import cv2

    style = rng.choices(["arch", "struct", "mixed"], weights=[0.50, 0.25, 0.25])[0]
    img = np.full((size, size, 3), 255, dtype=np.uint8)
    mask = np.zeros((size, size), dtype=np.uint8)

    sub_rects, foot = _make_building_shape(rng, size)

    if style == "arch":
        counts = _draw_architectural(img, mask, sub_rects, foot, rng)
    elif style == "struct":
        counts = _draw_structural(img, mask, foot, rng)
    else:
        counts = _draw_mixed(img, mask, sub_rects, foot, rng)

    _apply_photometric_noise(img, rng)

    meta: dict[str, Any] = {
        "source": "procedural",
        "style": style,
        "image_size": size,
        "element_counts": counts,
    }
    return img, mask, meta


# ----------------------------------------------------------------------
# Generación de footprint (rectangular, L, T)
# ----------------------------------------------------------------------
def _make_building_shape(rng: random.Random, size: int) -> tuple[list[Rect], Rect]:
    """Devuelve (sub_rects, bounding_foot).

    sub_rects: lista de rectángulos que forman el edificio (1 para rect, 2 para L/T).
    bounding_foot: bounding box global usado para instalaciones y perímetro.
    """
    margin = rng.randint(18, 60)
    x0, y0 = margin, margin
    x1, y1 = size - margin, size - margin
    w, h = x1 - x0, y1 - y0
    min_section = 80  # mínimo píxeles para que una sección tenga sentido

    shape = rng.choices(["rect", "L", "T"], weights=[0.40, 0.38, 0.22])[0]

    if shape == "L" and w > 2 * min_section and h > 2 * min_section:
        # L: rectángulo completo menos una esquina
        cut_x = rng.randint(x0 + min_section, x1 - min_section)
        cut_y = rng.randint(y0 + min_section, y1 - min_section)
        corner = rng.choice(["tl", "tr", "bl", "br"])
        if corner == "br":
            r1 = (x0, y0, x1, cut_y)       # banda superior completa
            r2 = (x0, cut_y, cut_x, y1)    # banda inferior izquierda
        elif corner == "bl":
            r1 = (x0, y0, x1, cut_y)
            r2 = (cut_x, cut_y, x1, y1)
        elif corner == "tr":
            r1 = (x0, cut_y, x1, y1)
            r2 = (x0, y0, cut_x, cut_y)
        else:  # tl
            r1 = (x0, cut_y, x1, y1)
            r2 = (cut_x, y0, x1, cut_y)
        return [r1, r2], (x0, y0, x1, y1)

    if shape == "T" and w > 3 * min_section and h > 2 * min_section:
        # T: banda horizontal completa + tallo central vertical
        cut_y = rng.randint(y0 + min_section, y1 - min_section)
        stem_x0 = rng.randint(x0 + min_section // 2, (x0 + x1) // 2 - min_section // 2)
        stem_x1 = rng.randint((x0 + x1) // 2 + min_section // 2, x1 - min_section // 2)
        r1 = (x0, y0, x1, cut_y)           # cabeza horizontal
        r2 = (stem_x0, cut_y, stem_x1, y1) # tallo
        return [r1, r2], (x0, y0, x1, y1)

    # Fallback rectangular
    foot = (x0, y0, x1, y1)
    return [foot], foot


# ----------------------------------------------------------------------
# Estilo arquitectónico: recintos + muros + aberturas
# ----------------------------------------------------------------------
def _draw_architectural(img, mask, sub_rects: list[Rect], foot: Rect, rng: random.Random) -> dict[str, int]:
    import cv2

    counts = {k: 0 for k in ("wall", "room", "opening", "beam", "column", "roof", "riostra", "cloaca", "electricidad")}
    all_rooms: list[Rect] = []

    for section in sub_rects:
        min_size = rng.randint(52, 80)
        max_depth = rng.randint(2, 4)
        rooms = _bsp_split(section, 0, max_depth, min_size, rng)
        all_rooms.extend(rooms)

    # 1) Recintos
    for (x0, y0, x1, y1) in all_rooms:
        cv2.rectangle(mask, (x0, y0), (x1, y1), MASK_ROOM, -1)
        counts["room"] += 1
        if rng.random() < 0.7:
            _draw_room_label(img, (x0, y0, x1, y1), rng)

    # 2) Columnas en esquinas (ocasional)
    if rng.random() < 0.5:
        corners = _collect_corners(all_rooms)
        rng.shuffle(corners)
        for cpt in corners[: rng.randint(0, min(6, len(corners)))]:
            _draw_column(img, mask, cpt, rng)
            counts["column"] += 1

    # 3) Muros
    edges = _collect_edges(all_rooms)
    for (p1, p2) in edges:
        _draw_wall(img, mask, p1, p2, rng)
    counts["wall"] += len(edges)

    # 4) Aberturas
    for (x0, y0, x1, y1) in all_rooms:
        room_edges = [
            ((x0, y0), (x1, y0)),
            ((x1, y0), (x1, y1)),
            ((x1, y1), (x0, y1)),
            ((x0, y1), (x0, y0)),
        ]
        interior = [e for e in room_edges if not _edge_on_boundary(e, foot)]
        if interior and rng.random() < 0.85:
            e = rng.choice(interior)
            if _add_opening(img, mask, e[0], e[1], rng, is_door=True):
                counts["opening"] += 1
    for _ in range(rng.randint(1, 4)):
        e = _random_boundary_edge(foot, rng)
        if _add_opening(img, mask, e[0], e[1], rng, is_door=False):
            counts["opening"] += 1

    counts.update(_draw_installation_network(img, mask, all_rooms, foot, rng, include_riostras=False))
    return counts


# ----------------------------------------------------------------------
# Estilo estructural: losa + grilla de columnas + vigas
# ----------------------------------------------------------------------
def _draw_structural(img, mask, foot: Rect, rng: random.Random) -> dict[str, int]:
    import cv2

    counts = {k: 0 for k in ("wall", "room", "opening", "beam", "column", "roof", "riostra", "cloaca", "electricidad")}
    x0, y0, x1, y1 = foot

    # Losa
    rx0 = x0 + rng.randint(0, 12)
    ry0 = y0 + rng.randint(0, 12)
    rx1 = x1 - rng.randint(0, 12)
    ry1 = y1 - rng.randint(0, 12)
    cv2.rectangle(mask, (rx0, ry0), (rx1, ry1), MASK_ROOF, -1)
    counts["roof"] += 1
    if rng.random() < 0.6:
        _draw_label(img, ((rx0 + rx1) // 2, (ry0 + ry1) // 2), rng.choice(_ROOF_LABELS), rng)

    ncols = rng.randint(3, 6)
    nrows = rng.randint(3, 6)
    xs = np.linspace(x0, x1, ncols).round().astype(int)
    ys = np.linspace(y0, y1, nrows).round().astype(int)

    for j, yy in enumerate(ys):
        for i, xx in enumerate(xs):
            if i + 1 < ncols:
                _draw_beam(img, mask, (int(xx), int(yy)), (int(xs[i + 1]), int(yy)), rng)
                counts["beam"] += 1
            if j + 1 < nrows:
                _draw_beam(img, mask, (int(xx), int(yy)), (int(xx), int(ys[j + 1])), rng)
                counts["beam"] += 1

    for yy in ys:
        for xx in xs:
            _draw_column(img, mask, (int(xx), int(yy)), rng)
            counts["column"] += 1
            if rng.random() < 0.25:
                _draw_label(img, (int(xx) + 10, int(yy) - 6), rng.choice(_COLUMN_LABELS), rng)

    perim = [
        ((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)),
        ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0)),
    ]
    for (p1, p2) in perim:
        _draw_wall(img, mask, p1, p2, rng)
    counts["wall"] += len(perim)

    counts.update(_draw_installation_network(img, mask, [], foot, rng, include_riostras=True))
    return counts


# ----------------------------------------------------------------------
# Estilo mixto: layout de recintos + grilla estructural superpuesta
# ----------------------------------------------------------------------
def _draw_mixed(img, mask, sub_rects: list[Rect], foot: Rect, rng: random.Random) -> dict[str, int]:
    import cv2

    counts = _draw_architectural(img, mask, sub_rects, foot, rng)

    # Grilla estructural ligera superpuesta
    x0, y0, x1, y1 = foot
    ncols = rng.randint(2, 4)
    nrows = rng.randint(2, 4)
    xs = np.linspace(x0, x1, ncols).round().astype(int)
    ys = np.linspace(y0, y1, nrows).round().astype(int)
    for yy in ys:
        for xx in xs:
            _draw_column(img, mask, (int(xx), int(yy)), rng)
            counts["column"] += 1
    for j, yy in enumerate(ys):
        for i, xx in enumerate(xs):
            if i + 1 < ncols and rng.random() < 0.6:
                _draw_beam(img, mask, (int(xx), int(yy)), (int(xs[i + 1]), int(yy)), rng)
                counts["beam"] += 1
            if j + 1 < nrows and rng.random() < 0.6:
                _draw_beam(img, mask, (int(xx), int(yy)), (int(xx), int(ys[j + 1])), rng)
                counts["beam"] += 1

    counts.update(_draw_installation_network(img, mask, [], foot, rng, include_riostras=True))
    return counts


# ----------------------------------------------------------------------
# Red de instalaciones — trazado lógico con tronco + ramales
# ----------------------------------------------------------------------
def _draw_installation_network(
    img, mask, rooms: list[Rect], foot: Rect, rng: random.Random,
    include_riostras: bool = False,
) -> dict[str, int]:
    """Dibuja instalaciones siguiendo un patrón de tronco principal + ramales,
    imitando la lógica real de un plano de instalaciones."""
    import cv2

    counts = {"riostra": 0, "cloaca": 0, "electricidad": 0}
    x0, y0, x1, y1 = foot

    # ---- Riostras (solo estructural/mixto) ----
    if include_riostras:
        n_rios = rng.randint(2, 5)
        for _ in range(n_rios):
            # Riostras horizontales o verticales entre puntos del perímetro
            if rng.random() < 0.5:
                py = rng.randint(y0 + 20, y1 - 20)
                p1 = (x0, py)
                p2 = (x1, py)
            else:
                px = rng.randint(x0 + 20, x1 - 20)
                p1 = (px, y0)
                p2 = (px, y1)
            cv2.line(mask, p1, p2, MASK_RIOSTRA, DEFAULT_RIOSTRA_THICK_PX)
            cv2.line(img, p1, p2, _COLOR_RIOSTRA_BGR, DEFAULT_RIOSTRA_THICK_PX, lineType=cv2.LINE_AA)
            counts["riostra"] += 1

    # ---- Cloacas — tronco hacia el exterior + ramales a baños/cocinas ----
    n_cloa_trunks = rng.randint(1, 3)
    for _ in range(n_cloa_trunks):
        # Tronco principal: va de un punto interior hacia un borde del edificio
        side = rng.choice(["bottom", "left", "right"])
        if side == "bottom":
            trunk_start = (rng.randint(x0 + 20, x1 - 20), rng.randint(y0 + 40, (y0 + y1) // 2))
            trunk_end = (trunk_start[0] + rng.randint(-30, 30), y1)
        elif side == "left":
            trunk_start = (rng.randint(x0 + 40, (x0 + x1) // 2), rng.randint(y0 + 20, y1 - 20))
            trunk_end = (x0, trunk_start[1] + rng.randint(-30, 30))
        else:
            trunk_start = (rng.randint((x0 + x1) // 2, x1 - 40), rng.randint(y0 + 20, y1 - 20))
            trunk_end = (x1, trunk_start[1] + rng.randint(-30, 30))

        cv2.line(mask, trunk_start, trunk_end, MASK_CLOACA, DEFAULT_CLOACA_THICK_PX)
        cv2.line(img, trunk_start, trunk_end, _COLOR_CLOACA_BGR, DEFAULT_CLOACA_THICK_PX, lineType=cv2.LINE_AA)
        counts["cloaca"] += 1

        # Ramales: 1-3 conexiones al tronco desde recintos o puntos aleatorios
        n_branches = rng.randint(1, 3)
        for _ in range(n_branches):
            if rooms:
                room = rng.choice(rooms)
                branch_start = (
                    rng.randint(room[0], room[2]),
                    rng.randint(room[1], room[3]),
                )
            else:
                branch_start = (rng.randint(x0, x1), rng.randint(y0, y1))
            # Conectar al tronco con un codo (horizontal luego vertical)
            mid = (branch_start[0], trunk_start[1])
            cv2.line(mask, branch_start, mid, MASK_CLOACA, DEFAULT_CLOACA_THICK_PX)
            cv2.line(mask, mid, trunk_start, MASK_CLOACA, DEFAULT_CLOACA_THICK_PX)
            cv2.line(img, branch_start, mid, _COLOR_CLOACA_BGR, DEFAULT_CLOACA_THICK_PX, lineType=cv2.LINE_AA)
            cv2.line(img, mid, trunk_start, _COLOR_CLOACA_BGR, DEFAULT_CLOACA_THICK_PX, lineType=cv2.LINE_AA)
            counts["cloaca"] += 1

    # ---- Electricidad — circuito que recorre los recintos ----
    n_circuits = rng.randint(1, 3)
    for _ in range(n_circuits):
        # Tablero: punto de origen cerca de un borde
        tablero = (
            rng.randint(x0 + 10, x0 + 40),
            rng.randint(y0 + 10, y0 + 40),
        )
        # Tronco horizontal desde el tablero
        trunk_end_x = rng.randint((x0 + x1) // 2, x1 - 20)
        trunk = [(tablero[0], tablero[1]), (trunk_end_x, tablero[1])]

        cv2.line(mask, trunk[0], trunk[1], MASK_ELECTRICIDAD, DEFAULT_ELECTRICIDAD_THICK_PX)
        cv2.line(img, trunk[0], trunk[1], _COLOR_ELECTRICIDAD_BGR, DEFAULT_ELECTRICIDAD_THICK_PX, lineType=cv2.LINE_AA)
        counts["electricidad"] += 1

        # Derivaciones verticales hacia abajo
        n_der = rng.randint(2, 5)
        for _ in range(n_der):
            der_x = rng.randint(trunk[0][0], trunk[1][0])
            der_y_end = rng.randint(tablero[1] + 20, y1 - 10)
            p_top = (der_x, tablero[1])
            p_bot = (der_x, der_y_end)
            cv2.line(mask, p_top, p_bot, MASK_ELECTRICIDAD, DEFAULT_ELECTRICIDAD_THICK_PX)
            cv2.line(img, p_top, p_bot, _COLOR_ELECTRICIDAD_BGR, DEFAULT_ELECTRICIDAD_THICK_PX, lineType=cv2.LINE_AA)
            # Bifurcaciones horizontales desde la derivación
            if rng.random() < 0.5:
                bif_y = rng.randint(tablero[1] + 10, der_y_end - 10)
                bif_end_x = rng.randint(x0, x1)
                cv2.line(mask, (der_x, bif_y), (bif_end_x, bif_y), MASK_ELECTRICIDAD, DEFAULT_ELECTRICIDAD_THICK_PX)
                cv2.line(img, (der_x, bif_y), (bif_end_x, bif_y), _COLOR_ELECTRICIDAD_BGR, DEFAULT_ELECTRICIDAD_THICK_PX, lineType=cv2.LINE_AA)
            counts["electricidad"] += 1

    return counts


# ----------------------------------------------------------------------
# BSP de particionado en recintos
# ----------------------------------------------------------------------
def _bsp_split(rect: Rect, depth: int, max_depth: int, min_size: int, rng: random.Random) -> list[Rect]:
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    if depth >= max_depth or (w < 2 * min_size and h < 2 * min_size):
        return [rect]

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
# Primitivas de dibujo
# ----------------------------------------------------------------------
def _draw_wall(img, mask, p1: Point, p2: Point, rng: random.Random) -> None:
    import cv2

    img_thick = rng.choice([3, 4, 5, 6])
    cv2.line(img, p1, p2, (0, 0, 0), img_thick, lineType=cv2.LINE_AA)
    cv2.line(mask, p1, p2, MASK_WALL, DEFAULT_WALL_THICK_PX)


def _draw_beam(img, mask, p1: Point, p2: Point, rng: random.Random) -> None:
    import cv2

    cv2.line(mask, p1, p2, MASK_BEAM, DEFAULT_BEAM_THICK_PX)
    gray = rng.randint(90, 160)
    cv2.line(img, p1, p2, (gray, gray, gray), DEFAULT_BEAM_THICK_PX, lineType=cv2.LINE_AA)
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length
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
    cv2.rectangle(mask, p0, p1, MASK_COLUMN, -1)
    cv2.rectangle(img, p0, p1, (0, 0, 0), -1)


def _add_opening(img, mask, p1: Point, p2: Point, rng: random.Random, is_door: bool) -> bool:
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

    cv2.line(img, d1, d2, (255, 255, 255), DEFAULT_WALL_THICK_PX + 3)
    if is_door:
        nx, ny = -uy, ux
        hinge = d1
        end = (int(round(d1[0] + nx * width)), int(round(d1[1] + ny * width)))
        cv2.line(img, hinge, end, (0, 0, 0), 1, lineType=cv2.LINE_AA)
        ang = math.degrees(math.atan2(uy, ux))
        cv2.ellipse(img, hinge, (width, width), ang, 0, 90, (0, 0, 0), 1, lineType=cv2.LINE_AA)
    else:
        cv2.line(img, d1, d2, (0, 0, 0), 1, lineType=cv2.LINE_AA)

    cv2.line(mask, d1, d2, MASK_OPENING, DEFAULT_OPENING_THICK_PX)
    return True


# ----------------------------------------------------------------------
# Texto (solo imagen — el modelo debe ignorarlo)
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
# Helpers geométricos
# ----------------------------------------------------------------------
def _edge_on_boundary(edge: tuple[Point, Point], foot: Rect) -> bool:
    (ax, ay), (bx, by) = edge
    fx0, fy0, fx1, fy1 = foot
    if ax == bx and (ax == fx0 or ax == fx1):
        return True
    if ay == by and (ay == fy0 or ay == fy1):
        return True
    return False


def _random_boundary_edge(foot: Rect, rng: random.Random) -> tuple[Point, Point]:
    x0, y0, x1, y1 = foot
    sides = [
        ((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)),
        ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0)),
    ]
    return rng.choice(sides)


def _apply_photometric_noise(img, rng: random.Random) -> None:
    """Ruido fotométrico para acercar el sintético al dominio real."""
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
    # Leve variación de tono (simula distintos estilos CAD)
    if rng.random() < 0.15:
        tint = np.array([rng.randint(-8, 8), rng.randint(-8, 8), rng.randint(-8, 8)], dtype=np.int16)
        img[:] = np.clip(img.astype(np.int16) + tint, 0, 255).astype(np.uint8)
