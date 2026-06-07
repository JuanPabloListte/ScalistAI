"""Generación de pares (image, mask) de entrenamiento a partir de archivos DXF.

El mismo mapeo de capas que usa `dxf_import.py` garantiza que la máscara
generada sea consistente con los DetectedElements que el import crea.

Llamado desde:
  - `dxf_import.build_dxf_plan()` al subir un DXF vía API (background)
  - `scripts/dxf_to_training.py` para procesar lotes de DXFs en disco
"""
from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path
from typing import Optional

# Mapeo: palabras clave de capa → (índice de clase, color BGR imagen)
# Índices de clase deben coincidir con _common.CLASS_NAMES de scripts/_common.py
LAYER_MAP: list[tuple[tuple[str, ...], int, tuple[int, int, int]]] = [
    (("MURO", "WALL"),                              1, (0, 0, 0)),
    (("PUERTA", "DOOR"),                            3, (0, 0, 0)),
    (("VENTANA", "WINDOW"),                         3, (0, 0, 0)),
    (("HABITACION", "ROOM", "RECINTO"),             2, (180, 180, 180)),
    (("VIGA", "BEAM"),                              6, (80, 80, 80)),
    (("COLUMNA", "COLUMN"),                         7, (0, 0, 0)),
    (("LOSA", "TECHO", "ROOF", "SLAB"),             8, (200, 200, 200)),
    (("CLOACA", "CLOACAL", "SANITARI", "DESAGUE", "PLUMB"), 10, (0, 90, 230)),
    (("ELECTRIC", "ILUMINAC", "TOMA", "TABLERO"),  11, (0, 210, 230)),
    (("RIOSTRA", "ENCADENADO", "FUNDACION", "ZAPATA"), 9, (30, 110, 190)),
]

# Grosor de trazo en la máscara (-1 = fill)
_MASK_THICK: dict[int, int] = {
    1: 4, 2: -1, 3: 8, 6: 18, 7: -1, 8: -1, 9: 18, 10: 6, 11: 4,
}

_TARGET_SIZE = 512
_TARGET_MAX_PX = 2000
_MARGIN_PX = 40


def _classify_layer(layer_name: str) -> Optional[tuple[int, tuple[int, int, int]]]:
    up = layer_name.upper()
    for keywords, cls_idx, color in LAYER_MAP:
        if any(k in up for k in keywords):
            return cls_idx, color
    return None


def _entity_points(entity) -> Optional[list[tuple[float, float]]]:
    kind = entity.dxftype()
    if kind == "LINE":
        s, e = entity.dxf.start, entity.dxf.end
        return [(s.x, s.y), (e.x, e.y)]
    if kind == "LWPOLYLINE":
        try:
            pts = [(p[0], p[1]) for p in entity.get_points(format="xy")]
        except Exception:  # noqa: BLE001
            return None
        if not pts:
            return None
        if getattr(entity, "closed", False) and len(pts) >= 2:
            pts = pts + [pts[0]]
        return pts
    if kind == "POLYLINE":
        try:
            pts = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
        except Exception:  # noqa: BLE001
            return None
        return pts or None
    return None


def _rotate_img(img, angle: int):
    import cv2
    codes = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}
    return cv2.rotate(img, codes[angle]) if angle in codes else img


def generate_from_dxf_path(
    dxf_path: Path,
    out_dir: Path,
    variations: int = 8,
    plan_id: int | None = None,
) -> int:
    """Genera pares (image.png, mask.png) a partir de un DXF guardado en disco.

    Devuelve la cantidad de variaciones escritas. Retorna 0 silenciosamente si el
    DXF no tiene capas clasificadas (no es un error grave — el plan ya fue importado).
    """
    import random

    import cv2
    import ezdxf
    import numpy as np

    try:
        doc = ezdxf.readfile(str(dxf_path))
    except Exception:  # noqa: BLE001
        return 0

    msp = doc.modelspace()
    all_pts: list[tuple[float, float]] = []
    segments_all: list[list[tuple[float, float]]] = []
    segments_cls: list[tuple[list[tuple[float, float]], int, tuple[int, int, int]]] = []

    for entity in msp:
        pts = _entity_points(entity)
        if not pts or len(pts) < 2:
            continue
        all_pts.extend(pts)
        segments_all.append(pts)
        try:
            layer = entity.dxf.layer
        except AttributeError:
            continue
        result = _classify_layer(layer)
        if result is not None:
            cls_idx, color = result
            segments_cls.append((pts, cls_idx, color))

    if not all_pts or not segments_cls:
        return 0

    gx1 = min(p[0] for p in all_pts)
    gy1 = min(p[1] for p in all_pts)
    gx2 = max(p[0] for p in all_pts)
    gy2 = max(p[1] for p in all_pts)
    width_m = max(gx2 - gx1, 1e-6)
    height_m = max(gy2 - gy1, 1e-6)
    span_m = max(width_m, height_m)
    px_per_m = min((_TARGET_MAX_PX - 2 * _MARGIN_PX) / span_m, 300.0)
    px_per_m = max(px_per_m, 20.0)

    img_w = int(math.ceil(width_m * px_per_m)) + 2 * _MARGIN_PX
    img_h = int(math.ceil(height_m * px_per_m)) + 2 * _MARGIN_PX

    def to_px(mx: float, my: float) -> tuple[int, int]:
        return (int((mx - gx1) * px_per_m + _MARGIN_PX),
                int((gy2 - my) * px_per_m + _MARGIN_PX))

    img_base = np.full((img_h, img_w, 3), 255, dtype=np.uint8)
    for seg in segments_all:
        pts_px = [to_px(x, y) for x, y in seg]
        for i in range(len(pts_px) - 1):
            cv2.line(img_base, pts_px[i], pts_px[i + 1], (110, 110, 110), 2, lineType=cv2.LINE_AA)
    for seg, cls_idx, color in segments_cls:
        pts_px = [to_px(x, y) for x, y in seg]
        thick = max(2, _MASK_THICK.get(cls_idx, 4)) if _MASK_THICK.get(cls_idx, 4) != -1 else 2
        for i in range(len(pts_px) - 1):
            cv2.line(img_base, pts_px[i], pts_px[i + 1], color, thick, lineType=cv2.LINE_AA)

    mask_base = np.zeros((img_h, img_w), dtype=np.uint8)
    for seg, cls_idx, _ in segments_cls:
        pts_px = [to_px(x, y) for x, y in seg]
        thick = _MASK_THICK.get(cls_idx, 4)
        if thick == -1:
            cv2.fillPoly(mask_base, [np.array(pts_px, dtype=np.int32)], cls_idx)
        else:
            for i in range(len(pts_px) - 1):
                cv2.line(mask_base, pts_px[i], pts_px[i + 1], cls_idx, thick)

    img_512 = cv2.resize(img_base, (_TARGET_SIZE, _TARGET_SIZE), interpolation=cv2.INTER_AREA)
    mask_512 = cv2.resize(mask_base, (_TARGET_SIZE, _TARGET_SIZE), interpolation=cv2.INTER_NEAREST)

    combos = [(r, f) for r in (0, 90, 180, 270) for f in (None, "h", "v")]
    rng = random.Random()
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot_at = dt.datetime.now(dt.UTC).isoformat()
    stem = dxf_path.stem
    written = 0

    for var_idx in range(variations):
        rot, flip = rng.choice(combos)
        img_v = _rotate_img(img_512, rot)
        mask_v = _rotate_img(mask_512, rot)
        if flip == "h":
            img_v = cv2.flip(img_v, 1)
            mask_v = cv2.flip(mask_v, 1)
        elif flip == "v":
            img_v = cv2.flip(img_v, 0)
            mask_v = cv2.flip(mask_v, 0)

        var_dir = out_dir / f"{stem}_var{var_idx + 1:03d}"
        var_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(var_dir / "image.png"), img_v)
        cv2.imwrite(str(var_dir / "mask.png"), mask_v)
        meta = {
            "source": "dxf",
            "dxf_file": dxf_path.name,
            "plan_id": plan_id,
            "variation": var_idx + 1,
            "rotation": rot,
            "flip": flip,
            "px_per_m": round(px_per_m, 3),
            "classes_present": [int(c) for c in np.unique(mask_v) if c > 0],
            "snapshot_at": snapshot_at,
        }
        (var_dir / "meta.json").write_text(json.dumps(meta, indent=2))
        written += 1

    return written
