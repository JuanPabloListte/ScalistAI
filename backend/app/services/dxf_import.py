"""Importación de planos DXF.

A diferencia de un PDF (que se rasteriza on-demand), un DXF trae geometría
vectorial en coordenadas de modelo (se asumen **metros**, escala 1:1). Para que
el visor —100% basado en raster + overlays en píxeles— pueda mostrarlo y
editarlo como cualquier otro plano, en el import:

  1. Parseamos las entidades dibujables (LINE / LWPOLYLINE / POLYLINE).
  2. Calculamos el bounding box global y un factor `px_per_m` para que el
     dibujo entre en un PNG de tamaño razonable.
  3. Transformamos metros → píxeles (con flip del eje Y: en DXF crece hacia
     arriba, en imagen hacia abajo) y renderizamos un PNG de fondo dibujando las
     entidades. Ese PNG se guarda en la ruta de caché del raster, así el
     endpoint `/plans/{id}/raster` lo sirve sin cambios.
  4. Creamos el Plan con `status="ready"`, `page_scales={"1": px_per_m}` y los
     DetectedElement con geometría **en píxeles** (igual que un PDF), de modo que
     las mediciones (`length_m`/`area_m2`) y la asignación de materiales
     funcionan exactamente igual.
"""

import io
import math
import uuid
from pathlib import Path
from typing import Optional

import ezdxf
from fastapi import HTTPException
from PIL import Image, ImageDraw
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.detected_element import DetectedElement
from app.models.plan import Plan

# Mapeo de palabra clave en el nombre de capa → (type, subtype) del DetectedElement.
# El modelo solo conoce wall/room/opening/column/beam/roof. Puertas y ventanas son
# `opening` con un subtype en geometry.
_LAYER_MAP: list[tuple[tuple[str, ...], str, Optional[str]]] = [
    (("MURO", "WALL"), "wall", None),
    (("PUERTA", "DOOR"), "opening", "door"),
    (("VENTANA", "WINDOW"), "opening", "window"),
    (("HABITACION", "ROOM", "RECINTO"), "room", None),
    (("VIGA", "BEAM"), "beam", None),
    (("COLUMNA", "COLUMN"), "column", None),
    (("LOSA", "TECHO", "ROOF", "SLAB"), "roof", None),
    (("CLOACA", "CLOACAL", "SANITARI", "DESAGUE", "PLUMB"), "cloaca", None),
    (("ELECTRIC", "ILUMINAC", "TOMA", "TABLERO"), "electricidad", None),
    (("RIOSTRA", "ENCADENADO", "FUNDACION", "ZAPATA"), "riostra", None),
]

# Parámetros de render del PNG de fondo.
_TARGET_MAX_PX = 2000  # lado mayor objetivo del PNG
_MAX_IMG_PX = 4000     # techo duro para no generar imágenes gigantes
_MIN_PX_PER_M = 20.0
_MAX_PX_PER_M = 300.0
_DEFAULT_PX_PER_M = 100.0
_MARGIN_PX = 40
_LINE_THICKNESS_M = 0.15  # grosor mínimo en metros para una LINE axial


def _classify_layer(layer: str) -> Optional[tuple[str, Optional[str]]]:
    up = layer.upper()
    for keywords, el_type, subtype in _LAYER_MAP:
        if any(k in up for k in keywords):
            return el_type, subtype
    return None


def _entity_polyline(entity) -> Optional[list[tuple[float, float]]]:
    """Secuencia de puntos (x, y) en coords de modelo para LINE / *POLYLINE."""
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


def _bbox_of(pts: list[tuple[float, float]]) -> dict[str, float]:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return {"x1": min(xs), "y1": min(ys), "x2": max(xs), "y2": max(ys)}


def build_dxf_plan(
    project_id: int, content: bytes, filename: str, db: Session
) -> tuple[Plan, int]:
    """Parsea un DXF, genera su PNG de fondo y crea el Plan (+ DetectedElements)
    adjunto al proyecto indicado. El caller es responsable del `commit`.

    Devuelve (plan, cantidad de elementos importados).
    """
    try:
        text = content.decode("utf-8", errors="ignore")
        doc = ezdxf.read(io.StringIO(text))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Error leyendo DXF: {e}")

    msp = doc.modelspace()

    # 1) Recolectar entidades dibujables + clasificadas en una sola pasada.
    segments: list[list[tuple[float, float]]] = []
    classified: list[tuple[str, Optional[str], dict[str, float], bool]] = []
    for entity in msp:
        pts = _entity_polyline(entity)
        if not pts or len(pts) < 2:
            continue
        segments.append(pts)

        try:
            layer = entity.dxf.layer
        except AttributeError:
            continue
        kind = _classify_layer(layer)
        if kind is None:
            continue
        el_type, subtype = kind
        classified.append((el_type, subtype, _bbox_of(pts), entity.dxftype() == "LINE"))

    # 2) Bounding box global y factor px/m.
    if segments:
        all_pts = [p for seg in segments for p in seg]
        gx1 = min(p[0] for p in all_pts)
        gy1 = min(p[1] for p in all_pts)
        gx2 = max(p[0] for p in all_pts)
        gy2 = max(p[1] for p in all_pts)
    else:
        gx1, gy1, gx2, gy2 = 0.0, 0.0, 1.0, 1.0

    width_m = max(gx2 - gx1, 1e-6)
    height_m = max(gy2 - gy1, 1e-6)
    span_m = max(width_m, height_m)

    px_per_m = (_TARGET_MAX_PX - 2 * _MARGIN_PX) / span_m if span_m > 0 else _DEFAULT_PX_PER_M
    px_per_m = max(_MIN_PX_PER_M, min(_MAX_PX_PER_M, px_per_m))
    # Techo duro de tamaño de imagen para dibujos enormes.
    if span_m * px_per_m + 2 * _MARGIN_PX > _MAX_IMG_PX:
        px_per_m = (_MAX_IMG_PX - 2 * _MARGIN_PX) / span_m

    def to_px(mx: float, my: float) -> tuple[float, float]:
        x = (mx - gx1) * px_per_m + _MARGIN_PX
        y = (gy2 - my) * px_per_m + _MARGIN_PX  # flip vertical
        return (x, y)

    img_w = int(math.ceil(width_m * px_per_m)) + 2 * _MARGIN_PX
    img_h = int(math.ceil(height_m * px_per_m)) + 2 * _MARGIN_PX
    img_w = max(img_w, 2 * _MARGIN_PX + 10)
    img_h = max(img_h, 2 * _MARGIN_PX + 10)

    # 3) Persistir el DXF original y renderizar el PNG de fondo en la ruta de
    #    caché del raster (mismo esquema de nombres que usa plans.py:
    #    "<stem>_p<page>.png").
    plan_storage = Path(settings.STORAGE_DIR) / "plans" / str(project_id)
    plan_storage.mkdir(parents=True, exist_ok=True)
    file_id = uuid.uuid4().hex
    dxf_path = plan_storage / f"{file_id}.dxf"
    dxf_path.write_bytes(content)
    raster_path = dxf_path.with_name(f"{dxf_path.stem}_p1.png")

    img = Image.new("RGB", (img_w, img_h), "white")
    draw = ImageDraw.Draw(img)
    for seg in segments:
        line_px = [to_px(x, y) for (x, y) in seg]
        if len(line_px) >= 2:
            draw.line(line_px, fill=(110, 110, 110), width=2, joint="curve")
    img.save(raster_path, "PNG")

    # 4) Crear el Plan.
    plan = Plan(
        project_id=project_id,
        original_filename=filename,
        pdf_path=str(dxf_path),
        dpi=None,
        page=1,
        page_count=1,
        scale_px_per_m=round(px_per_m, 4),
        scale_source="dxf",
        page_scales={"1": round(px_per_m, 4)},
        status="ready",
    )
    db.add(plan)
    db.flush()

    # 5) Crear los DetectedElement con geometría en píxeles.
    elements: list[DetectedElement] = []
    for el_type, subtype, bbox, is_line in classified:
        x1, y1, x2, y2 = bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"]
        width = abs(x2 - x1)
        height = abs(y2 - y1)
        # LINE axial: dar grosor mínimo en la dimensión colapsada (en metros).
        if is_line:
            if width < 0.01:
                x1 -= _LINE_THICKNESS_M / 2
                x2 += _LINE_THICKNESS_M / 2
                width = _LINE_THICKNESS_M
            elif height < 0.01:
                y1 -= _LINE_THICKNESS_M / 2
                y2 += _LINE_THICKNESS_M / 2
                height = _LINE_THICKNESS_M

        # Rectángulo en píxeles (4 esquinas, formato plano).
        p_tl = to_px(x1, y2)  # top-left  (y mayor → arriba tras el flip)
        p_tr = to_px(x2, y2)
        p_br = to_px(x2, y1)
        p_bl = to_px(x1, y1)
        points = [
            p_tl[0], p_tl[1],
            p_tr[0], p_tr[1],
            p_br[0], p_br[1],
            p_bl[0], p_bl[1],
        ]

        area = (width or _LINE_THICKNESS_M) * (height or _LINE_THICKNESS_M)
        length = max(width, height) if is_line else None

        geometry: dict = {"points": points}
        if subtype:
            geometry["subtype"] = subtype

        elements.append(
            DetectedElement(
                plan_id=plan.id,
                page=1,
                type=el_type,
                geometry=geometry,
                area_m2=area if el_type in ("wall", "room", "roof", "opening") else None,
                length_m=length,
                source="manual",
            )
        )

    if elements:
        db.add_all(elements)

    return plan, len(elements)
