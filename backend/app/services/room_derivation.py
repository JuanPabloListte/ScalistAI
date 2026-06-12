"""Derivación geométrica de recintos a partir de los muros.

Un recinto es el área cerrada que delimitan los muros — nadie lo dibuja en
CAD, pero se puede calcular: se rasterizan los ejes de muro con su espesor,
se hace flood-fill desde el exterior, y cada hueco interior que queda es un
recinto. Sirve para llenar la clase 'room' del dataset de entrenamiento con
geometría consistente con los muros exactos.

Solo crea recintos donde no los haya (no pisa los dibujados a mano).
"""

import logging
import math

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Espesor con que se dibujan los muros para cerrar los recintos. Más grueso
# que el muro real para cerrar vanos de puertas (si no, dos ambientes
# conectados por una puerta serían un solo recinto).
_WALL_THICK_M = 0.45
_MIN_ROOM_M2 = 1.5     # placares chicos quedan afuera
_MAX_ROOM_M2 = 300.0   # más grande que esto = patio/exterior mal cerrado
_SIMPLIFY_PX = 3.0     # tolerancia del approxPolyDP


def derive_rooms_for_page(
    walls: list,           # DetectedElement type='wall' de la página
    px_per_m: float,
    img_w: int,
    img_h: int,
) -> list[dict]:
    """Devuelve recintos como dicts {points: [...], area_m2: float}.

    `walls` deben ser segmentos de 2+ puntos en píxeles de la página.
    """
    if not walls or px_per_m <= 0:
        return []

    mask = np.zeros((img_h, img_w), dtype=np.uint8)
    thick = max(2, int(_WALL_THICK_M * px_per_m))
    for w in walls:
        pts = w.geometry.get("points") or []
        xy = [(int(round(x)), int(round(y))) for x, y in zip(pts[0::2], pts[1::2])]
        for a, b in zip(xy, xy[1:]):
            cv2.line(mask, a, b, 255, thickness=thick)

    # Flood-fill desde los bordes: lo conectado al exterior no es recinto.
    free = (mask == 0).astype(np.uint8)
    ff_mask = np.zeros((img_h + 2, img_w + 2), dtype=np.uint8)
    exterior = free.copy()
    for seed in [(0, 0), (img_w - 1, 0), (0, img_h - 1), (img_w - 1, img_h - 1)]:
        if exterior[seed[1], seed[0]]:
            cv2.floodFill(exterior, ff_mask, seed, 2)
    interior = ((exterior == 1) & (free == 1)).astype(np.uint8)

    # Componentes conexas del interior = recintos candidatos.
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(interior, connectivity=4)
    rooms: list[dict] = []
    min_px = _MIN_ROOM_M2 * px_per_m * px_per_m
    max_px = _MAX_ROOM_M2 * px_per_m * px_per_m

    for lbl in range(1, n_labels):
        area_px = stats[lbl, cv2.CC_STAT_AREA]
        if area_px < min_px or area_px > max_px:
            continue
        comp = (labels == lbl).astype(np.uint8)
        contours, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        cnt = max(contours, key=cv2.contourArea)
        approx = cv2.approxPolyDP(cnt, _SIMPLIFY_PX, True)
        if len(approx) < 3:
            continue
        flat: list[float] = []
        for p in approx.reshape(-1, 2):
            flat.extend([float(p[0]), float(p[1])])
        area_m2 = cv2.contourArea(approx) / (px_per_m * px_per_m)
        if area_m2 < _MIN_ROOM_M2:
            continue
        rooms.append({
            "points": [round(v, 2) for v in flat],
            "area_m2": round(area_m2, 2),
        })

    logger.info("room derivation: %d recintos de %d muros", len(rooms), len(walls))
    return rooms


def derive_rooms_for_plan(plan_id: int, db, only_pages: list[int] | None = None) -> int:
    """Crea DetectedElement(type='room', source='dxf') derivados de los muros
    de cada página. Salta páginas que ya tienen recintos. Devuelve creados."""
    from pathlib import Path

    from PIL import Image

    from app.models import DetectedElement, Plan

    plan = db.get(Plan, plan_id)
    if plan is None:
        return 0

    created = 0
    for page in range(1, (plan.page_count or 1) + 1):
        if only_pages and page not in only_pages:
            continue
        existing_rooms = (
            db.query(DetectedElement)
            .filter(DetectedElement.plan_id == plan_id,
                    DetectedElement.page == page,
                    DetectedElement.type == "room")
            .count()
        )
        if existing_rooms:
            continue
        walls = (
            db.query(DetectedElement)
            .filter(DetectedElement.plan_id == plan_id,
                    DetectedElement.page == page,
                    DetectedElement.type == "wall",
                    DetectedElement.is_candidate.is_(False))
            .all()
        )
        if len(walls) < 4:
            continue
        px_per_m = (plan.page_scales or {}).get(str(page)) or plan.scale_px_per_m
        if not px_per_m:
            continue

        # Dimensiones de la página: PNG gemelo (CAD) o raster del PDF.
        src = Path(plan.pdf_path)
        if src.suffix.lower() == ".svg":
            stem = src.stem[:-3] if src.stem.endswith("_p1") else src.stem
            png = src.with_name(f"{stem}_p{page}.png")
            if not png.exists():
                continue
            with Image.open(png) as im:
                img_w, img_h = im.size
        else:
            import fitz
            doc = fitz.open(str(src))
            try:
                zoom = (plan.dpi or 150) / 72.0
                rect = doc[page - 1].rect
                img_w, img_h = int(rect.width * zoom), int(rect.height * zoom)
            finally:
                doc.close()

        rooms = derive_rooms_for_page(walls, float(px_per_m), img_w, img_h)
        for r in rooms:
            db.add(DetectedElement(
                plan_id=plan_id,
                page=page,
                type="room",
                geometry={"points": r["points"]},
                area_m2=r["area_m2"],
                height_m=2.8,
                source="dxf",
            ))
        created += len(rooms)

    return created
