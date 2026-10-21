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
import re
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

# Fundaciones CAMUFLADAS: los modeladores suelen dibujar pilotes como columnas
# ("SOE-Columns" = Support of Excavation) y zapatas corridas como vigas de H°
# ("Hormigón-Viga rectangular:ZAPATA"). Sin esto se computan como estructura
# común (rubro equivocado) y el % paramétrico de fundaciones las re-estima.
_FOUNDATION_KW = ("SOE-", "SOE ", "PILOT", "ZAPATA", "FOOTING", "FUNDAC", "CIMIENT", "CIMENT")


def _is_foundation(el) -> bool:
    return any(k in _norm(getattr(el, "Name", "") or "") for k in _FOUNDATION_KW)


# --- Sección de vigas, viguetas y losas -------------------------------------
# El export real (Revit IFC2X3) no trae base quantities: la sección de la viga
# sale del PERFIL del sólido extruido (IfcRectangleProfileDef XDim/YDim) y, si
# el cuerpo es un Brep, del nombre del tipo ("V1 (18 x 25)" → 18×25 cm).
_SECTION_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*x\s*(\d+(?:[.,]\d+)?)", re.IGNORECASE)
_THICKNESS_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*cm\b", re.IGNORECASE)
# Lado de sección razonable para una viga (m). Fuera de esto, el dato es basura.
_SIDE_MIN_M, _SIDE_MAX_M = 0.05, 1.50
# Espesor razonable de una losa (m).
_THICK_MIN_M, _THICK_MAX_M = 0.03, 1.00
# Viguetas pretensadas (se compran hechas, no se hormigonan): "Viga tipo T",
# "tipo T doble", "vigueta", "pretensada". Sobre texto normalizado (_norm).
_VIGUETA_RE = re.compile(r"\bTIPO T\b|\bT DOBLE\b|VIGUETA|PRETENSAD")
# Losas estructurales: "losa" como palabra (no "baldosa"), descartando pisos,
# contrapisos, veredas, etc., que son FLOOR pero no hormigón estructural.
# "\bPISO" excluye "piso cerámico" pero NO "losa de entrepiso".
_LOSA_RE = re.compile(r"\bLOSA")
_NOT_LOSA_RE = re.compile(r"VEREDA|BANQUINA|\bPISO|CONTRAPISO|TERRENO|ASADOR|DESCANS|LANDING")


def _names(el) -> list[str]:
    """Textos que describen al elemento: nombre del tipo, ObjectType y Name."""
    import ifcopenshell.util.element as UE

    out: list[str] = []
    try:
        t = UE.get_type(el)
    except Exception:  # noqa: BLE001
        t = None
    for s in (getattr(t, "Name", None), getattr(el, "ObjectType", None), getattr(el, "Name", None)):
        if s and s not in out:
            out.append(s)
    return out


def _type_label(el) -> Optional[str]:
    """Nombre del tipo (o, si no hay tipo, el ObjectType/Name)."""
    names = _names(el)
    return names[0] if names else None


def _is_vigueta(el) -> bool:
    return any(_VIGUETA_RE.search(_norm(s)) for s in _names(el))


def _is_structural_slab(el) -> bool:
    text = _norm(" ".join(_names(el)))
    return bool(_LOSA_RE.search(text)) and not _NOT_LOSA_RE.search(text)


def _round_or_none(x: Optional[float], nd: int) -> Optional[float]:
    return round(float(x), nd) if x is not None else None


def _to_float(s: str) -> float:
    return float(s.replace(",", "."))


def _section_from_name(el) -> Optional[tuple[float, float]]:
    """(ancho, alto) en m desde el nombre "NN x MM" (en cm). None si no hay o es absurdo."""
    for s in _names(el):
        for a, b in _SECTION_RE.findall(s):
            w, d = _to_float(a) / 100.0, _to_float(b) / 100.0
            if _SIDE_MIN_M <= w <= _SIDE_MAX_M and _SIDE_MIN_M <= d <= _SIDE_MAX_M:
                return w, d
    return None


def _thickness_from_name(el) -> Optional[float]:
    for s in _names(el):
        for a in _THICKNESS_RE.findall(s):
            t = _to_float(a) / 100.0
            if _THICK_MIN_M <= t <= _THICK_MAX_M:
                return t
    return None


def _extrusions(el) -> list:
    """IfcExtrudedAreaSolid del cuerpo del elemento.

    Sigue mapped items (tipo con RepresentationMaps) y booleanos de recorte
    (FirstOperand). Si el elemento no tiene representación propia, mira las
    del tipo. Nunca lanza."""
    import ifcopenshell.util.element as UE

    found: list = []

    def walk(it, depth=0):
        if it is None or depth > 6:
            return
        if it.is_a("IfcExtrudedAreaSolid"):
            found.append(it)
        elif it.is_a("IfcBooleanResult"):  # incluye IfcBooleanClippingResult
            walk(it.FirstOperand, depth + 1)
        elif it.is_a("IfcMappedItem"):
            for sub in it.MappingSource.MappedRepresentation.Items or []:
                walk(sub, depth + 1)

    def reps_of(rep_list):
        bodies = [r for r in rep_list if (r.RepresentationIdentifier or "") == "Body"]
        return bodies or [r for r in rep_list
                          if (r.RepresentationIdentifier or "") not in ("Axis", "Box", "FootPrint")]

    try:
        rep = getattr(el, "Representation", None)
        reps = reps_of(list(rep.Representations or [])) if rep is not None else []
        if not reps:
            t = UE.get_type(el)
            maps = (getattr(t, "RepresentationMaps", None) or []) if t is not None else []
            reps = reps_of([m.MappedRepresentation for m in maps])
        for r in reps:
            for it in r.Items or []:
                walk(it)
    except Exception:  # noqa: BLE001 — la geometría es un extra, nunca rompe el parse
        return []
    return found


def _rect_dims(profile) -> Optional[tuple[float, float]]:
    """(XDim, YDim) de un perfil rectangular MACIZO (el hueco no da volumen lleno)."""
    if profile is not None and profile.is_a() in ("IfcRectangleProfileDef", "IfcRoundedRectangleProfileDef"):
        return _num(profile.XDim), _num(profile.YDim)
    return None


def _beam_section_from_geometry(el, scale: float) -> Optional[tuple[float, float]]:
    """(ancho, alto) en m del primer perfil rectangular del cuerpo. Ancho = lado menor."""
    for ex in _extrusions(el):
        dims = _rect_dims(ex.SweptArea)
        if dims is None:
            continue
        a, b = sorted((dims[0] * scale, dims[1] * scale))
        if _SIDE_MIN_M <= a and b <= _SIDE_MAX_M:
            return a, b
    return None


def _polyline_area(curve) -> Optional[float]:
    """Área (unidades del modelo²) de una IfcPolyline cerrada, por shoelace."""
    if curve is None or not curve.is_a("IfcPolyline"):
        return None
    pts = [tuple(p.Coordinates[:2]) for p in curve.Points or []]
    if len(pts) < 3:
        return None
    s = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]))
    return abs(s) / 2.0


def _profile_area(profile) -> Optional[float]:
    """Área de un perfil (unidades del modelo²): rectángulo o polilínea, menos huecos."""
    if profile is None:
        return None
    dims = _rect_dims(profile)
    if dims is not None:
        return dims[0] * dims[1]
    if profile.is_a("IfcArbitraryClosedProfileDef"):
        area = _polyline_area(profile.OuterCurve)
        if area is None:
            return None
        for inner in getattr(profile, "InnerCurves", None) or []:  # ...WithVoids
            hole = _polyline_area(inner)
            if hole is None:
                return None
            area -= hole
        return area if area > 0 else None
    return None


def _slab_from_geometry(el, scale: float) -> tuple[Optional[float], Optional[float]]:
    """(área m², espesor m) de una losa por su extrusión. None donde no se pueda.

    El área es la del PERFIL (exacta para losas en L o con huecos dibujados en
    el contorno), no la del bounding box."""
    exts = _extrusions(el)
    if not exts:
        return None, None
    areas = [_profile_area(ex.SweptArea) for ex in exts]
    area = sum(areas) * scale * scale if all(a is not None for a in areas) else None
    thick = _num(exts[0].Depth) * scale
    if not (_THICK_MIN_M <= thick <= _THICK_MAX_M):
        thick = None
    return area, thick


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


def assess_ifc_quality(path: str) -> dict:
    """Semáforo de calidad del IFC sin parsear geometría (rápido, al upload).

    green  = schema ok + spaces + base quantities en muestra de muros
    yellow = usable pero falta spaces y/o QTO (área estimada / bbox)
    red    = no se pudo abrir o sin entidades estructurales útiles
    """
    checks: list[dict] = []
    warnings: list[str] = []
    try:
        import ifcopenshell
        import ifcopenshell.util.element as UE

        f = ifcopenshell.open(path)
    except Exception as exc:  # noqa: BLE001
        return {
            "level": "red",
            "schema": None,
            "has_spaces": False,
            "has_base_quantities": False,
            "n_storeys": 0,
            "n_walls": 0,
            "warnings": [f"No se pudo abrir el archivo: {exc}"],
            "checks": [
                {"id": "open", "ok": False, "label": "Archivo IFC legible"},
            ],
        }

    schema = str(getattr(f, "schema", "") or "")
    schema_ok = schema.upper().startswith("IFC")
    checks.append({
        "id": "schema",
        "ok": schema_ok,
        "label": f"Esquema {schema or 'desconocido'}",
    })
    if not schema_ok:
        warnings.append("El archivo no declara un esquema IFC reconocido.")

    n_spaces = len(f.by_type("IfcSpace"))
    has_spaces = n_spaces > 0
    checks.append({
        "id": "spaces",
        "ok": has_spaces,
        "label": f"Ambientes / rooms ({n_spaces})" if has_spaces else "Sin ambientes (IfcSpace)",
    })
    if not has_spaces:
        warnings.append("Sin IfcSpace: el área cubierta será una estimación (huella × pisos).")

    walls = f.by_type("IfcWall")
    n_walls = len(walls)
    qto_hits = 0
    sample = walls[: min(20, n_walls)]
    for wl in sample:
        psets = UE.get_psets(wl, qtos_only=True)
        for pset in psets.values():
            if any(k in pset for k in ("Length", "Height", "NetHeight", "GrossSideArea")):
                qto_hits += 1
                break
    has_qto = qto_hits >= max(1, len(sample) // 2) if sample else False
    checks.append({
        "id": "qto",
        "ok": has_qto,
        "label": "Base quantities" if has_qto else "Sin base quantities (usa geometría)",
    })
    if not has_qto:
        warnings.append(
            "Exportá con “base quantities” activadas para medidas más exactas."
        )

    n_storeys = len(f.by_type("IfcBuildingStorey"))
    storeys_ok = n_storeys > 0
    checks.append({
        "id": "storeys",
        "ok": storeys_ok,
        "label": f"{n_storeys} nivel{'es' if n_storeys != 1 else ''}" if storeys_ok else "Sin niveles",
    })
    if not storeys_ok:
        warnings.append("Sin IfcBuildingStorey: el cronograma no podrá secuenciar por piso.")

    structural = n_walls + len(f.by_type("IfcBeam")) + len(f.by_type("IfcColumn"))
    checks.append({
        "id": "structure",
        "ok": structural > 0,
        "label": f"{structural} elementos estructurales" if structural else "Sin muros/vigas/columnas",
    })
    if structural == 0:
        warnings.append("No se detectaron muros, vigas ni columnas en el modelo.")

    if structural == 0 or not schema_ok:
        level = "red"
    elif has_spaces and has_qto and storeys_ok:
        level = "green"
    else:
        level = "yellow"

    return {
        "level": level,
        "schema": schema or None,
        "has_spaces": has_spaces,
        "has_base_quantities": has_qto,
        "n_storeys": n_storeys,
        "n_walls": n_walls,
        "warnings": warnings,
        "checks": checks,
    }


def refine_ifc_quality(base: dict | None, meta: dict) -> dict:
    """Ajusta el semáforo con el resultado real del parseo."""
    q = dict(base or {})
    warnings = list(q.get("warnings") or [])
    checks = list(q.get("checks") or [])
    ent = meta.get("entities") or {}
    raw = meta.get("raw") or {}
    n_walls_file = ent.get("wall", 0)
    n_walls_out = raw.get("wall", 0)
    if n_walls_file and n_walls_out < n_walls_file * 0.5:
        warnings.append(
            f"Solo se midieron {n_walls_out} de {n_walls_file} muros "
            "(geometría incompleta o sin cantidades)."
        )
        checks = [c for c in checks if c.get("id") != "parse_yield"]
        checks.append({
            "id": "parse_yield",
            "ok": False,
            "label": f"Muros medidos {n_walls_out}/{n_walls_file}",
        })
        if q.get("level") == "green":
            q["level"] = "yellow"
        if n_walls_out == 0 and n_walls_file > 0:
            q["level"] = "red"
    if meta.get("area_estimada"):
        if not any("estimación" in w.lower() or "IfcSpace" in w for w in warnings):
            warnings.append("Área cubierta estimada (el modelo no trae IfcSpace).")
    q["warnings"] = warnings
    q["checks"] = checks
    q["n_elements"] = meta.get("n_elements")
    q["schema"] = meta.get("schema") or q.get("schema")
    return q


def _set_plan_progress(plan_id: int, progress: int, stage: str) -> None:
    """Actualiza progreso del parseo en una sesión corta (visible al FE vía poll)."""
    from app.core.database import SessionLocal
    from app.models.plan import Plan

    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        if plan is None:
            return
        plan.parse_progress = max(0, min(100, int(progress)))
        plan.parse_stage = stage[:64]
        db.commit()


def parse_ifc(path: str, on_progress=None) -> tuple[list[dict], dict]:
    """Devuelve (elementos, meta). Cada elemento: type + length_m/area_m2/height_m
    + subtype. meta: schema, contadores crudos.

    Extras por tipo: beam → width_m/depth_m/volume_m3 (None si no hay sección);
    vigueta → perfil; slab (losa estructural) → thickness_m (o None) y perfil.

    on_progress: callable opcional (pct: int, stage: str) → None.
    """
    def _prog(pct: int, stage: str) -> None:
        if on_progress is not None:
            try:
                on_progress(pct, stage)
            except Exception:  # noqa: BLE001
                pass

    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.util.element as UE
    import ifcopenshell.util.unit as UU

    _prog(8, "Abriendo modelo")
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
    _prog(15, "Leyendo geometría")
    try:
        import multiprocessing
        it = ifcopenshell.geom.iterator(settings, f, max(1, multiprocessing.cpu_count()))
        if it.initialize():
            n_shapes = 0
            while True:
                sh = it.get()
                bb = _verts_bbox(sh.geometry.verts)
                if bb is not None:
                    bbox_map[sh.id] = bb
                n_shapes += 1
                if n_shapes % 80 == 0:
                    # 15 → 55 aprox. mientras avanza el iterador
                    pct = min(55, 15 + (n_shapes // 80) * 2)
                    _prog(pct, "Leyendo geometría")
                if not it.next():
                    break
    except Exception:
        pass  # si el iterador no está disponible, bbox() cae a create_shape puntual

    _prog(60, "Extrayendo elementos")

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

    # --- Niveles (IfcBuildingStorey) ordenados por elevación ---
    # level_order 0 = el piso más bajo. Con esto el cronograma puede secuenciar
    # "Mampostería — PB" antes que "— Piso 1" (tareas por nivel).
    storeys = sorted(f.by_type("IfcBuildingStorey"),
                     key=lambda st: _num(getattr(st, "Elevation", 0.0)))
    storey_order = {st.id(): i for i, st in enumerate(storeys)}
    storey_name = {st.id(): (st.Name or f"Nivel {i + 1}")
                   for i, st in enumerate(storeys)}

    def _up(node):
        """Padre espacial: contención (RelContained) o agregación (Decomposes —
        los IfcSpace se AGREGAN al storey, no se contienen)."""
        nxt = UE.get_container(node)
        if nxt is not None:
            return nxt
        for rel in getattr(node, "Decomposes", None) or []:
            return rel.RelatingObject
        return None

    def _level_of(el):
        """(nombre, orden) del storey del elemento; (None, None) si no se puede
        resolver. Sube por el árbol espacial (un artefacto puede vivir en un
        IfcSpace, que a su vez decompone al storey)."""
        try:
            cont = _up(el)
            hops = 0
            while cont is not None and not cont.is_a("IfcBuildingStorey") and hops < 5:
                cont = _up(cont)
                hops += 1
        except Exception:  # noqa: BLE001
            return None, None
        if cont is None or not cont.is_a("IfcBuildingStorey"):
            return None, None
        return storey_name.get(cont.id()), storey_order.get(cont.id())

    def _with_mat(el, d: dict) -> dict:
        """Agrega material BIM (para auto-asignar receta) y nivel (storey) al
        dict del elemento."""
        mat = _material_name(el)
        if mat:
            d["material"] = mat
        lvl, lo = _level_of(el)
        if lvl is not None:
            d["level"], d["level_order"] = lvl, lo
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
        if pt == "FLOOR" and _is_structural_slab(sl):
            # Losa estructural (entrepiso/techo de H°A°) como elemento propio:
            # área por quantity o perfil de la extrusión (bbox como último
            # recurso) y espesor por la extrusión o el nombre ("12 cm").
            # Independiente de la estimación de área cubierta de más abajo.
            s_area = qty(sl, "NetArea", "GrossArea")
            s_area = s_area * scale * scale if s_area is not None else None
            g_area, thick = _slab_from_geometry(sl, scale)
            if s_area is None:
                s_area = g_area
            if s_area is None:
                bb = bbox(sl)
                if bb and bb[2] <= 1.5 and max(bb[0], bb[1]) <= SLAB_MAX_M:
                    s_area = bb[0] * bb[1]
            if thick is None:
                q_depth = qty(sl, "Depth", "Width")
                if q_depth is not None and _THICK_MIN_M <= q_depth * scale <= _THICK_MAX_M:
                    thick = q_depth * scale
                else:
                    thick = _thickness_from_name(sl)
            if s_area and math.isfinite(s_area) and 0 < s_area <= SLAB_MAX_M ** 2:
                out.append(_with_mat(sl, {"type": "slab", "area_m2": s_area,
                                          "thickness_m": thick, "perfil": _type_label(sl)}))
                raw["slab"] += 1
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
                out.append(_with_mat(sp, {"type": "room", "area_m2": area,
                                          "length_m": 4 * area ** 0.5,
                                          "height_m": DEFAULT_HEIGHT_M}))
                raw["room"] += 1
    elif floor_slab_areas:
        # --- Sin IfcSpace: ESTIMAMOS el área cubierta ---
        # Las losas de piso suelen venir fragmentadas y hasta duplicadas entre
        # niveles: sumarlas infla el área varias veces. En su lugar usamos
        # HUELLA (la losa más grande, ~footprint del edificio) × pisos habitables.
        # Es determinístico y no depende de la geometría flaky de losas rotas.
        # Cada piso estimado hereda el nombre del storey habitable que le toca.
        footprint = max(max(floor_slab_areas), roof_area)
        hab = [st for st in storeys
               if not any(k in (st.Name or "").upper() for k in _AUX_STOREY_KW)] or storeys
        for i in range(max(1, n_floors)):
            d = {"type": "room", "area_m2": footprint, "length_m": 4 * footprint ** 0.5,
                 "height_m": DEFAULT_HEIGHT_M, "subtype": "estimated_floor"}
            if i < len(hab):
                d["level"] = hab[i].Name or f"Nivel {i + 1}"
                d["level_order"] = storey_order.get(hab[i].id(), i)
            out.append(d)
            raw["room(estimated)"] += 1

    # --- Columnas (sección < 2m) y vigas (sección < 1.5m) ---
    # Los PILOTES modelados como columnas (SOE/PILOTE en el nombre) van al tipo
    # "pozo" (fundación, misma medida: sección); las ZAPATAS modeladas como
    # vigas van a "riostra" (viga de fundación, por ml). Así computan en el
    # rubro correcto y se descuentan del % paramétrico de fundaciones.
    for c in f.by_type("IfcColumn"):
        bb = bbox(c)
        if not bb or max(bb[0], bb[1]) > 2.0:
            continue
        el_type = "pozo" if _is_foundation(c) else "column"
        out.append(_with_mat(c, {"type": el_type, "area_m2": max(bb[0] * bb[1], 0.01), "height_m": bb[2]}))
        raw[el_type] += 1
    for b in f.by_type("IfcBeam"):
        length = qty(b, "Length")
        if length is not None:
            length = length * scale
        else:
            bb = bbox(b)
            if not bb or min(bb[0], bb[1]) > 1.5:
                continue
            length = max(bb[0], bb[1])
        if not 0 < length <= 30:
            continue
        if _is_foundation(b):
            out.append(_with_mat(b, {"type": "riostra", "length_m": length}))
            raw["riostra"] += 1
        elif _is_vigueta(b):
            # Vigueta pretensada: se compra hecha (por ml), no se hormigona.
            out.append(_with_mat(b, {"type": "vigueta", "length_m": length,
                                     "perfil": _type_label(b)}))
            raw["vigueta"] += 1
        else:
            # Viga de H°: sección del perfil extruido o, si no, del nombre.
            sec = _beam_section_from_geometry(b, scale) or _section_from_name(b)
            d = {"type": "beam", "length_m": length,
                 "width_m": None, "depth_m": None, "volume_m3": None}
            if sec is not None:
                d["width_m"], d["depth_m"] = sec
                d["volume_m3"] = sec[0] * sec[1] * length
            out.append(_with_mat(b, d))
            raw["beam"] += 1
    # Fundaciones EXPLÍCITAS (archivos bien exportados): zapatas y pilotes.
    for ft in list(f.by_type("IfcFooting")) + list(f.by_type("IfcPile")):
        area = qty(ft, "GrossArea", "NetArea")
        if area is not None:
            area = area * scale * scale
        else:
            bb = bbox(ft)
            area = bb[0] * bb[1] if bb else None
        if area and 0 < area <= 100:
            out.append(_with_mat(ft, {"type": "pozo", "area_m2": area}))
            raw["pozo"] += 1

    # --- Escaleras: contadas, sin medidas ---
    # En los "Assembled Stair" de Revit la geometría vive en los IfcMember del
    # conjunto y no es agregable en coordenadas locales (juntar bboxes locales
    # de members no da la escalera). Se cuenta el elemento sin inventar área.
    for st_el in f.by_type("IfcStair"):
        out.append(_with_mat(st_el, {"type": "escalera"}))
        raw["escalera"] += 1

    # --- Artefactos MEP: el modelo trae ARTEFACTOS aunque no las redes ---
    # (típico: inodoros/bachas/griferías y luminarias/tomas colocados, pero
    # 0 ml de cañería o cable). Se cuentan EXACTOS por nombre. No computan
    # costo (no hay receta por unidad todavía): informan el resumen y ayudan
    # a calibrar los rubros paramétricos de instalaciones.
    for ft in f.by_type("IfcFlowTerminal"):
        name = _norm(getattr(ft, "Name", "") or "")
        if any(k in name for k in _SANITARY_KW):
            out.append(_with_mat(ft, {"type": "sanitario"}))
            raw["sanitario"] += 1
        elif any(k in name for k in _ELEC_FIXTURE_KW):
            out.append(_with_mat(ft, {"type": "boca_electrica"}))
            raw["boca_electrica"] += 1
    # Tomas/llaves suelen venir como proxies genéricos: solo keywords inequívocas.
    for px in f.by_type("IfcBuildingElementProxy"):
        name = _norm(getattr(px, "Name", "") or "")
        if any(k in name for k in ("PLUG", "SOCKET", "OUTLET", "TOMACORRIENTE")):
            out.append(_with_mat(px, {"type": "boca_electrica"}))
            raw["boca_electrica"] += 1

    # --- Armaduras (IfcReinforcingBar): acero EXACTO por atributos ---
    # BarLength × CrossSectionArea × 7850 kg/m³ = kilos reales de hierro.
    # Sin atributos, la barra se cuenta igual (sin kg, no se inventa).
    for rb in f.by_type("IfcReinforcingBar"):
        L = _num(getattr(rb, "BarLength", None)) * scale
        A = _num(getattr(rb, "CrossSectionArea", None)) * scale * scale
        d = {"type": "armadura"}
        if 0 < L <= 100:
            d["length_m"] = L
            if A > 0:
                d["kg"] = L * A * 7850.0
        out.append(_with_mat(rb, d))
        raw["armadura"] += 1

    # --- Equipos de climatización (calderas/calefactores): contados ---
    for dev in f.by_type("IfcEnergyConversionDevice"):
        out.append(_with_mat(dev, {"type": "equipo_hvac"}))
        raw["equipo_hvac"] += 1

    # --- Cielorrasos (IfcCovering CEILING): contados, con área si la traen ---
    for cv in f.by_type("IfcCovering"):
        if str(getattr(cv, "PredefinedType", "")) != "CEILING":
            continue
        area = qty(cv, "GrossArea", "NetArea", "GrossCeilingArea")
        d = {"type": "cielorraso"}
        if area is not None and 0 < area * scale * scale <= SLAB_MAX_M ** 2:
            d["area_m2"] = area * scale * scale
        out.append(_with_mat(cv, d))
        raw["cielorraso"] += 1

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
    _prog(85, "Elementos extraídos")
    return out, meta


def parse_ifc_robust(path: str, attempts: int = 3, on_progress=None) -> tuple[list[dict], dict]:
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
        # Tipos que dependen de geometría sólida. Un IfcBeam puede salir como
        # beam, vigueta o riostra: se comparan contra el total de IfcBeam.
        out_by_ent = {
            "wall": raw.get("wall", 0),
            "beam": raw.get("beam", 0) + raw.get("vigueta", 0) + raw.get("riostra", 0),
        }
        for k, got in out_by_ent.items():
            n = ent.get(k, 0)
            if n:
                ratios.append(got / n)
        return min(ratios) if ratios else 1.0

    for attempt in range(max(1, attempts)):
        if on_progress and attempt > 0:
            try:
                on_progress(20, f"Reintentando geometría ({attempt + 1})")
            except Exception:  # noqa: BLE001
                pass
        out, meta = parse_ifc(path, on_progress=on_progress if attempt == 0 else None)
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


def build_ifc_plan(project_id: int, contents: "bytes | Path", filename: str, db) -> "object":
    """Guarda el .ifc y crea el Plan (sin páginas, status 'processing'). El parseo
    a elementos lo hace `process_ifc` en background (puede tardar en modelos grandes).

    `contents` puede ser el archivo ya volcado a disco (upload por bloques): se
    mueve al storage sin pasar por memoria."""
    import uuid
    from pathlib import Path

    from app.core.config import settings
    from app.models.plan import Plan

    plan_storage = Path(settings.STORAGE_DIR) / "plans" / str(project_id)
    plan_storage.mkdir(parents=True, exist_ok=True)
    ifc_path = plan_storage / f"{uuid.uuid4().hex}.ifc"
    if isinstance(contents, Path):
        contents.replace(ifc_path)
    else:
        ifc_path.write_bytes(contents)

    quality = assess_ifc_quality(str(ifc_path))

    plan = Plan(
        project_id=project_id,
        original_filename=filename,
        pdf_path=str(ifc_path),  # no hay PDF: guardamos la ruta del .ifc acá
        dpi=0,
        page_count=1,
        status="processing",
        parse_progress=0,
        parse_stage="En cola",
        ifc_quality=quality,
        error_message=None,
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

    def on_progress(pct: int, stage: str) -> None:
        _set_plan_progress(plan_id, pct, stage)

    with SessionLocal() as db:
        plan = db.get(Plan, plan_id)
        if plan is None:
            return
        try:
            _set_plan_progress(plan_id, 5, "Iniciando")
            elements, meta = parse_ifc_robust(plan.pdf_path, on_progress=on_progress)
            project = db.get(Project, plan.project_id)

            # Recetas de la org por tipo, para el matching por material.
            recipes_by_type: dict[str, list[tuple[int, str]]] = {}
            assemblies_by_id: dict[int, Assembly] = {}
            if project is not None:
                for a in db.query(Assembly).filter(
                        Assembly.organization_id == project.organization_id).all():
                    recipes_by_type.setdefault(a.applies_to, []).append((a.id, a.name))
                    assemblies_by_id[a.id] = a

            _set_plan_progress(plan_id, 90, "Guardando cómputo")
            # Re-fetch: el progreso abrió otras sesiones y este plan puede estar stale.
            plan = db.get(Plan, plan_id)
            if plan is None:
                return

            # Reproceso sin duplicar: se borran los elementos previos del plan en
            # la MISMA transacción que la inserción (si algo falla, rollback y
            # quedan los anteriores). element_assemblies cae por ON DELETE CASCADE.
            n_prev = (db.query(DetectedElement)
                      .filter(DetectedElement.plan_id == plan_id)
                      .delete(synchronize_session=False))
            if n_prev:
                logger.info("process_ifc plan=%s: %s elementos previos reemplazados", plan_id, n_prev)

            matched = Counter()
            for e in elements:
                geom = {"source": "ifc"}
                if e.get("subtype"):
                    geom["subtype"] = e["subtype"]
                if e.get("material"):
                    geom["material"] = e["material"]  # visible en el visor/debug
                if e.get("kg"):
                    geom["kg"] = round(e["kg"], 2)  # acero exacto (armaduras)
                if e.get("perfil"):
                    geom["perfil"] = e["perfil"]  # nombre del tipo (vigueta/losa)
                # Contrato con el presupuesto: las claves van SIEMPRE (null si no hay dato).
                if e["type"] == "beam":
                    for k in ("width_m", "depth_m", "volume_m3"):
                        geom[k] = _round_or_none(e.get(k), 4)
                elif e["type"] == "slab":
                    geom["thickness_m"] = _round_or_none(e.get("thickness_m"), 4)
                de = DetectedElement(
                    plan_id=plan_id, page=1, type=e["type"], geometry=geom,
                    length_m=e.get("length_m"), area_m2=e.get("area_m2"),
                    height_m=e.get("height_m"), source="ifc",
                    is_candidate=False, confidence=1.0,
                    level=e.get("level"), level_order=e.get("level_order"),
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
            plan.error_message = None
            plan.parse_progress = 100
            plan.parse_stage = "Listo"
            plan.ifc_quality = refine_ifc_quality(plan.ifc_quality, meta)
            # Autocompleta el Paso 5 desde el modelo (si el proyecto no lo tiene aún).
            if project is not None and not project.building_info:
                _autofill_building(project, meta)
            db.commit()
        except Exception as exc:
            logger.exception("process_ifc falló plan_id=%s", plan_id)
            db.rollback()
            plan = db.get(Plan, plan_id)
            if plan is not None:
                plan.status = "error"
                plan.error_message = str(exc)[:500]
                plan.parse_stage = "Error"
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
            qty_by["viga_m3"] += e.get("volume_m3") or 0
        elif e["type"] == "vigueta":
            qty_by["vigueta_ml"] += e["length_m"]
        elif e["type"] == "slab":
            qty_by["losa_m2"] += e["area_m2"]
        elif e["type"] == "opening":
            qty_by[e["subtype"] + "_m2"] += e["length_m"] * e["height_m"]
    print("\nelementos por tipo:", dict(agg))
    print("cantidades:", {k: round(v, 1) for k, v in qty_by.items()})
