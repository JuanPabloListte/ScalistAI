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
C_ROOF = 8
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


def _render_floor(geoms: list[tuple[int, list]], out_dir: Path):
    """geoms: lista de (clase, puntos_en_metros). Devuelve la máscara (np.uint8)
    si se guardó, o None. La máscara la usa _render_roof para derivar el techo."""
    import cv2

    all_pts = [p for _, ring in geoms for p in ring]
    if len(all_pts) < 6:
        return None
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
        return None

    out_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_dir / "image.png"), image)
    cv2.imwrite(str(out_dir / "mask.png"), mask)
    return mask


def _render_roof(mask, out_dir: Path) -> bool:
    """Deriva un plano de techos del footprint del edificio (contorno externo
    de todo lo ocupado en la máscara) y lo guarda como muestra propia: imagen
    estilo techo (contorno + cumbreras diagonales) + máscara rellena como roof.

    Es muestra SEPARADA (no se mezcla con el plano de planta) porque el techo
    cubre todo el edificio y pisaría recintos/muros. Así el modelo aprende a
    reconocer una lámina de techos sin contaminar el plano de arquitectura.
    Resuelve el roof=0.00: Swiss no trae techos, pero el footprint sí los da."""
    import cv2

    occ = ((mask > 0).astype(np.uint8)) * 255
    # cerrar huecos (recintos sin muro de borde) para un contorno externo limpio
    occ = cv2.morphologyEx(occ, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    cnts, _ = cv2.findContours(occ, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return False
    cnt = max(cnts, key=cv2.contourArea)
    if cv2.contourArea(cnt) < 5000:  # footprint demasiado chico → ruido
        return False
    hull = cv2.approxPolyDP(cnt, 3, True)

    image = np.full((TARGET, TARGET, 3), 255, np.uint8)
    rmask = np.zeros((TARGET, TARGET), np.uint8)
    cv2.fillPoly(rmask, [hull], C_ROOF)
    # Imagen tipo plano de techos: contorno marcado + cumbreras a 4 aguas.
    cv2.polylines(image, [hull], True, (60, 60, 60), 2)
    x, y, w, h = cv2.boundingRect(cnt)
    cx, cy = x + w // 2, y + h // 2
    for corner in ((x, y), (x + w, y), (x, y + h), (x + w, y + h)):
        cv2.line(image, corner, (cx, cy), (130, 130, 130), 1)

    out_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_dir / "image.png"), image)
    cv2.imwrite(str(out_dir / "mask.png"), rmask)
    return True


def run(csv_path: Path, out_root: Path, max_floors: int, min_walls: int,
        roof_frac: float = 0.3) -> None:
    # Dedupe real: agrupar TODAS las filas por floor_id (el CSV no está 100%
    # ordenado → el flush-on-change anterior pisaba pisos y los dejaba
    # incompletos). Acá cada floor_id junta su geometría completa y se renderiza
    # una sola vez.
    floors: dict[str, list[tuple[int, list]]] = defaultdict(list)
    wall_counts: dict[str, int] = defaultdict(int)

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        n = 0
        for row in reader:
            cls = _classify(row.get("entity_type", ""), row.get("entity_subtype", ""))
            if cls is None:
                continue
            ring = _parse_polygon(row.get("geometry", ""))
            if not ring:
                continue
            fid = row.get("floor_id")
            floors[fid].append((cls, ring))
            if cls == C_WALL:
                wall_counts[fid] += 1
            n += 1
            if n % 500000 == 0:
                print(f"  leídas {n} geometrías, {len(floors)} pisos...", flush=True)

    print(f"  {len(floors)} pisos únicos en el CSV; renderizando...", flush=True)

    # roof_frac: cada cuántos pisos se emite también una muestra de techo.
    roof_every = max(1, round(1 / roof_frac)) if roof_frac > 0 else 0
    saved = 0
    roofs = 0
    for fid in sorted(floors):
        if wall_counts[fid] < min_walls:
            continue
        out_dir = out_root / f"swiss_{fid}" / "var_001"
        mask = _render_floor(list(floors[fid]), out_dir)
        if mask is not None:
            saved += 1
            if roof_every and saved % roof_every == 0:
                if _render_roof(mask, out_root / f"swiss_{fid}" / "var_roof"):
                    roofs += 1
            if saved % 200 == 0:
                print(f"  guardados {saved} pisos ({roofs} techos)...", flush=True)
            if saved >= max_floors:
                break

    print(f"[done] {saved} pisos + {roofs} techos importados a {out_root}", flush=True)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--csv", required=True)
    p.add_argument("--out", default="storage/synthetic")
    p.add_argument("--max-floors", type=int, default=1500)
    p.add_argument("--min-walls", type=int, default=8)
    p.add_argument("--roof-frac", type=float, default=0.3,
                   help="Fracción de pisos que también generan muestra de techo (0=ninguna)")
    args = p.parse_args()
    run(Path(args.csv), Path(args.out), args.max_floors, args.min_walls, args.roof_frac)
    return 0


if __name__ == "__main__":
    sys.exit(main())
