import io
from typing import Dict, List, Optional

import ezdxf
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.detected_element import DetectedElement
from app.models.plan import Plan
from app.models.project import Project
from app.models.user import User

router = APIRouter(prefix="/integrations", tags=["integrations"])


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
]


def _classify_layer(layer: str) -> Optional[tuple[str, Optional[str]]]:
    up = layer.upper()
    for keywords, el_type, subtype in _LAYER_MAP:
        if any(k in up for k in keywords):
            return el_type, subtype
    return None


def _extract_bounding_box(entity) -> Optional[Dict[str, float]]:
    """Bounding box aproximado para LINE / LWPOLYLINE / POLYLINE."""
    kind = entity.dxftype()
    if kind == "LINE":
        s, e = entity.dxf.start, entity.dxf.end
        return {
            "x1": min(s.x, e.x),
            "y1": min(s.y, e.y),
            "x2": max(s.x, e.x),
            "y2": max(s.y, e.y),
        }
    if kind in ("LWPOLYLINE", "POLYLINE"):
        try:
            pts = list(entity.get_points(format="xy")) if kind == "LWPOLYLINE" else [
                (v.dxf.location.x, v.dxf.location.y) for v in entity.vertices
            ]
        except Exception:
            return None
        if not pts:
            return None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return {"x1": min(xs), "y1": min(ys), "x2": max(xs), "y2": max(ys)}
    return None


def _bbox_to_points(bbox: Dict[str, float], is_line: bool, thickness: float = 0.15) -> List[float]:
    """Convierte un bbox a lista plana de puntos [x1,y1,x2,y1,x2,y2,x1,y2]."""
    x1, y1, x2, y2 = bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"]
    if is_line:
        # Una LINE perfectamente axial colapsa a 0 en una dimensión: le damos
        # grosor mínimo en la dimensión que colapsó.
        if abs(x1 - x2) < 0.01:
            x1 -= thickness / 2
            x2 += thickness / 2
        elif abs(y1 - y2) < 0.01:
            y1 -= thickness / 2
            y2 += thickness / 2
    return [x1, y1, x2, y1, x2, y2, x1, y2]


@router.post("/dxf/upload")
async def upload_dxf(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not file.filename or not file.filename.lower().endswith(".dxf"):
        raise HTTPException(status_code=400, detail="El archivo debe ser un .dxf")
    if not user.organization_id:
        raise HTTPException(status_code=403, detail="Usuario sin organización asignada")

    content = await file.read()
    try:
        text = content.decode("utf-8", errors="ignore")
        doc = ezdxf.read(io.StringIO(text))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error leyendo DXF: {e}")

    msp = doc.modelspace()

    project = Project(
        name=f"Importación AutoCAD: {file.filename}",
        description="Proyecto generado automáticamente desde archivo DXF.",
        status="active",
        wizard_step=5,
        organization_id=user.organization_id,
        user_id=user.id,
    )
    db.add(project)
    db.flush()

    plan = Plan(
        project_id=project.id,
        original_filename=file.filename,
        pdf_path=f"virtual_dxf/{file.filename}",
        page=1,
        page_count=1,
        scale_px_per_m=1.0,  # DXF: las coordenadas ya están en metros (1:1)
        scale_source="dxf",
        status="success",
    )
    db.add(plan)
    db.flush()

    elements: List[DetectedElement] = []
    for entity in msp:
        try:
            layer = entity.dxf.layer
        except AttributeError:
            continue
        classified = _classify_layer(layer)
        if classified is None:
            continue
        el_type, subtype = classified

        bbox = _extract_bounding_box(entity)
        if bbox is None:
            continue

        is_line = entity.dxftype() == "LINE"
        points = _bbox_to_points(bbox, is_line=is_line)

        width = abs(bbox["x2"] - bbox["x1"]) or 0.15
        height = abs(bbox["y2"] - bbox["y1"]) or 0.15
        area = width * height
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

    db.commit()

    return {
        "success": True,
        "project_id": project.id,
        "plan_id": plan.id,
        "elements_imported": len(elements),
    }
