"""Test del parser IFC (ifc_import.parse_ifc).

Verifica las garantías del import BIM con un IFC sintético de medidas conocidas:
- Aberturas por atributo (OverallWidth/Height): exactas, sin geometría.
- Muros/vigas/losas por base quantities (Qto_*): exactos.
- Columna por geometría (extrusión 0.3×0.3×2.8): camino bbox/iterador.
- Muro roto (sin qty ni geometría): se descarta sin romper el parseo.
- Losa FLOOR en nivel auxiliar (TECHOS): excluida del área (_AUX_STOREY_KW).
- Sin IfcSpace → área ESTIMADA = huella (losa/techo mayor) × pisos habitables,
  con subtype="estimated_floor" y meta area_estimada=True.
- Con IfcSpace → área EXACTA por ambiente, banos contados por nombre,
  area_estimada=False. Un space con área absurda (>SLAB_MAX_M²) se descarta.
- _autofill_building: <3 pisos → casa; ≥3 → edificio.
- parse_ifc_robust devuelve lo mismo que parse_ifc en un archivo sano.
- Vigas: sección del perfil extruido (propio o del tipo), si no del nombre
  "NN x MM" (cm); volumen = ancho × alto × largo; sin sección → None.
- Viguetas pretensadas ("Viga tipo T", "T doble") → type "vigueta", no beam.
- Losas estructurales ("Floor:losa") → type "slab" con área (quantity o perfil)
  y espesor; veredas/contrapisos/pisos no generan slab.

Corre directo (python tests/test_ifc_import.py) en el contenedor backend
(necesita ifcopenshell). No toca la base de datos.
"""

import importlib.util
import sys
import tempfile
import types
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _load_ifc_import():
    spec = importlib.util.spec_from_file_location(
        "ifc_import_under_test", BACKEND_DIR / "app" / "services" / "ifc_import.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _new_ifc():
    """Archivo IFC4 vacío en METROS con proyecto, contexto Body y 3 niveles
    (Nivel 1, Nivel 2, TECHOS). Devuelve (f, body, st1, st2, staux)."""
    from ifcopenshell.api import run

    f = run("project.create_file", version="IFC4")
    project = run("root.create_entity", f, ifc_class="IfcProject", name="Test")
    # OJO: el default de unit.assign_unit es MILÍMETROS. Asignamos METROS
    # explícitos para que scale=1 y las medidas del fixture sean literales.
    metre = run("unit.add_si_unit", f, unit_type="LENGTHUNIT")
    run("unit.assign_unit", f, units=[metre])
    model = run("context.add_context", f, context_type="Model")
    body = run(
        "context.add_context", f, context_type="Model",
        context_identifier="Body", target_view="MODEL_VIEW", parent=model,
    )

    site = run("root.create_entity", f, ifc_class="IfcSite", name="Sitio")
    building = run("root.create_entity", f, ifc_class="IfcBuilding", name="Edificio")
    st1 = run("root.create_entity", f, ifc_class="IfcBuildingStorey", name="Nivel 1")
    st2 = run("root.create_entity", f, ifc_class="IfcBuildingStorey", name="Nivel 2")
    staux = run("root.create_entity", f, ifc_class="IfcBuildingStorey", name="TECHOS")
    run("aggregate.assign_object", f, products=[site], relating_object=project)
    run("aggregate.assign_object", f, products=[building], relating_object=site)
    run("aggregate.assign_object", f, products=[st1, st2, staux], relating_object=building)
    return f, body, st1, st2, staux


def _add_qto(f, product, name, props):
    from ifcopenshell.api import run

    qto = run("pset.add_qto", f, product=product, name=name)
    run("pset.edit_qto", f, qto=qto, properties=props)


def _build_ifc(tmp: Path, with_spaces: bool) -> Path:
    """IFC4 sintético con medidas conocidas (unidades SI = metros)."""
    from ifcopenshell.api import run

    f, body, st1, st2, staux = _new_ifc()

    def _qto(product, name, props):
        _add_qto(f, product, name, props)

    # Muro sano: 10 m × 2.8 m por base quantities, con MATERIAL asignado
    # (para el auto-matching de recetas: piedra ≠ ladrillo).
    wall = run("root.create_entity", f, ifc_class="IfcWall", name="Muro 10m")
    run("spatial.assign_container", f, products=[wall], relating_structure=st1)
    _qto(wall, "Qto_WallBaseQuantities", {"Length": 10.0, "Height": 2.8})
    piedra = run("material.add_material", f, name="Piedra San Luis")
    run("material.assign_material", f, products=[wall], material=piedra)
    # Muro ROTO: sin qty ni geometría → el parser debe descartarlo sin excepción.
    broken = run("root.create_entity", f, ifc_class="IfcWall", name="Muro roto")
    run("spatial.assign_container", f, products=[broken], relating_structure=st1)

    # Aberturas por atributo (exactas).
    door = run("root.create_entity", f, ifc_class="IfcDoor", name="P1")
    door.OverallWidth, door.OverallHeight = 0.9, 2.05
    window = run("root.create_entity", f, ifc_class="IfcWindow", name="V1")
    window.OverallWidth, window.OverallHeight = 1.6, 1.1

    # Viga 4 m por quantity.
    beam = run("root.create_entity", f, ifc_class="IfcBeam", name="Viga")
    run("spatial.assign_container", f, products=[beam], relating_structure=st1)
    _qto(beam, "Qto_BeamBaseQuantities", {"Length": 4.0})

    # Losas: FLOOR 50 m² (Nivel 1) + FLOOR 999 m² en TECHOS (auxiliar,
    # debe excluirse) + ROOF 55 m² (huella del edificio).
    slab = run("root.create_entity", f, ifc_class="IfcSlab",
               name="Losa N1", predefined_type="FLOOR")
    run("spatial.assign_container", f, products=[slab], relating_structure=st1)
    _qto(slab, "Qto_SlabBaseQuantities", {"GrossArea": 50.0})
    aux = run("root.create_entity", f, ifc_class="IfcSlab",
              name="Losa techo", predefined_type="FLOOR")
    run("spatial.assign_container", f, products=[aux], relating_structure=staux)
    _qto(aux, "Qto_SlabBaseQuantities", {"GrossArea": 999.0})
    roof = run("root.create_entity", f, ifc_class="IfcSlab",
               name="Cubierta", predefined_type="ROOF")
    run("spatial.assign_container", f, products=[roof], relating_structure=staux)
    _qto(roof, "Qto_SlabBaseQuantities", {"GrossArea": 55.0})

    # Columna 0.3×0.3×2.8 con GEOMETRÍA real (extrusión) → camino bbox/iterador.
    col = run("root.create_entity", f, ifc_class="IfcColumn", name="C1")
    run("spatial.assign_container", f, products=[col], relating_structure=st1)
    run("geometry.edit_object_placement", f, product=col)
    profile = f.createIfcRectangleProfileDef("AREA", None, None, 0.3, 0.3)
    rep = run("geometry.add_profile_representation", f, context=body,
              profile=profile, depth=2.8)
    run("geometry.assign_representation", f, product=col, representation=rep)

    # Fundaciones CAMUFLADAS (como en los Revit reales): pilote modelado como
    # columna "SOE-Columns..." y zapata como viga "...:ZAPATA". Deben ir a
    # pozo/riostra (rubro fundación), no a column/beam.
    pil = run("root.create_entity", f, ifc_class="IfcColumn", name="SOE-Columns-CRHConcrete")
    run("spatial.assign_container", f, products=[pil], relating_structure=st1)
    run("geometry.edit_object_placement", f, product=pil)
    pprof = f.createIfcRectangleProfileDef("AREA", None, None, 0.4, 0.4)
    prep = run("geometry.add_profile_representation", f, context=body,
               profile=pprof, depth=8.0)
    run("geometry.assign_representation", f, product=pil, representation=prep)
    zap = run("root.create_entity", f, ifc_class="IfcBeam", name="Hormigón-Viga rectangular:ZAPATA")
    run("spatial.assign_container", f, products=[zap], relating_structure=st1)
    _qto(zap, "Qto_BeamBaseQuantities", {"Length": 6.5})

    # Armadura con atributos (kg exactos: L × A × 7850) y una sin atributos
    # (se cuenta, sin inventar kg).
    rb = run("root.create_entity", f, ifc_class="IfcReinforcingBar", name="Rebar Bar")
    rb.BarLength, rb.CrossSectionArea, rb.NominalDiameter = 2.0, 0.0001, 0.011
    run("spatial.assign_container", f, products=[rb], relating_structure=st1)
    rb2 = run("root.create_entity", f, ifc_class="IfcReinforcingBar", name="Rebar sin datos")
    run("spatial.assign_container", f, products=[rb2], relating_structure=st1)

    # Equipo HVAC + cielorraso con área.
    boiler = run("root.create_entity", f, ifc_class="IfcEnergyConversionDevice", name="Caldera")
    run("spatial.assign_container", f, products=[boiler], relating_structure=st1)
    ceil = run("root.create_entity", f, ifc_class="IfcCovering",
               name="cieloraso revoque", predefined_type="CEILING")
    run("spatial.assign_container", f, products=[ceil], relating_structure=st1)
    _qto(ceil, "Qto_CoveringBaseQuantities", {"GrossArea": 22.5})

    # Artefactos MEP y escalera: el modelo trae los ARTEFACTOS aunque no las
    # redes. Sanitario + luminaria (FlowTerminal, clasificados por nombre),
    # toma (proxy genérico con keyword PLUG) y una escalera armada.
    for nm in ("Sanitary_Toilets_DURAVIT Starck-3", "SASSO 60 round direct-indirect"):
        ft = run("root.create_entity", f, ifc_class="IfcFlowTerminal", name=nm)
        run("spatial.assign_container", f, products=[ft], relating_structure=st1)
    px = run("root.create_entity", f, ifc_class="IfcBuildingElementProxy",
             name="JARTON_USAWallPlugSmartHome")
    run("spatial.assign_container", f, products=[px], relating_structure=st1)
    stair = run("root.create_entity", f, ifc_class="IfcStair", name="Assembled Stair")
    run("spatial.assign_container", f, products=[stair], relating_structure=st1)

    if with_spaces:
        sp1 = run("root.create_entity", f, ifc_class="IfcSpace", name="Baño 1")
        run("aggregate.assign_object", f, products=[sp1], relating_object=st1)
        _qto(sp1, "Qto_SpaceBaseQuantities", {"NetFloorArea": 12.5})
        sp2 = run("root.create_entity", f, ifc_class="IfcSpace", name="Estar")
        run("aggregate.assign_object", f, products=[sp2], relating_object=st1)
        _qto(sp2, "Qto_SpaceBaseQuantities", {"NetFloorArea": 20.0})
        # Space con área absurda (geometría rota simulada): debe descartarse.
        sp3 = run("root.create_entity", f, ifc_class="IfcSpace", name="Roto")
        run("aggregate.assign_object", f, products=[sp3], relating_object=st2)
        _qto(sp3, "Qto_SpaceBaseQuantities", {"NetFloorArea": 1.0e9})

    out = tmp / ("con_spaces.ifc" if with_spaces else "sin_spaces.ifc")
    f.write(str(out))
    return out


def _build_ifc_estructura(tmp: Path) -> Path:
    """IFC con vigas, viguetas y losas como las del export real de Revit (sin
    base quantities de sección): perfil extruido, perfil vía tipo (mapped item),
    sección solo en el nombre, viguetas por nombre y por tipo, y losas
    estructurales vs. pisos/veredas."""
    from ifcopenshell.api import run

    f, body, st1, st2, staux = _new_ifc()

    def beam(name, length, profile=None, storey=st1):
        b = run("root.create_entity", f, ifc_class="IfcBeam", name=name)
        run("spatial.assign_container", f, products=[b], relating_structure=storey)
        _add_qto(f, b, "Qto_BeamBaseQuantities", {"Length": length})
        if profile is not None:
            run("geometry.edit_object_placement", f, product=b)
            rep = run("geometry.add_profile_representation", f, context=body,
                      profile=profile, depth=length)
            run("geometry.assign_representation", f, product=b, representation=rep)
        return b

    def slab(name, storey=st2, profile=None, depth=None, qto=None, pt="FLOOR"):
        s = run("root.create_entity", f, ifc_class="IfcSlab", name=name, predefined_type=pt)
        run("spatial.assign_container", f, products=[s], relating_structure=storey)
        if qto:
            _add_qto(f, s, "Qto_SlabBaseQuantities", qto)
        if profile is not None:
            run("geometry.edit_object_placement", f, product=s)
            rep = run("geometry.add_profile_representation", f, context=body,
                      profile=profile, depth=depth)
            run("geometry.assign_representation", f, product=s, representation=rep)
        return s

    # Viga con PERFIL rectangular 0.20×0.40, 5 m. El nombre dice otra sección
    # (15 x 20): manda la geometría.
    beam("Hormigón-Viga rectangular:V9 (15 x 20)", 5.0,
         profile=f.createIfcRectangleProfileDef("AREA", None, None, 0.4, 0.2))
    # Viga SIN geometría, sección solo en el nombre (Brep en el real).
    beam("Hormigón-Viga rectangular:V1 (18 x 25):820589", 4.0)
    # Viga sin sección reconocible + una con medidas absurdas en el nombre.
    beam("Hormigón-Viga rectangular:VL220", 2.0)
    beam("Viga rara 2 x 300", 2.0)
    # Viga cuya geometría vive en el TIPO (RepresentationMap → IfcMappedItem).
    vt = run("root.create_entity", f, ifc_class="IfcBeamType", name="Hormigón-Viga rectangular:VT")
    trep = run("geometry.add_profile_representation", f, context=body,
               profile=f.createIfcRectangleProfileDef("AREA", None, None, 0.15, 0.30), depth=3.0)
    run("geometry.assign_representation", f, product=vt, representation=trep)
    bt = beam("Viga tipada", 3.0)
    run("type.assign_type", f, related_objects=[bt], relating_type=vt)

    # Viguetas pretensadas: por nombre y por tipo ("T doble").
    beam("GPEVCO-EST-Viga tipo T:10 x 15:973136", 3.1)
    vd = run("root.create_entity", f, ifc_class="IfcBeamType", name="GPEVCO-EST-Viga tipo T doble:doble")
    bd = beam("Viga", 3.5)
    run("type.assign_type", f, related_objects=[bd], relating_type=vd)

    # Losas estructurales.
    slab("Floor:losa:1001", profile=f.createIfcRectangleProfileDef("AREA", None, None, 6.0, 5.0),
         depth=0.12)
    slab("Floor:losa 2 - 15 cm:1002", qto={"GrossArea": 40.0})
    pts = [f.createIfcCartesianPoint(p) for p in
           ((0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (2.0, 2.0), (2.0, 4.0), (0.0, 4.0), (0.0, 0.0))]
    slab("Floor:losa de entrepiso L:1003", storey=st1,
         profile=f.createIfcArbitraryClosedProfileDef("AREA", None, f.createIfcPolyline(pts)),
         depth=0.10)
    # No estructurales (FLOOR igual): no generan slab.
    slab("Floor:veredas:2001", storey=st1, qto={"GrossArea": 20.0})
    slab("Floor:contrapiso:2002", storey=st1, qto={"GrossArea": 30.0})
    slab("Floor:piso ceramico:2003", storey=st1, qto={"GrossArea": 30.0})
    slab("Floor:baldosa:2004", storey=st1, qto={"GrossArea": 30.0})
    # Techo: sigue siendo roof, no slab.
    slab("Basic Roof:Cubierta - por defecto - 30 cm 2", storey=staux, qto={"GrossArea": 55.0}, pt="ROOF")

    out = tmp / "estructura.ifc"
    f.write(str(out))
    return out


def _by_type(els):
    grouped: dict[str, list] = {}
    for e in els:
        grouped.setdefault(e["type"], []).append(e)
    return grouped


def test_parse_sin_spaces_area_estimada():
    ifc = _load_ifc_import()
    tmp = Path(tempfile.mkdtemp())
    els, meta = ifc.parse_ifc(str(_build_ifc(tmp, with_spaces=False)))
    g = _by_type(els)

    # Aberturas exactas por atributo.
    openings = sorted(g["opening"], key=lambda e: e["length_m"])
    assert len(openings) == 2
    assert abs(openings[0]["length_m"] - 0.9) < 1e-6 and openings[0]["subtype"] == "door"
    assert abs(openings[0]["height_m"] - 2.05) < 1e-6
    assert abs(openings[1]["length_m"] - 1.6) < 1e-6 and openings[1]["subtype"] == "window"

    # Muro sano por quantities; el roto se descarta sin romper.
    assert len(g["wall"]) == 1, f"muros: {g.get('wall')}"
    assert abs(g["wall"][0]["length_m"] - 10.0) < 1e-6
    assert abs(g["wall"][0]["height_m"] - 2.8) < 1e-6
    # El material BIM viaja en el dict (para el auto-matching de recetas).
    assert g["wall"][0].get("material") == "Piedra San Luis", \
        f"material del muro: {g['wall'][0].get('material')!r}"

    # Viga por quantity.
    assert len(g["beam"]) == 1 and abs(g["beam"][0]["length_m"] - 4.0) < 1e-6

    # Columna por geometría (0.3×0.3, alto 2.8).
    assert len(g["column"]) == 1, f"columnas: {g.get('column')}"
    assert abs(g["column"][0]["area_m2"] - 0.09) < 0.01
    assert abs(g["column"][0]["height_m"] - 2.8) < 0.05

    # Techo = huella mayor.
    assert len(g["roof"]) == 1 and abs(g["roof"][0]["area_m2"] - 55.0) < 1e-6

    # Artefactos MEP contados por nombre + escalera sin medidas inventadas.
    assert len(g.get("sanitario", [])) == 1, f"sanitarios: {g.get('sanitario')}"
    assert len(g.get("boca_electrica", [])) == 2, \
        f"bocas (luminaria FlowTerminal + toma proxy): {g.get('boca_electrica')}"
    assert len(g.get("escalera", [])) == 1
    assert "area_m2" not in g["escalera"][0], "la escalera no debe inventar área"

    # Fundaciones camufladas reclasificadas: el pilote SOE va a "pozo" (no
    # column) y la viga ZAPATA a "riostra" (no beam).
    assert len(g.get("pozo", [])) == 1, f"pilote SOE: {g.get('pozo')}"
    assert abs(g["pozo"][0]["area_m2"] - 0.16) < 0.02      # sección 0.4×0.4
    assert len(g.get("riostra", [])) == 1
    assert abs(g["riostra"][0]["length_m"] - 6.5) < 1e-6
    # La columna y viga comunes NO se contaminaron (siguen 1 y 1).
    assert len(g["column"]) == 1 and len(g["beam"]) == 1

    # Armaduras: kg exacto solo cuando hay atributos (2.0 × 0.0001 × 7850 = 1.57).
    arms = g.get("armadura", [])
    assert len(arms) == 2, f"armaduras: {arms}"
    with_kg = [a for a in arms if "kg" in a]
    assert len(with_kg) == 1 and abs(with_kg[0]["kg"] - 1.57) < 0.01

    # HVAC contado; cielorraso con área de quantity.
    assert len(g.get("equipo_hvac", [])) == 1
    assert len(g.get("cielorraso", [])) == 1
    assert abs(g["cielorraso"][0]["area_m2"] - 22.5) < 1e-6

    # Área ESTIMADA: huella max(losa 50, techo 55)=55 × 2 pisos habitables
    # (TECHOS excluido; si la losa de 999 m² entrara, la huella sería 999).
    rooms = g["room"]
    assert len(rooms) == 2
    assert all(r.get("subtype") == "estimated_floor" for r in rooms)
    assert all(abs(r["area_m2"] - 55.0) < 1e-6 for r in rooms), \
        f"la losa auxiliar contaminó la huella: {[r['area_m2'] for r in rooms]}"
    assert meta["area_estimada"] is True
    assert abs(meta["area_cubierta_m2"] - 110.0) < 0.1
    assert meta["pisos"] == 2 and meta["ambientes"] == 0 and meta["banos"] == 0

    # Conteo real de entidades del archivo (para el retry por yield). Incluye
    # las fundaciones camufladas (pilote = IfcColumn, zapata = IfcBeam crudos).
    assert meta["entities"] == {"wall": 2, "beam": 2, "column": 2, "slab": 3}


def test_parse_con_spaces_area_exacta():
    ifc = _load_ifc_import()
    tmp = Path(tempfile.mkdtemp())
    els, meta = ifc.parse_ifc(str(_build_ifc(tmp, with_spaces=True)))
    rooms = sorted(_by_type(els)["room"], key=lambda e: e["area_m2"])

    # 2 ambientes exactos; el de 1e9 m² (geometría rota) descartado.
    assert len(rooms) == 2, f"rooms: {[r['area_m2'] for r in rooms]}"
    assert abs(rooms[0]["area_m2"] - 12.5) < 1e-6
    assert abs(rooms[1]["area_m2"] - 20.0) < 1e-6
    assert all("subtype" not in r or r["subtype"] != "estimated_floor" for r in rooms)

    assert meta["area_estimada"] is False
    assert abs(meta["area_cubierta_m2"] - 32.5) < 0.1
    assert meta["ambientes"] == 3      # el archivo declara 3 IfcSpace
    assert meta["banos"] == 1          # "Baño 1"


def test_parse_ifc_robust_coincide():
    ifc = _load_ifc_import()
    tmp = Path(tempfile.mkdtemp())
    path = str(_build_ifc(tmp, with_spaces=True))
    els_a, meta_a = ifc.parse_ifc(path)
    els_b, meta_b = ifc.parse_ifc_robust(path, attempts=2)
    assert len(els_a) == len(els_b)
    assert meta_a["raw"] == meta_b["raw"]


def _parse_estructura():
    ifc = _load_ifc_import()
    tmp = Path(tempfile.mkdtemp())
    els, meta = ifc.parse_ifc(str(_build_ifc_estructura(tmp)))
    return _by_type(els), meta


def test_vigas_seccion_y_volumen():
    g, _ = _parse_estructura()
    beams = g.get("beam", [])
    assert len(beams) == 5, f"vigas: {beams}"
    # Las vigas no traen nombre en el dict: se identifican por largo (únicos
    # salvo las dos de 2 m, que se distinguen aparte).
    by_len = {}
    for b in beams:
        by_len.setdefault(round(b["length_m"], 2), []).append(b)

    # Perfil rectangular 0.40×0.20 → ancho 0.20 (lado menor), alto 0.40; manda
    # la geometría sobre el nombre "15 x 20". Volumen = 0.2 × 0.4 × 5 = 0.4.
    v = by_len[5.0][0]
    assert abs(v["width_m"] - 0.20) < 1e-6 and abs(v["depth_m"] - 0.40) < 1e-6, v
    assert abs(v["volume_m3"] - 0.40) < 1e-6, v

    # Sin perfil, sección del nombre "V1 (18 x 25)" → 0.18 × 0.25 × 4 = 0.18.
    v = by_len[4.0][0]
    assert abs(v["width_m"] - 0.18) < 1e-6 and abs(v["depth_m"] - 0.25) < 1e-6, v
    assert abs(v["volume_m3"] - 0.18) < 1e-6, v

    # Geometría en el TIPO (mapped item): 0.15 × 0.30 × 3 = 0.135.
    v = by_len[3.0][0]
    assert abs(v["width_m"] - 0.15) < 1e-6 and abs(v["depth_m"] - 0.30) < 1e-6, v
    assert abs(v["volume_m3"] - 0.135) < 1e-6, v

    # "VL220" y "2 x 300" (absurdo): sin sección, pero siguen contando su largo.
    sin = by_len[2.0]
    assert len(sin) == 2
    for b in sin:
        assert b["width_m"] is None and b["depth_m"] is None and b["volume_m3"] is None, b
        assert abs(b["length_m"] - 2.0) < 1e-6


def test_viguetas_no_son_vigas():
    g, meta = _parse_estructura()
    vig = sorted(g.get("vigueta", []), key=lambda e: e["length_m"])
    assert len(vig) == 2, f"viguetas: {vig}"
    # Por nombre ("Viga tipo T:10 x 15") y por tipo ("tipo T doble").
    assert abs(vig[0]["length_m"] - 3.1) < 1e-6
    assert "tipo T" in vig[0]["perfil"]
    assert abs(vig[1]["length_m"] - 3.5) < 1e-6
    assert vig[1]["perfil"] == "GPEVCO-EST-Viga tipo T doble:doble"
    assert "width_m" not in vig[0], "la vigueta no lleva sección de hormigón"
    # Ninguna vigueta se coló como beam (5 vigas de H° y nada más).
    assert len(g.get("beam", [])) == 5
    # El rendimiento del parseo cuenta viguetas como IfcBeam medidos (7/7).
    assert meta["entities"]["beam"] == 7
    assert meta["raw"]["beam"] + meta["raw"]["vigueta"] == 7


def test_losas_estructurales():
    g, meta = _parse_estructura()
    slabs = sorted(g.get("slab", []), key=lambda e: e["area_m2"])
    assert len(slabs) == 3, f"losas: {[(s.get('perfil'), s['area_m2']) for s in slabs]}"

    # Losa en L por PERFIL (polilínea): 12 m², no los 16 del bounding box;
    # "entrepiso" no se confunde con "piso".
    l_ = slabs[0]
    assert abs(l_["area_m2"] - 12.0) < 1e-6, l_
    assert abs(l_["thickness_m"] - 0.10) < 1e-6
    assert l_["level"] == "Nivel 1"

    # "Floor:losa" con perfil 6×5, extrusión 0.12 → 30 m², espesor 0.12.
    s = slabs[1]
    assert abs(s["area_m2"] - 30.0) < 1e-6, s
    assert abs(s["thickness_m"] - 0.12) < 1e-6
    assert s["level"] == "Nivel 2" and s["level_order"] is not None

    # Por quantity, sin geometría: área 40, espesor del nombre ("15 cm").
    s = slabs[2]
    assert abs(s["area_m2"] - 40.0) < 1e-6, s
    assert abs(s["thickness_m"] - 0.15) < 1e-6

    # Veredas/contrapiso/piso/baldosa no generan slab; el techo sigue en roof.
    assert all("VEREDA" not in (x.get("perfil") or "").upper() for x in slabs)
    assert len(g.get("roof", [])) == 1 and abs(g["roof"][0]["area_m2"] - 55.0) < 1e-6
    assert meta["raw"]["slab"] == 3


def test_losa_sin_espesor_queda_null():
    """Losa estructural sin extrusión ni "NN cm" en el nombre: thickness_m None."""
    from ifcopenshell.api import run

    ifc = _load_ifc_import()
    f, _body, st1, _st2, _staux = _new_ifc()
    s = run("root.create_entity", f, ifc_class="IfcSlab", name="Floor:losa tanque",
            predefined_type="FLOOR")
    run("spatial.assign_container", f, products=[s], relating_structure=st1)
    _add_qto(f, s, "Qto_SlabBaseQuantities", {"GrossArea": 9.0})
    tmp = Path(tempfile.mkdtemp()) / "losa.ifc"
    f.write(str(tmp))
    els, _ = ifc.parse_ifc(str(tmp))
    slabs = _by_type(els).get("slab", [])
    assert len(slabs) == 1 and abs(slabs[0]["area_m2"] - 9.0) < 1e-6
    assert "thickness_m" in slabs[0] and slabs[0]["thickness_m"] is None


def test_match_recipe_by_material():
    """Matching material BIM → receta: conservador, solo con match inequívoco."""
    ifc = _load_ifc_import()
    m = ifc.match_recipe_by_material

    # Recetas de muro típicas de la org (3 de ladrillo + 1 de piedra).
    walls = [
        (7, "Muro Ladrillo Hueco 18x18x33"),
        (16, "Muro Exterior 22cm (ladrillo 18 + revoque)"),
        (17, "Muro Interior 16cm (ladrillo 12 + revoque)"),
        (30, "Muro de Piedra vista 20cm"),
    ]
    # Piedra: UNA sola receta comparte familia → asigna (el caso de uso real).
    assert m("Piedra San Luis", walls) == 30
    assert m("Stone Basalt", walls) == 30           # sinónimo EN
    # Ladrillo: 3 recetas comparten familia → ambiguo → no asigna (default).
    assert m("Ladrillo hueco cerámico", walls) is None
    # Material sin familia conocida → no asigna.
    assert m("Fenólico 18mm", walls) is None
    # Acentos y mayúsculas normalizados; "H°A°" es notación de hormigón.
    assert m("HORMIGÓN ARMADO", [(6, "Columna H°A° 20x20"), (12, "Columna metálica")]) == 6
    assert m("Hormigón in situ", [(6, "Columna de hormigon armado"), (12, "Columna metálica")]) == 6
    # Sin recetas candidatas → None (org sin recetas de ese tipo).
    assert m("Piedra", []) is None


def test_autofill_building():
    ifc = _load_ifc_import()
    proj = types.SimpleNamespace(building_type=None, building_info=None)
    ifc._autofill_building(proj, {"pisos": 2, "area_cubierta_m2": 110.0,
                                  "ambientes": 4, "banos": 1})
    assert proj.building_type == "casa"
    assert proj.building_info["area_cubierta_m2"] == 110.0
    assert proj.building_info["habitaciones"] == 4 and proj.building_info["banos"] == 1

    proj2 = types.SimpleNamespace(building_type=None, building_info=None)
    ifc._autofill_building(proj2, {"pisos": 5, "area_cubierta_m2": 900.0,
                                   "ambientes": 0, "banos": 0})
    assert proj2.building_type == "edificio"
    assert proj2.building_info == {"area_total_m2": 900.0, "pisos": 5}


def test_assess_ifc_quality_semaphore():
    ifc = _load_ifc_import()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        # Sin spaces ni QTO → yellow (tiene muros/storeys, usable).
        q_no = ifc.assess_ifc_quality(str(_build_ifc(tmp, with_spaces=False)))
        assert q_no["level"] in ("yellow", "green", "red")
        assert q_no["has_spaces"] is False
        assert any(c["id"] == "spaces" and c["ok"] is False for c in q_no["checks"])
        assert q_no["n_storeys"] >= 1

        q_yes = ifc.assess_ifc_quality(str(_build_ifc(tmp, with_spaces=True)))
        assert q_yes["has_spaces"] is True
        assert any(c["id"] == "spaces" and c["ok"] is True for c in q_yes["checks"])

        refined = ifc.refine_ifc_quality(
            q_no,
            {"entities": {"wall": 10}, "raw": {"wall": 2}, "area_estimada": True, "n_elements": 5},
        )
        assert refined["level"] in ("yellow", "red")
        assert any("muros" in w.lower() for w in refined["warnings"])


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok    {name}")
            except AssertionError as exc:
                failed += 1
                print(f"  FAIL  {name}: {exc}")
    total = sum(1 for n, f in globals().items() if n.startswith("test_") and callable(f))
    print(f"\n{total - failed}/{total} tests pasaron")
    sys.exit(1 if failed else 0)
