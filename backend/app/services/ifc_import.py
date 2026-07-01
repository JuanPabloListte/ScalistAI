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

import logging
import math
from collections import Counter
from typing import Optional

logger = logging.getLogger(__name__)

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


def _habitable_storeys(f) -> int:
    """Cuenta los niveles habitables (excluye techo/tanque/estructura)."""
    storeys = f.by_type("IfcBuildingStorey")
    habitable = [st for st in storeys
                 if not any(k in (st.Name or "").upper() for k in _AUX_STOREY_KW)]
    return len(habitable) or len(storeys) or 1


def _material_name(el) -> Optional[str]:
    """Nombre del material del elemento según el modelo BIM.

    Los muros de Revit suelen venir como LayerSet (ladrillo + revoque + ...):
    se toma la CAPA MÁS GRUESA, que es el material estructural. Nunca lanza.
    """
    import ifcopenshell.util.element as UE

    try:
        m = UE.get_material(el)
        if m is None:
            return None
        t = m.is_a()
        if t == "IfcMaterial":
            return m.Name or None
        if t == "IfcMaterialLayerSetUsage":
            m = m.ForLayerSet
            t = m.is_a()
        if t == "IfcMaterialLayerSet":
            layers = [ly for ly in (m.MaterialLayers or []) if ly.Material]
            if not layers:
                return None
            thickest = max(layers, key=lambda ly: _num(ly.LayerThickness))
            return thickest.Material.Name or None
        if t == "IfcMaterialList":
            mats = m.Materials or []
            return mats[0].Name if mats else None
        if t == "IfcMaterialProfileSetUsage":  # vigas/columnas IFC4
            profiles = m.ForProfileSet.MaterialProfiles or []
            return profiles[0].Material.Name if profiles and profiles[0].Material else None
    except Exception:  # noqa: BLE001 — el material es un extra, nunca rompe el parse
        pass
    return None


# --- Matching material BIM → receta de la org -------------------------------
# Familias de material: sinónimos ES/EN normalizados (sin acentos, mayúsculas).
# El match es CONSERVADOR: se asigna receta solo si el material del IFC y
# exactamente UNA receta del tipo comparten familia. Con 0 o >1 candidatas
# queda el default por tipo (no adivinamos).
_MATERIAL_FAMILIES: list[tuple[str, ...]] = [
    ("LADRILLO", "BRICK", "MAMPOSTER"),
    ("BLOQUE", "BLOCK"),
    ("PIEDRA", "STONE"),
    ("HORMIGON", "CONCRETE", "H°A°", "HºAº"),
    ("MADERA", "WOOD", "TIMBER"),
    ("ACERO", "STEEL", "METALICA", "METALICO"),
    ("ALUMINIO", "ALUMINUM", "ALUMINIUM"),
    ("YESO", "GYPSUM", "DRYWALL", "DURLOCK"),
    ("VIDRIO", "GLASS", "GLAZING"),
]

_ACCENTS = str.maketrans("ÁÉÍÓÚÜÑ", "AEIOUUN")

# Artefactos MEP por nombre (los IfcFlowTerminal de Revit 2x3 no traen
# PredefinedType/ObjectType): sanitarios/cocina vs iluminación/tomas.
# "DIRECT-INDIRECT" es jerga de luminarias (ej. "SASSO 60 direct-indirect").
_SANITARY_KW = (
    "SANITARY", "TOILET", "BIDET", "SHOWER", "WASH", "BASIN", "SINK", "TAP",
    "MIXER", "DRAIN", "PLUMBING", "INODORO", "BACHA", "DUCHA", "GRIFER",
)
_ELEC_FIXTURE_KW = (
    "LIGHT", "LAMP", "LED", "LUMINA", "PLUG", "SOCKET", "OUTLET", "SWITCH",
    "SPOT", "DIRECT-INDIRECT",
)


def _norm(s: str) -> str:
    return (s or "").upper().translate(_ACCENTS)


def _families_of(name: str) -> set[int]:
    up = _norm(name)
    return {i for i, fam in enumerate(_MATERIAL_FAMILIES) if any(k in up for k in fam)}


def match_recipe_by_material(material: str, recipes: list[tuple[int, str]]) -> Optional[int]:
    """Elige la receta cuyo nombre comparte familia de material con el IFC.

    `recipes`: [(id, nombre)] del MISMO applies_to y la MISMA org.
    Devuelve el id solo si exactamente UNA receta matchea (sin ambigüedad).
    """
    mat_fams = _families_of(material)
    if not mat_fams:
        return None
    hits = [rid for rid, rname in recipes if _families_of(rname) & mat_fams]
    return hits[0] if len(hits) == 1 else None


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

    def _verts_bbox(v) -> Optional[tuple[float, float, float]]:
        if not v:
            return None
        xs, ys, zs = v[0::3], v[1::3], v[2::3]
        return ((max(xs) - min(xs)) * scale, (max(ys) - min(ys)) * scale, (max(zs) - min(zs)) * scale)

    # Geometría en LOTE con el iterador: `create_shape` uno-por-uno falla de forma
    # NO-determinística en archivos grandes (memoria/OpenCASCADE) → devolvía 8 de
    # 92 muros. El iterador procesa todo de una y es fiable. Guardamos solo el
    # bbox (dx,dy,dz) por id de entidad; los verts se descartan (memoria liviana).
    bbox_map: dict[int, tuple[float, float, float]] = {}
    try:
        import multiprocessing
        it = ifcopenshell.geom.iterator(settings, f, max(1, multiprocessing.cpu_count()))
        if it.initialize():
            while True:
                sh = it.get()
                bb = _verts_bbox(sh.geometry.verts)
                if bb is not None:
                    bbox_map[sh.id] = bb
                if not it.next():
                    break
    except Exception:
        pass  # si el iterador no está disponible, bbox() cae a create_shape puntual

    def bbox(el) -> Optional[tuple[float, float, float]]:
        bb = bbox_map.get(el.id())
        if bb is not None:
            return bb
        try:  # fallback puntual (elementos que el iterador no tesela)
            v = ifcopenshell.geom.create_shape(settings, el).geometry.verts
        except Exception:
            return None
        return _verts_bbox(v)

    out: list[dict] = []
    raw = Counter()

    def _with_mat(el, d: dict) -> dict:
        """Agrega el material BIM al dict del elemento (si el modelo lo trae).
        Después se usa para auto-asignar la receta (ladrillo vs piedra...)."""
        mat = _material_name(el)
        if mat:
            d["material"] = mat
        return d

    # --- Aberturas: medida directa (exacta), sin geometría ---
    for d in f.by_type("IfcDoor"):
        w, h = _num(d.OverallWidth) * scale, _num(d.OverallHeight) * scale
        if w > 0 and h > 0:
            out.append(_with_mat(d, {"type": "opening", "length_m": w, "height_m": h, "subtype": "door"}))
            raw["door"] += 1
    for wd in f.by_type("IfcWindow"):
        w, h = _num(wd.OverallWidth) * scale, _num(wd.OverallHeight) * scale
        if w > 0 and h > 0:
            out.append(_with_mat(wd, {"type": "opening", "length_m": w, "height_m": h, "subtype": "window"}))
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
        out.append(_with_mat(wl, {"type": "wall", "length_m": length, "height_m": height}))
        raw["wall"] += 1

    # --- Losas: recolectamos huellas (no sumamos aún) ---
    # ROOF -> techo. FLOOR -> piso. Guardamos áreas individuales para estimar la
    # huella del edificio (losa más grande), robusta a losas fragmentadas.
    has_space = len(f.by_type("IfcSpace")) > 0
    n_floors = _habitable_storeys(f)
    floor_slab_areas: list[float] = []
    roof_area = 0.0
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
            roof_area = max(roof_area, area)  # huella de techo = la mayor
        else:
            cont = UE.get_container(sl)
            storey = (getattr(cont, "Name", "") or "").upper()
            if any(k in storey for k in _AUX_STOREY_KW):
                continue  # losa de nivel auxiliar (techo/tanque/estructura), no piso habitable
            floor_slab_areas.append(area)

    if roof_area > 0:
        out.append({"type": "roof", "area_m2": roof_area})
        raw["roof"] += 1

    if has_space:
        # --- Ambientes REALES (el export trae IfcSpace): área exacta ---
        # Sin base quantities el área sale de geometría (bbox), que a veces
        # devuelve basura (verts corruptos → área absurda). Se descarta si no es
        # física: un ambiente > SLAB_MAX_M² (ó no finito) es geometría rota.
        for sp in f.by_type("IfcSpace"):
            area = qty(sp, "NetFloorArea", "GrossFloorArea")
            if area is None:
                bb = bbox(sp)
                area = bb[0] * bb[1] if bb else None
            else:
                area = area * scale * scale
            if area and math.isfinite(area) and 0 < area <= SLAB_MAX_M ** 2:
                out.append({"type": "room", "area_m2": area, "length_m": 4 * area ** 0.5, "height_m": DEFAULT_HEIGHT_M})
                raw["room"] += 1
    elif floor_slab_areas:
        # --- Sin IfcSpace: ESTIMAMOS el área cubierta ---
        # Las losas de piso suelen venir fragmentadas y hasta duplicadas entre
        # niveles: sumarlas infla el área varias veces. En su lugar usamos
        # HUELLA (la losa más grande, ~footprint del edificio) × pisos habitables.
        # Es determinístico y no depende de la geometría flaky de losas rotas.
        footprint = max(max(floor_slab_areas), roof_area)
        for _ in range(max(1, n_floors)):
            out.append({"type": "room", "area_m2": footprint, "length_m": 4 * footprint ** 0.5,
                        "height_m": DEFAULT_HEIGHT_M, "subtype": "estimated_floor"})
            raw["room(estimated)"] += 1

    # --- Columnas (sección < 2m) y vigas (sección < 1.5m) ---
    for c in f.by_type("IfcColumn"):
        bb = bbox(c)
        if not bb or max(bb[0], bb[1]) > 2.0:
            continue
        out.append(_with_mat(c, {"type": "column", "area_m2": max(bb[0] * bb[1], 0.01), "height_m": bb[2]}))
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
            out.append(_with_mat(b, {"type": "beam", "length_m": length}))
            raw["beam"] += 1

    # --- Escaleras: contadas, sin medidas ---
    # En los "Assembled Stair" de Revit la geometría vive en los IfcMember del
    # conjunto y no es agregable en coordenadas locales (juntar bboxes locales
    # de members no da la escalera). Se cuenta el elemento sin inventar área.
    for st_el in f.by_type("IfcStair"):
        out.append({"type": "escalera"})
        raw["escalera"] += 1

    # --- Artefactos MEP: el modelo trae ARTEFACTOS aunque no las redes ---
    # (típico: inodoros/bachas/griferías y luminarias/tomas colocados, pero
    # 0 ml de cañería o cable). Se cuentan EXACTOS por nombre. No computan
    # costo (no hay receta por unidad todavía): informan el resumen y ayudan
    # a calibrar los rubros paramétricos de instalaciones.
    for ft in f.by_type("IfcFlowTerminal"):
        name = _norm(getattr(ft, "Name", "") or "")
        if any(k in name for k in _SANITARY_KW):
            out.append({"type": "sanitario"})
            raw["sanitario"] += 1
        elif any(k in name for k in _ELEC_FIXTURE_KW):
            out.append({"type": "boca_electrica"})
            raw["boca_electrica"] += 1
    # Tomas/llaves suelen venir como proxies genéricos: solo keywords inequívocas.
    for px in f.by_type("IfcBuildingElementProxy"):
        name = _norm(getattr(px, "Name", "") or "")
        if any(k in name for k in ("PLUG", "SOCKET", "OUTLET", "TOMACORRIENTE")):
            out.append({"type": "boca_electrica"})
            raw["boca_electrica"] += 1

    # --- Metadata del edificio (para autocompletar el Paso 5) ---
    spaces = f.by_type("IfcSpace")

    def _sp_name(sp) -> str:
        return ((sp.Name or "") + " " + (getattr(sp, "LongName", "") or "")).upper()

    banos = sum(1 for sp in spaces
                if any(k in _sp_name(sp) for k in ("BAÑO", "BANO", "BATH", "TOILET", "SANITARIO", "ASEO", "WC")))
    area_cubierta = sum(e.get("area_m2", 0) for e in out if e["type"] == "room")
    area_estimada = not has_space  # el área cubierta es estimación (huella×pisos), no exacta

    meta = {
        "schema": f.schema, "scale": scale, "raw": dict(raw), "n_elements": len(out),
        "pisos": n_floors,
        "area_estimada": area_estimada,
        "ambientes": len(spaces),
        "banos": banos,
        "area_cubierta_m2": round(area_cubierta, 1),
        # Cantidad REAL de entidades en el archivo (para verificar el rendimiento
        # del parseo: si sobrevivieron muchas menos, la geometría falló).
        "entities": {
            "wall": len(f.by_type("IfcWall")),
            "beam": len(f.by_type("IfcBeam")),
            "column": len(f.by_type("IfcColumn")),
            "slab": len(f.by_type("IfcSlab")),
        },
    }
    return out, meta


def parse_ifc_robust(path: str, attempts: int = 3) -> tuple[list[dict], dict]:
    """Igual que `parse_ifc`, pero tolerante a fallos transitorios del motor de
    geometría (que bajo presión de memoria puede fallar en silencio en muchos
    elementos de archivos grandes). Reintenta y se queda con la mejor corrida:
    la que más se acerca a la cantidad real de entidades del archivo.

    Corta apenas una corrida rinde bien (>=90% de muros y vigas), para no
    reparsear de gorra un archivo que ya salió completo.
    """
    best: Optional[tuple[list[dict], dict]] = None

    def _yield(meta: dict) -> float:
        ent, raw = meta.get("entities", {}), meta.get("raw", {})
        ratios = []
        for k in ("wall", "beam"):  # tipos que dependen de geometría solida
            n = ent.get(k, 0)
            if n:
                ratios.append(raw.get(k, 0) / n)
        return min(ratios) if ratios else 1.0

    for _ in range(max(1, attempts)):
        out, meta = parse_ifc(path)
        if best is None or _yield(meta) > _yield(best[1]):
            best = (out, meta)
        if _yield(meta) >= 0.9:
            break
    return best  # type: ignore[return-value]


def _autofill_building(project, meta: dict) -> None:
    """Precarga tipo + datos de construcción del proyecto desde el modelo BIM.
    Solo llena lo derivable; el resto lo completa el usuario en el Paso 5."""
    pisos = meta.get("pisos") or 1
    area = meta.get("area_cubierta_m2") or 0
    ambientes = meta.get("ambientes") or 0
    banos = meta.get("banos") or 0
    if pisos >= 3:
        project.building_type = "edificio"
        project.building_info = {"area_total_m2": area, "pisos": pisos}
    else:
        project.building_type = "casa"
        info = {"area_cubierta_m2": area, "pisos": pisos}
        if ambientes:
            info["habitaciones"] = ambientes
        if banos:
            info["banos"] = banos
        project.building_info = info


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
    """Background: parsea el IFC del plan y crea los DetectedElement exactos.

    Si el modelo trae materiales (IfcMaterial), auto-asigna la receta de la
    org que corresponda a cada elemento ("muro de piedra" → receta piedra) vía
    el mecanismo de receta-por-elemento (element_assemblies). Conservador: sin
    match inequívoco no asigna nada y queda el default por tipo.
    """
    from app.core.database import SessionLocal
    from app.models.detected_element import DetectedElement
    from app.models.material import Assembly
    from app.models.plan import Plan
    from app.models.project import Project

    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        if plan is None:
            return
        try:
            elements, meta = parse_ifc_robust(plan.pdf_path)
            project = db.get(Project, plan.project_id)

            # Recetas de la org por tipo, para el matching por material.
            recipes_by_type: dict[str, list[tuple[int, str]]] = {}
            assemblies_by_id: dict[int, Assembly] = {}
            if project is not None:
                for a in db.query(Assembly).filter(
                        Assembly.organization_id == project.organization_id).all():
                    recipes_by_type.setdefault(a.applies_to, []).append((a.id, a.name))
                    assemblies_by_id[a.id] = a

            matched = Counter()
            for e in elements:
                geom = {"source": "ifc"}
                if e.get("subtype"):
                    geom["subtype"] = e["subtype"]
                if e.get("material"):
                    geom["material"] = e["material"]  # visible en el visor/debug
                de = DetectedElement(
                    plan_id=plan_id, page=1, type=e["type"], geometry=geom,
                    length_m=e.get("length_m"), area_m2=e.get("area_m2"),
                    height_m=e.get("height_m"), source="ifc",
                    is_candidate=False, confidence=1.0,
                )
                # Material BIM → receta (solo tipos con receta directa; los
                # rooms usan recetas compuestas room_* y quedan al default).
                if e.get("material") and e["type"] in ("wall", "column", "beam", "roof", "opening"):
                    rid = match_recipe_by_material(
                        e["material"], recipes_by_type.get(e["type"], []))
                    if rid is not None:
                        de.assemblies.append(assemblies_by_id[rid])
                        matched[f"{e['type']}→{assemblies_by_id[rid].name}"] += 1
                db.add(de)
            if matched:
                logger.info("ifc materiales→recetas plan=%s: %s", plan_id, dict(matched))

            plan.status = "ready"
            # Autocompleta el Paso 5 desde el modelo (si el proyecto no lo tiene aún).
            if project is not None and not project.building_info:
                _autofill_building(project, meta)
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
