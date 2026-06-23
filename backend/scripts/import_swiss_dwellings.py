"""Importa el dataset Swiss Dwellings (CC BY 4.0, Archilyse AG) como datos de
entrenamiento sintéticos.

geometries.csv trae, por piso (floor_id), la geometría WKT de muros, columnas,
aberturas, recintos y escaleras. Cada piso se renderiza como un par
(image.png, mask.png) de 512px en el MISMO formato que synthetic_generator,
así el trainer lo levanta sin cambios. Esto suma miles de plantas reales y
diversas — el desbloqueo para que el modelo generalice.

Atribución requerida (CC BY 4.0): "Swiss Dwellings dataset, Archilyse AG".

Uso:
    python -m scripts.import_swiss_dwellings --csv storage/datasets/swiss_geometries.csv \
        --out storage/synthetic --max-floors 1500 --min-walls 8
"""
from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

# Índices de clase (deben matchear scripts._common.CLASS_NAMES).
C_WALL, C_ROOM, C_DOOR, C_WINDOW, C_COLUMN, C_ESCALERA = 1, 2, 3, 4, 7, 12
TARGET = 512
MARGIN = 16

csv.field_size_limit(10_000_000)

# subtype (entity_type, entity_subtype) → (clase, dibuja_en_imagen)
_RING = re.compile(r"\(\(([^()]*)\)")


def _parse_polygon(wkt: str) -> list[tuple[float, float]] | None:
    """Anillo exterior de un POLYGON/MULTIPOLYGON WKT → lista de (x, y)."""
    m = _RING.search(wkt)
    if not m:
        return None
    pts = []
    for pair in m.group(1).split(","):
        p = pair.split()
        if len(p) >= 2:
            try:
                pts.append((float(p[0]), float(p[1])))
            except ValueError:
                return None
    return pts if len(pts) >= 2 else None


def _classify(et: str, st: str) -> int | None:
    st = (st or "").upper()
    if et == "separator":
        if st == "WALL":
            return C_WALL
        if st == "COLUMN":
            return C_COLUMN
        return None  # RAILING, etc.
    if et == "opening":
        if "WINDOW" in st:
            return C_WINDOW
        return C_DOOR  # DOOR, ENTRANCE_DOOR, ...
    if et == "area":
        return C_ROOM
    if et == "feature" and "STAIR" in st:
        return C_ESCALERA
    return None


def _render_floor(geoms: list[tuple[int, list]], out_dir: Path) -> bool:
    """geoms: lista de (clase, puntos_en_metros). Devuelve True si se guardó."""
    import cv2

    all_pts = [p for _, ring in geoms for p in ring]
    if len(all_pts) < 6:
        return False
    xs = [p[0] for p in all_pts]
    ys = [p[1] for p in all_pts]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    span = max(maxx - minx, maxy - miny, 1e-6)
    scale = (TARGET - 2 * MARGIN) / span

    def to_px(p):
        x = (p[0] - minx) * scale + MARGIN
        y = (maxy - p[1]) * scale + MARGIN  # flip Y (norte arriba)
        return [int(round(x)), int(round(y))]

    image = np.full((TARGET, TARGET, 3), 255, np.uint8)
    mask = np.zeros((TARGET, TARGET), np.uint8)

    # Orden: recintos (fondo) → muros → columnas → aberturas → escaleras.
    order = {C_ROOM: 0, C_WALL: 1, C_COLUMN: 2, C_DOOR: 3, C_WINDOW: 3, C_ESCALERA: 4}
    geoms.sort(key=lambda g: order.get(g[0], 9))

    for cls, ring in geoms:
        poly = np.array([to_px(p) for p in ring], np.int32)
        if len(poly) < 3:
            # línea (abertura fina): dibujar como segmento grueso
            if len(poly) == 2:
                cv2.line(mask, tuple(poly[0]), tuple(poly[1]), cls, 6)
                cv2.line(image, tuple(poly[0]), tuple(poly[1]), (90, 90, 90), 4)
            continue
        cv2.fillPoly(mask, [poly], cls)
        # Imagen: recinto = casi blanco, muro/columna = oscuro, abertura = gris,
        # escalera = gris medio con líneas.
        if cls == C_ROOM:
            cv2.fillPoly(image, [poly], (247, 247, 247))
        elif cls in (C_WALL, C_COLUMN):
            cv2.fillPoly(image, [poly], (40, 40, 40))
        elif cls in (C_DOOR, C_WINDOW):
            cv2.fillPoly(image, [poly], (120, 120, 120))
        elif cls == C_ESCALERA:
            cv2.fillPoly(image, [poly], (200, 200, 200))
            cv2.polylines(image, [poly], True, (110, 110, 110), 1)

    # Debe haber muros suficientes para ser útil
    if int((mask == C_WALL).sum()) < 200:
        return False

    out_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_dir / "image.png"), image)
    cv2.imwrite(str(out_dir / "mask.png"), mask)
    return True


def run(csv_path: Path, out_root: Path, max_floors: int, min_walls: int) -> None:
    cur_floor = None
    cur: list[tuple[int, list]] = []
    wall_count = 0
    saved = 0

    def flush(floor_id, geoms, n_walls):
        nonlocal saved
        if n_walls < min_walls:
            return
        out_dir = out_root / f"swiss_{floor_id}" / "var_001"
        if _render_floor(list(geoms), out_dir):
            saved += 1
            if saved % 100 == 0:
                print(f"  guardados {saved} pisos...", flush=True)

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            fid = row.get("floor_id")
            if fid != cur_floor:
                if cur_floor is not None:
                    flush(cur_floor, cur, wall_count)
                    if saved >= max_floors:
                        break
                cur_floor, cur, wall_count = fid, [], 0
            cls = _classify(row.get("entity_type", ""), row.get("entity_subtype", ""))
            if cls is None:
                continue
            ring = _parse_polygon(row.get("geometry", ""))
            if ring:
                cur.append((cls, ring))
                if cls == C_WALL:
                    wall_count += 1
        else:
            if cur_floor is not None and saved < max_floors:
                flush(cur_floor, cur, wall_count)

    print(f"[done] {saved} pisos importados a {out_root}", flush=True)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--csv", required=True)
    p.add_argument("--out", default="storage/synthetic")
    p.add_argument("--max-floors", type=int, default=1500)
    p.add_argument("--min-walls", type=int, default=8)
    args = p.parse_args()
    run(Path(args.csv), Path(args.out), args.max_floors, args.min_walls)
    return 0


if __name__ == "__main__":
    sys.exit(main())
