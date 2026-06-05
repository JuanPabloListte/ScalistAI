"""Convierte archivos DXF en pares (image.png, mask.png) para entrenar el modelo.

Las capas del DXF son las anotaciones: capa "MUROS" = muros, "CLOACAS" = cloacas,
etc. No hay que dibujar nada a mano — la geometría vectorial del DXF genera ground
truth perfecto.

Flujo:
  1. Lee todos los .dxf de --input-dir.
  2. Para cada archivo: renderiza la imagen completa (todas las capas, gris) y
     construye la máscara dibujando cada capa clasificada con su índice de clase.
  3. Redimensiona a 512×512 y guarda en --out-dir con el mismo formato que
     storage/synthetic (image.png + mask.png + meta.json).
  4. Genera también variaciones geométricas (rot/flip) para multiplicar el dataset.

Uso:
    cd backend
    python -m scripts.dxf_to_training --input-dir /ruta/a/mis/dxfs --variations 12
    # luego finetunear:
    python -m scripts.finetune_model --epochs 20

Mapeo de capas (configurable con --layer-map JSON):
    Default: MURO→wall, PUERTA→door, VENTANA→window, RECINTO→room,
             VIGA→beam, COLUMNA→column, LOSA→roof,
             CLOACA→cloaca, ELECTRIC→electricidad, RIOSTRA→riostra

El mapeo busca la palabra clave en el nombre de capa (case-insensitive).
Si una capa no matchea ninguna keyword, sus entidades van solo a la imagen
(como texto/cotas) pero no a la máscara.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path
from typing import Optional


# Mapeo keyword → (mask_class_index, color_BGR_imagen)
# El color en imagen imita colores reales de planos argentinos.
_DEFAULT_LAYER_MAP: list[tuple[tuple[str, ...], int, tuple[int, int, int]]] = [
    (("MURO", "WALL"),                      1,  (0, 0, 0)),        # negro
    (("PUERTA", "DOOR"),                    3,  (0, 0, 0)),        # negro
    (("VENTANA", "WINDOW"),                 3,  (0, 0, 0)),        # negro
    (("HABITACION", "ROOM", "RECINTO"),     2,  (180, 180, 180)),  # gris claro
    (("VIGA", "BEAM"),                      6,  (80, 80, 80)),     # gris oscuro
    (("COLUMNA", "COLUMN"),                 7,  (0, 0, 0)),        # negro
    (("LOSA", "TECHO", "ROOF", "SLAB"),     8,  (200, 200, 200)),  # gris muy claro
    (("CLOACA", "CLOACAL", "SANITARI",
      "DESAGUE", "PLUMB"),                 10,  (0, 90, 230)),     # naranja
    (("ELECTRIC", "ILUMINAC",
      "TOMA", "TABLERO"),                  11,  (0, 210, 230)),    # amarillo
    (("RIOSTRA", "ENCADENADO",
      "FUNDACION", "ZAPATA"),               9,  (30, 110, 190)),   # marrón-naranja
]

# Grosor de línea en píxeles al dibujar en la máscara (tras el resize a px_per_m)
_MASK_THICK: dict[int, int] = {
    1: 4,   # wall
    2: -1,  # room (fill)
    3: 8,   # opening
    6: 18,  # beam
    7: -1,  # column (fill)
    8: -1,  # roof (fill)
    9: 18,  # riostra
    10: 6,  # cloaca
    11: 4,  # electricidad
}

_TARGET_SIZE = 512
_TARGET_MAX_PX = 2000
_MARGIN_PX = 40


def _classify_layer(layer_name: str, layer_map) -> Optional[tuple[int, tuple[int, int, int]]]:
    up = layer_name.upper()
    for keywords, cls_idx, color in layer_map:
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
        except Exception:
            return None
        if not pts:
            return None
        if getattr(entity, "closed", False) and len(pts) >= 2:
            pts = pts + [pts[0]]
        return pts
    if kind == "POLYLINE":
        try:
            pts = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
        except Exception:
            return None
        return pts or None
    return None


def _process_dxf(dxf_path: Path, out_dir: Path, layer_map, variations: int, rng) -> int:
    """Procesa un DXF: genera image+mask y sus variaciones. Devuelve cantidad generada."""
    import cv2
    import ezdxf
    import numpy as np

    try:
        doc = ezdxf.readfile(str(dxf_path))
    except Exception as e:
        print(f"  [WARN] No se pudo leer {dxf_path.name}: {e}")
        return 0

    msp = doc.modelspace()

    # Recolectar entidades
    all_pts: list[tuple[float, float]] = []
    segments_all: list[list[tuple[float, float]]] = []        # todas (para imagen)
    segments_cls: list[tuple[list[tuple[float, float]], int, tuple[int, int, int]]] = []  # clasificadas

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
        result = _classify_layer(layer, layer_map)
        if result is not None:
            cls_idx, color = result
            segments_cls.append((pts, cls_idx, color))

    if not all_pts:
        print(f"  [WARN] {dxf_path.name}: sin entidades dibujables")
        return 0

    if not segments_cls:
        print(f"  [WARN] {dxf_path.name}: ninguna capa clasificada — revisá los nombres de capas")
        return 0

    # Bounding box y factor px/m
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
        x = int((mx - gx1) * px_per_m + _MARGIN_PX)
        y = int((gy2 - my) * px_per_m + _MARGIN_PX)  # flip Y
        return (x, y)

    # Renderizar imagen base (todas las capas en gris, como un plano real)
    img_base = np.full((img_h, img_w, 3), 255, dtype=np.uint8)
    for seg in segments_all:
        pts_px = [to_px(x, y) for x, y in seg]
        for i in range(len(pts_px) - 1):
            cv2.line(img_base, pts_px[i], pts_px[i + 1], (110, 110, 110), 2, lineType=cv2.LINE_AA)

    # Superponer colores de las capas clasificadas en la imagen
    for seg, cls_idx, color in segments_cls:
        pts_px = [to_px(x, y) for x, y in seg]
        thick_img = max(2, _MASK_THICK.get(cls_idx, 4))
        if thick_img == -1:
            thick_img = 2
        for i in range(len(pts_px) - 1):
            cv2.line(img_base, pts_px[i], pts_px[i + 1], color, thick_img, lineType=cv2.LINE_AA)

    # Renderizar máscara (solo capas clasificadas)
    mask_base = np.zeros((img_h, img_w), dtype=np.uint8)
    for seg, cls_idx, _ in segments_cls:
        pts_px = [to_px(x, y) for x, y in seg]
        thick = _MASK_THICK.get(cls_idx, 4)
        if thick == -1:
            # Fill: dibujar polígono relleno
            poly = np.array(pts_px, dtype=np.int32)
            cv2.fillPoly(mask_base, [poly], cls_idx)
        else:
            for i in range(len(pts_px) - 1):
                cv2.line(mask_base, pts_px[i], pts_px[i + 1], cls_idx, thick)

    # Redimensionar a 512×512
    img_512 = cv2.resize(img_base, (_TARGET_SIZE, _TARGET_SIZE), interpolation=cv2.INTER_AREA)
    mask_512 = cv2.resize(mask_base, (_TARGET_SIZE, _TARGET_SIZE), interpolation=cv2.INTER_NEAREST)

    # Variaciones geométricas (rot × flip)
    combos = [(rot, flip) for rot in (0, 90, 180, 270) for flip in (None, "h", "v")]
    written = 0
    snapshot_at = dt.datetime.now(dt.UTC).isoformat()
    stem = dxf_path.stem

    for var_idx in range(variations):
        rot, flip = rng.choice(combos)

        img_v = _rotate(img_512, rot)
        mask_v = _rotate(mask_512, rot)
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

        classes_present = [int(c) for c in np.unique(mask_v) if c > 0]
        meta = {
            "source": "dxf",
            "dxf_file": dxf_path.name,
            "variation": var_idx + 1,
            "rotation": rot,
            "flip": flip,
            "px_per_m": round(px_per_m, 3),
            "classes_present": classes_present,
            "snapshot_at": snapshot_at,
        }
        (var_dir / "meta.json").write_text(json.dumps(meta, indent=2))
        written += 1

    return written


def _rotate(img, angle: int):
    import cv2
    if angle == 0:
        return img
    if angle == 90:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if angle == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    if angle == 270:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return img


def main() -> int:
    parser = argparse.ArgumentParser(description="Convierte DXF en pares image+mask para entrenamiento.")
    parser.add_argument("--input-dir", required=True,
                        help="Directorio con archivos .dxf")
    parser.add_argument("--out-dir", default="storage/dxf_training",
                        help="Directorio de salida (default: storage/dxf_training)")
    parser.add_argument("--variations", type=int, default=12,
                        help="Variaciones geométricas por archivo (default: 12 = 4 rot × 3 flip)")
    parser.add_argument("--layer-map", default=None,
                        help="JSON file con mapeo custom de capas (opcional)")
    args = parser.parse_args()

    import random
    rng = random.Random()

    layer_map = _DEFAULT_LAYER_MAP
    if args.layer_map:
        # Permite customizar el mapeo sin tocar el código
        try:
            custom = json.loads(Path(args.layer_map).read_text())
            layer_map = [
                (tuple(entry["keywords"]), entry["class_idx"], tuple(entry["color_bgr"]))
                for entry in custom
            ]
            print(f"[setup] Usando layer-map custom con {len(layer_map)} entradas")
        except Exception as e:
            print(f"[WARN] No se pudo leer --layer-map: {e}. Usando default.")

    input_dir = Path(args.input_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    dxf_files = sorted(input_dir.glob("**/*.dxf")) + sorted(input_dir.glob("**/*.DXF"))
    if not dxf_files:
        print(f"ERROR: no se encontraron .dxf en {input_dir}")
        return 1

    print(f"[setup] {len(dxf_files)} archivos DXF encontrados en {input_dir}")
    print(f"[setup] {args.variations} variaciones por archivo → {len(dxf_files) * args.variations} samples máx.")
    print(f"[setup] salida en {out_dir}")
    print("-" * 60)

    total = 0
    for dxf_path in dxf_files:
        print(f"  procesando {dxf_path.name}...")
        n = _process_dxf(dxf_path, out_dir, layer_map, args.variations, rng)
        print(f"    → {n} variaciones generadas")
        total += n

    print("-" * 60)
    print(f"[done] {total} samples en {out_dir}")
    print(f"[done] para entrenar:")
    print(f"       python -m scripts.finetune_model --epochs 20 "
          f"--extra-data-dir {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
