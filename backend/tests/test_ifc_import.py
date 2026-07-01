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


def _build_ifc(tmp: Path, with_spaces: bool) -> Path:
    """IFC4 sintético con medidas conocidas (unidades SI = metros)."""
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

    def _qto(product, name, props):
        qto = run("pset.add_qto", f, product=product, name=name)
        run("pset.edit_qto", f, qto=qto, properties=props)

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

    # Conteo real de entidades del archivo (para el retry por yield).
    assert meta["entities"] == {"wall": 2, "beam": 1, "column": 1, "slab": 3}


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
