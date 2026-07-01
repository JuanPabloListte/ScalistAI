"""Import de modelos BIM en formato **IFC** (texto STEP, abierto) → cómputo exacto.

A diferencia del PDF/DXF, el IFC ya es el modelo: muros, losas, aberturas y
columnas son objetos con cantidades. No hay que detectar nada. Se mapea cada
entidad IFC al tipo de `DetectedElement` del sistema y se alimenta el motor de
costos tal cual.

Cantidades: se prefieren las **base quantities** embebidas (si el export las
trae); si no, se calculan de la **geometría** (IfcOpenShell). Se descarta el
"ruido de contexto" (medianeras/terreno) por tamaño.

No tiene páginas ni raster: el IFC salta el visor → va directo al presupuesto.
"""
from __future__ import annotations

from collections import Counter
from typing import Optional

# Un muro/viga no supera esto; más largo = degenerado/contexto. Las losas SÍ
# pueden ser plateas grandes (edificios largos), por eso su límite es mayor.
CONTEXT_MAX_M = 50.0
SLAB_MAX_M = 200.0
DEFAULT_HEIGHT_M = 2.8
# Niveles NO habitables: sus losas no cuentan como piso cubierto (evita inflar el área).
_AUX_STOREY_KW = ("TECHO", "TANQUE", "CUBIERTA", "AZOTEA", "VIGA", "CIMIENT", "FUNDAC", "SOBRE LOSA")


def _num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def parse_ifc(path: str) -> tuple[list[dict], dict]:
    """Devuelve (elementos, meta). Cada elemento: type + length_m/area_m2/height_m
    + subtype. meta: schema, contadores crudos."""
    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.util.element as UE
    import ifcopenshell.util.unit as UU

    f = ifcopenshell.open(path)
    scale = UU.calculate_unit_scale(f)  # *scale -> metros
    settings = ifcopenshell.geom.settings()
    # Coordenadas LOCALES: cada elemento en su propio marco -> el bbox da su
    # tamaño real. Con world-coords la geometría se infla (transform global).
    settings.set(settings.USE_WORLD_COORDS, False)

    def qty(el, *names) -> Optional[float]:
        psets = UE.get_psets(el, qtos_only=True)
        for pset in psets.values():
            for name in names:
                if name in pset and isinstance(pset[name], (int, float)):
                    return float(pset[name])
        return None

    def bbox(el) -> Optional[tuple[float, float, float]]:
        try:
            v = ifcopenshell.geom.create_shape(settings, el).geometry.verts
        except Exception:
            return None
        if not v:
            return None
        xs, ys, zs = v[0::3], v[1::3], v[2::3]
        return ((max(xs) - min(xs)) * scale, (max(ys) - min(ys)) * scale, (max(zs) - min(zs)) * scale)

    out: list[dict] = []
    raw = Counter()

    # --- Aberturas: medida directa (exacta), sin geometría ---
    for d in f.by_type("IfcDoor"):
        w, h = _num(d.OverallWidth) * scale, _num(d.OverallHeight) * scale
        if w > 0 and h > 0:
            out.append({"type": "opening", "length_m": w, "height_m": h, "subtype": "door"})
            raw["door"] += 1
    for wd in f.by_type("IfcWindow"):
        w, h = _num(wd.OverallWidth) * scale, _num(wd.OverallHeight) * scale
        if w > 0 and h > 0:
            out.append({"type": "opening", "length_m": w, "height_m": h, "subtype": "window"})
            raw["window"] += 1

    # --- Muros: largo × alto (cordura: espesor < 1m) ---
    for wl in f.by_type("IfcWall"):
        length, height = qty(wl, "Length"), qty(wl, "Height", "NetHeight")
        if length is not None and height is not None:
            length, height = length * scale, height * scale
        else:
            bb = bbox(wl)
            if not bb or min(bb[0], bb[1]) > 1.0:  # espesor dudoso -> geometría rota
                continue
            length = length * scale if length is not None else max(bb[0], bb[1])
            height = height * scale if height is not None else bb[2]
        if not (0 < length <= 30 and 0 < height <= 8):
            continue
        out.append({"type": "wall", "length_m": length, "height_m": height})
        raw["wall"] += 1

    # --- Losas: ROOF -> cubierta · FLOOR -> ambiente (huella = piso) ---
    has_space = len(f.by_type("IfcSpace")) > 0
    for sl in f.by_type("IfcSlab"):
        pt = str(sl.PredefinedType)
        if pt not in ("FLOOR", "ROOF"):
            continue
        area = qty(sl, "GrossArea", "NetArea", "GrossFloorArea")
        if area is not None:
            area = area * scale * scale
        else:
            bb = bbox(sl)
            if not bb or bb[2] > 1.5 or max(bb[0], bb[1]) > SLAB_MAX_M:
                continue  # dz>1.5m no es losa plana (geometría rota)
            area = bb[0] * bb[1]  # huella por bounding box
        if area <= 0:
            continue
        if pt == "ROOF":
            out.append({"type": "roof", "area_m2": area})
            raw["roof"] += 1
        elif not has_space:  # sin IfcSpace, la losa de piso aproxima el ambiente
            cont = UE.get_container(sl)
            storey = (getattr(cont, "Name", "") or "").upper()
            if any(k in storey for k in _AUX_STOREY_KW):
                continue  # losa de nivel auxiliar (techo/tanque/estructura), no piso habitable
            out.append({"type": "room", "area_m2": area, "length_m": 4 * area ** 0.5, "height_m": DEFAULT_HEIGHT_M})
            raw["room(from_slab)"] += 1

    # --- Ambientes reales (si el export trae IfcSpace) ---
    for sp in f.by_type("IfcSpace"):
        area = qty(sp, "NetFloorArea", "GrossFloorArea")
        if area is None:
            bb = bbox(sp)
            area = bb[0] * bb[1] if bb else None
        else:
            area = area * scale * scale
        if area and area > 0:
            out.append({"type": "room", "area_m2": area, "length_m": 4 * area ** 0.5, "height_m": DEFAULT_HEIGHT_M})
            raw["room"] += 1

    # --- Columnas (sección < 2m) y vigas (sección < 1.5m) ---
    for c in f.by_type("IfcColumn"):
        bb = bbox(c)
        if not bb or max(bb[0], bb[1]) > 2.0:
            continue
        out.append({"type": "column", "area_m2": max(bb[0] * bb[1], 0.01), "height_m": bb[2]})
        raw["column"] += 1
    for b in f.by_type("IfcBeam"):
        length = qty(b, "Length")
        if length is not None:
            length = length * scale
        else:
            bb = bbox(b)
            if not bb or min(bb[0], bb[1]) > 1.5:
                continue
            length = max(bb[0], bb[1])
        if 0 < length <= 30:
            out.append({"type": "beam", "length_m": length})
            raw["beam"] += 1

    meta = {"schema": f.schema, "scale": scale, "raw": dict(raw), "n_elements": len(out)}
    return out, meta


def build_ifc_plan(project_id: int, contents: bytes, filename: str, db) -> "object":
    """Guarda el .ifc y crea el Plan (sin páginas, status 'processing'). El parseo
    a elementos lo hace `process_ifc` en background (puede tardar en modelos grandes)."""
    import uuid
    from pathlib import Path

    from app.core.config import settings
    from app.models.plan import Plan

    plan_storage = Path(settings.STORAGE_DIR) / "plans" / str(project_id)
    plan_storage.mkdir(parents=True, exist_ok=True)
    ifc_path = plan_storage / f"{uuid.uuid4().hex}.ifc"
    ifc_path.write_bytes(contents)

    plan = Plan(
        project_id=project_id,
        original_filename=filename,
        pdf_path=str(ifc_path),  # no hay PDF: guardamos la ruta del .ifc acá
        dpi=0,
        page_count=1,
        status="processing",
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def process_ifc(plan_id: int) -> None:
    """Background: parsea el IFC del plan y crea los DetectedElement exactos."""
    from app.core.database import SessionLocal
    from app.models.detected_element import DetectedElement
    from app.models.plan import Plan

    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        if plan is None:
            return
        try:
            elements, _meta = parse_ifc(plan.pdf_path)
            for e in elements:
                geom = {"source": "ifc"}
                if e.get("subtype"):
                    geom["subtype"] = e["subtype"]
                db.add(DetectedElement(
                    plan_id=plan_id, page=1, type=e["type"], geometry=geom,
                    length_m=e.get("length_m"), area_m2=e.get("area_m2"),
                    height_m=e.get("height_m"), source="ifc",
                    is_candidate=False, confidence=1.0,
                ))
            plan.status = "ready"
            db.commit()
        except Exception:
            plan.status = "error"
            db.commit()
            raise


if __name__ == "__main__":
    import sys
    els, meta = parse_ifc(sys.argv[1] if len(sys.argv) > 1 else "/tmp/duplex.ifc")
    print("meta:", meta)
    agg = Counter()
    qty_by = Counter()
    for e in els:
        agg[e["type"]] += 1
        if e["type"] == "wall":
            qty_by["muro_m2"] += e["length_m"] * e["height_m"]
            qty_by["muro_ml"] += e["length_m"]
        elif e["type"] in ("room", "roof"):
            qty_by[e["type"] + "_m2"] += e.get("area_m2", 0)
        elif e["type"] == "beam":
            qty_by["viga_ml"] += e["length_m"]
        elif e["type"] == "opening":
            qty_by[e["subtype"] + "_m2"] += e["length_m"] * e["height_m"]
    print("\nelementos por tipo:", dict(agg))
    print("cantidades:", {k: round(v, 1) for k, v in qty_by.items()})
