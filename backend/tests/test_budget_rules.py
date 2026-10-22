"""Presupuesto por reglas (services/budget_rules.py) + API de juegos de reglas.

Corre directo: python tests/test_budget_rules.py (dentro del contenedor).
Los tests de motor no usan DB; los de API crean una org de test y la borran.
"""
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _el(type, length=None, area=None, height=None, level=None, **geom):
    return NS(type=type, length_m=length, area_m2=area, height_m=height, geometry=geom,
              level=level)


def _line(row, desc, net, amount=1.0, unit="u", **attrs):
    return {"row": row, "code": None, "description": desc, "unit_price_net": net,
            "presentation": {"amount": amount, "unit": unit, "attrs": attrs}}


def _rule(id, measure, label, keywords, unit, factor, mode="fixed", waste=0.0, exclude=()):
    from app.services.budget_rules import RuleSpec
    return RuleSpec(id=id, measure=measure, label=label, keywords=list(keywords), unit=unit,
                    factor=factor, mode=mode, waste_pct=waste, exclude_keywords=list(exclude))


def test_medidas_desde_elementos():
    from app.services.budget_rules import measures_from_elements

    m = measures_from_elements([
        _el("wall", length=10, height=3),           # 30 m²
        _el("opening", length=1, height=2),         # −2 m²
        _el("column", area=0.04, height=3),         # 0,12 m³
        _el("beam", length=5),
        _el("roof", area=100),
        # 9,5 mm (3/8") → Ø10 con aviso; 8 mm exacto
        _el("armadura", length=10, kg=10 * 0.006165 * 9.5 ** 2),
        _el("armadura", length=12, kg=12 * 0.006165 * 8 ** 2),
        _el("armadura"),                            # sin kg: no computa
    ])
    assert abs(m.values["muro_m2"] - 28) < 1e-9
    assert abs(m.values["columna_m3"] - 0.12) < 1e-9
    assert m.values["viga_ml"] == 5 and m.values["techo_m2"] == 100
    assert abs(m.values["viga_m3"] - 5 * 0.18 * 0.25) < 1e-9   # sin sección: 18×25
    assert set(m.rebar_kg) == {8.0, 10.0}
    assert any("Ø10" in w for w in m.warnings)
    assert any("sin largo" in w for w in m.warnings)


def test_palabras_clave():
    from app.services.budget_rules import matches_keywords

    assert matches_keywords("LAD.CERAM.PORTANTE 12X19X33 PALMAR", ["portante 12"], [])
    assert matches_keywords("PORTANTE 12 - FANTINI, Varios", ["portante 12"], [])
    assert not matches_keywords("PORTANTE 18 - FANTINI", ["portante 12"], [])
    assert not matches_keywords("PORTANTE 120", ["portante 12"], [])
    assert matches_keywords("HIERROS VARIOS", ["hierro"], [])
    assert not matches_keywords("CALIDAD PREMIUM", ["cal"], [])
    assert not matches_keywords("PEGAMENTO CEMENTICIO", ["cemento"], ["pegamento"])
    assert matches_keywords("Cemento Pórtland", ["cemento portland"], [])


def test_conversion_a_unidad_de_venta():
    from app.services.budget_rules import Measures, compute_budget

    m = Measures(values={"columna_m3": 1.0})
    rules = [
        _rule(1, "columna_m3", "Cemento", ["cemento"], "kg", 350),
        _rule(2, "columna_m3", "Arena", ["arena"], "m3", 0.65, waste=10),
    ]
    lines = [
        _line(1, "CEMENTO X 25 KG", 6000, 25, "kg"),
        _line(2, "CEMENTO X 50 KG", 13000, 50, "kg"),     # más caro por kg
        _line(3, "ARENA CAMION 6M3", 150000, 6, "m3"),   # 25.000/m³
        _line(4, "ARENA X M3 BOLSON", 30000, 1, "m3"),
        _line(5, "ARENA FINA SUELTA", 100, 1, "u"),      # no convertible a m³
    ]
    r = compute_budget(m, rules, lines)
    cem, arena = r["items"]
    assert cem["line"]["row"] == 1 and cem["units_to_buy"] == 14.0    # 350 / 25
    assert [a["row"] for a in cem["alternatives"]] == [2]
    assert arena["line"]["row"] == 3                                     # más barato por m³
    assert abs(arena["quantity"] - 0.715) < 1e-9                         # +10%
    assert 5 not in [a["row"] for a in arena["alternatives"]]
    # Lista de compras redondea hacia arriba por renglón.
    shop = {s["row"]: s for s in r["shopping_list"]}
    assert shop[1]["units_to_buy"] == 14 and shop[3]["units_to_buy"] == 1
    assert r["totals"]["net"] == 14 * 6000 + 150000
    assert r["totals"]["total"] == round(r["totals"]["net"] * 1.21, 2)
    assert {ln["row"] for ln in r["unused_lines"]} == {2, 4, 5}


def test_ladrillos_por_medidas_y_respaldo():
    from app.services.budget_rules import Measures, bricks_per_m2, compute_budget

    m = Measures(values={"muro_m2": 100.0})
    rule = _rule(1, "muro_m2", "Ladrillo", ["portante 12"], "u", 15.0, mode="brick_dims")
    con_medidas = compute_budget(m, [rule], [_line(1, "PORTANTE 12X19X33", 900, dims=[12, 19, 33])])
    esperado = 100 * bricks_per_m2([12, 19, 33])
    assert abs(con_medidas["items"][0]["quantity"] - esperado) < 0.01
    assert 14 < bricks_per_m2([12, 19, 33]) < 14.3
    sin_medidas = compute_budget(m, [rule], [_line(1, "PORTANTE 12 - FANTINI", 900)])
    assert sin_medidas["items"][0]["quantity"] == 1500.0


def test_hierro_por_diametro():
    from app.services.budget_rules import Measures, compute_budget

    m = Measures(values={"armadura_kg": 100.0}, rebar_kg={8.0: 47.35, 10.0: 52.65})
    rule = _rule(1, "armadura_kg", "Hierro", ["hierro"], "kg", 1.0, mode="rebar")
    lines = [
        _line(1, "HIERRO 12 MTS - 8 MM", 8000, 12, "m", diameter_mm=8.0),
        _line(2, "HIERRO 10 C/U", 12000, 1, "u", diameter_mm=10.0),   # u → barra de 12 m
    ]
    r = compute_budget(m, [rule], lines)
    d8, d10 = r["items"]
    assert d8["key"] == "1:d8" and d8["label"] == "Hierro Ø8"
    assert abs(d8["units_to_buy"] - 47.35 / (0.006165 * 64 * 12)) < 1e-3   # ~8 barras
    assert d10["line"]["row"] == 2 and d10["status"] == "ok"


def test_sin_precio_sin_medida_y_override():
    from app.services.budget_rules import Measures, compute_budget

    m = Measures(values={"muro_m2": 10.0})
    rules = [
        _rule(1, "muro_m2", "Cemento", ["cemento"], "kg", 3),
        _rule(2, "techo_m2", "Losa", ["losa"], "u", 5.5),
        _rule(3, "muro_m2", "Cal", ["cal"], "kg", 5),
    ]
    lines = [_line(1, "CEMENTO 25 KG", 6000, 25, "kg"), _line(2, "OTRO CEMENTO 25 KG", 7000, 25, "kg")]
    r = compute_budget(m, rules, lines)
    st = {i["key"]: i["status"] for i in r["items"]}
    assert st == {"1": "ok", "2": "sin_medida", "3": "sin_precio"}
    assert r["counts"] == {"ok": 1, "sin_precio": 1, "sin_medida": 1}

    r = compute_budget(m, rules, lines, overrides={"1": 2, "3": None})
    it = {i["key"]: i for i in r["items"]}
    assert it["1"]["line"]["row"] == 2 and it["1"]["manual"] is True
    assert it["3"]["status"] == "sin_precio"


def test_juego_por_defecto_con_presupuestos_reales():
    """Con los PDFs reales (si están) el juego por defecto encuentra precio para
    la obra gruesa del proveedor que la cotiza completa."""
    from app.services.budget_rules import DEFAULT_RULES, Measures, RuleSpec, compute_budget
    from app.services.price_list_parse import parse_price_list

    path = (Path(__file__).resolve().parent.parent / "storage" / "fixtures" / "price_lists"
            / "rptPresupuesto_SILICIO CONSTRU_013.pdf")
    if not path.exists():
        print("        (sin fixture Digimat, se omite)")
        return
    lines = parse_price_list(path.name, path.read_bytes())["lines"]
    rules = [RuleSpec(id=i, measure=r[0], label=r[1], keywords=r[2], unit=r[3], factor=r[4],
                      mode=r[5], waste_pct=r[6], exclude_keywords=r[7])
             for i, r in enumerate(DEFAULT_RULES)]
    # vigueta_ml no: el corralón de obra gruesa no siempre cotiza viguetas.
    m = Measures(values={k: 10.0 for k in ("muro_m2", "columna_m3", "viga_m3", "riostra_m3",
                                           "techo_m2", "losa_m2", "armadura_kg")},
                 rebar_kg={6.0: 2.0, 8.0: 3.0, 10.0: 5.0})
    r = compute_budget(m, rules, lines)
    # Las viguetas pretensadas no las cotiza ese corralón (las vende el fabricante),
    # ni las terminaciones de muro (revoque fino, fijador, pintura): quedan sin
    # precio a propósito; todo lo demás de obra gruesa tiene que encontrarse.
    sin_cotizar = {"Vigueta pretensada", "Revoque fino (2 caras)", "Fijador (2 caras)",
                   "Pintura látex (2 caras, 2 manos)"}
    faltan = [i["label"] for i in r["items"]
              if i["status"] not in ("ok", "sin_medida") and i["label"] not in sin_cotizar]
    assert faltan == [], faltan


def test_vigas_por_volumen_viguetas_y_losas():
    from app.services.budget_rules import measures_from_elements

    m = measures_from_elements([
        _el("beam", length=10, volume_m3=0.9, width_m=0.2, depth_m=0.45),
        _el("beam", length=4, volume_m3=None, width_m=None, depth_m=None),   # sin sección
        _el("vigueta", length=120),
        _el("vigueta", length=30),
        _el("slab", area=80, thickness_m=0.17),
        _el("slab", area=12, thickness_m=None),
    ])
    assert m.values["viga_ml"] == 14 and m.counts["viga_ml"] == 2
    assert abs(m.values["viga_m3"] - (0.9 + 4 * 0.18 * 0.25)) < 1e-9
    assert m.counts["viga_m3"] == 2
    assert m.values["vigueta_ml"] == 150 and m.counts["vigueta_ml"] == 2
    assert m.values["losa_m2"] == 92 and m.counts["losa_m2"] == 2
    d = m.as_dict()
    keys = [x["key"] for x in d["measures"]]
    assert {"viga_ml", "viga_m3", "vigueta_ml", "losa_m2"} <= set(keys)
    assert [a["message"] for a in d["alerts"]] == [
        "1 viga sin sección en el modelo: se estimó 18×25 cm."]
    assert d["alerts"][0]["level"] == "medio"
    assert isinstance(d["warnings"], list)
    # Todas con volumen: sin aviso de sección.
    m = measures_from_elements([_el("beam", length=10, volume_m3=0.9)])
    assert m.alerts == [] and m.values["viga_m3"] == 0.9


def test_riostras_por_volumen():
    """Vigas de fundación / zapatas (type riostra): el hormigón sale del volumen
    real del IFC; sin sección se estima 20×30 y se avisa. El largo sigue
    (mano de obra y Gantt)."""
    from app.services.budget_rules import measures_from_elements

    m = measures_from_elements([
        _el("riostra", length=10, volume_m3=0.875, width_m=0.25, depth_m=0.35),  # VF 25×35
        _el("riostra", length=5, volume_m3=None, width_m=None, depth_m=None),    # sin sección
        _el("riostra", length=2),                       # import viejo: solo largo
    ])
    assert m.values["riostra_ml"] == 17 and m.counts["riostra_ml"] == 3
    assert abs(m.values["riostra_m3"] - (0.875 + 7 * 0.20 * 0.30)) < 1e-9
    assert m.counts["riostra_m3"] == 3
    d = m.as_dict()
    med = {x["key"]: x for x in d["measures"]}
    assert med["riostra_m3"]["label"] == "Vigas de fundación / riostras (volumen)"
    assert med["riostra_m3"]["unit"] == "m3"
    assert [a["message"] for a in d["alerts"]] == [
        "2 vigas de fundación sin sección en el modelo: se estimaron 20×30 cm."]
    assert d["alerts"][0]["level"] == "medio"
    (a,) = measures_from_elements([_el("riostra", length=3)]).alerts
    assert a["message"] == "1 viga de fundación sin sección en el modelo: se estimó 20×30 cm."
    # Todas con volumen: sin aviso.
    m = measures_from_elements([_el("riostra", length=10, volume_m3=0.875)])
    assert m.alerts == [] and m.values["riostra_m3"] == 0.875
    # Vigas y riostras sin sección: un aviso por cada una.
    msgs = [a["message"] for a in _alerts([_el("beam", length=4), _el("riostra", length=4)])]
    assert msgs == ["1 viga sin sección en el modelo: se estimó 18×25 cm.",
                    "1 viga de fundación sin sección en el modelo: se estimó 20×30 cm."], msgs


def test_juego_estandar_riostras_m3():
    from app.services.budget_rules import (DEFAULT_LABOR_RULES, DEFAULT_RULES, MEASURE_STAGE,
                                           MEASURES, RuleSpec, _HORMIGON_NOTE, compute_budget,
                                           measures_from_elements)
    from app.services.budget_schedule import _SHORT

    assert not [r for r in DEFAULT_RULES if r[0] == "riostra_ml"],         "el hormigón de riostras ya no va por metro lineal"
    ri = {r[1]: r for r in DEFAULT_RULES if r[0] == "riostra_m3"}
    assert ri["Cemento (hormigón riostras)"][4] == 350.0
    assert ri["Cemento (hormigón riostras)"][8] == _HORMIGON_NOTE
    assert ri["Arena gruesa (hormigón riostras)"][4] == 0.65
    assert ri["Piedra (hormigón riostras)"][4] == 0.75
    (mo,) = [r for r in DEFAULT_LABOR_RULES if r[1] == "Mano de obra: vigas de fundación"]
    assert mo[0] == "riostra_ml" and mo[2] == "Fundaciones"
    assert MEASURE_STAGE["riostra_m3"] == "Fundaciones" and "riostra_ml" in MEASURES
    assert _SHORT["riostra_m3"] == "hormigón de fundaciones"
    # 40 ml de VF 25×35 = 3,5 m³ -> 3,5 × 350 × 1,05 kg de cemento.
    m = measures_from_elements([_el("riostra", length=40, volume_m3=3.5)])
    rules = [RuleSpec(id=i, measure=r[0], label=r[1], keywords=r[2], unit=r[3], factor=r[4],
                      mode=r[5], waste_pct=r[6], exclude_keywords=r[7])
             for i, r in enumerate(DEFAULT_RULES)]
    r = compute_budget(m, rules, [_line(1, "CEMENTO X 25 KG", 6000, 25, "kg")])
    cem = next(i for i in r["items"] if i["label"] == "Cemento (hormigón riostras)")
    assert cem["status"] == "ok" and cem["measure"] == "riostra_m3"
    assert abs(cem["quantity"] - 3.5 * 350 * 1.05) < 1e-6


def test_juego_estandar_vigas_m3_losas_y_viguetas():
    from app.services.budget_rules import (DEFAULT_LABOR_RULES, DEFAULT_RULES, MEASURE_STAGE,
                                           MEASURES)

    by = {}
    for r in DEFAULT_RULES:
        by.setdefault(r[0], []).append(r)
    assert "viga_ml" not in by, "el hormigón de vigas ya no va por metro lineal"
    vigas = {r[1]: r for r in by["viga_m3"]}
    assert vigas["Cemento (hormigón vigas)"][4] == 350.0
    assert vigas["Arena gruesa (hormigón vigas)"][4] == 0.65
    assert vigas["Piedra (hormigón vigas)"][4] == 0.75
    columnas = [r for r in by["columna_m3"]]
    assert [(r[4], r[6]) for r in by["viga_m3"]] == [(r[4], r[6]) for r in columnas]
    losas = by["losa_m2"]
    assert [r[4] for r in losas] == [5.5, 17.5, 0.0325, 0.0375]
    assert all("entrepiso" in r[1] for r in losas)
    assert [r[4] for r in losas] == [r[4] for r in by["techo_m2"]]
    (vig,) = by["vigueta_ml"]
    assert vig[1:7] == ("Vigueta pretensada", ["vigueta"], "m", 1.0, "fixed", 3)
    labor = {r[0]: r for r in DEFAULT_LABOR_RULES if r[0] in ("viga_ml", "losa_m2")}
    assert labor["viga_ml"][1] == "Mano de obra: vigas de H°A°"
    assert labor["losa_m2"][2] == "Estructura" and labor["losa_m2"][3] == 10.0
    for k in ("viga_m3", "vigueta_ml", "losa_m2"):
        assert MEASURE_STAGE[k] == "Estructura" and k in MEASURES
    assert MEASURES["viga_m3"] == ("Vigas de hormigón (volumen)", "m3")
    assert MEASURES["vigueta_ml"] == ("Viguetas pretensadas (largo)", "m")
    assert MEASURES["losa_m2"] == ("Losas de entrepiso (superficie)", "m2")


def test_aberturas_por_subtype():
    """Puertas y ventanas se cuentan por geometry.subtype; una abertura sin
    subtype (o de otro tipo) descuenta del muro pero no suma unidades."""
    from app.services.budget_rules import MEASURE_STAGE, MEASURES, measures_from_elements
    from app.services.budget_schedule import _SHORT

    m = measures_from_elements([
        _el("wall", length=20, height=3),                          # 60 m² brutos
        _el("opening", length=0.9, height=2.1, subtype="door"),
        _el("opening", length=0.8, height=2.0, subtype="door"),
        _el("opening", length=1.5, height=1.1, subtype="window"),
        _el("opening", length=1.0, height=1.0),                    # sin subtype
        _el("opening", length=1.0, height=1.0, subtype="otro"),
        _el("opening", subtype="window"),                          # sin medidas: cuenta igual
    ])
    assert m.values["puerta_u"] == 2 and m.counts["puerta_u"] == 2
    assert m.values["ventana_u"] == 2 and m.counts["ventana_u"] == 2
    huecos = 0.9 * 2.1 + 0.8 * 2.0 + 1.5 * 1.1 + 1.0 + 1.0
    assert abs(m.values["muro_m2"] - (60 - huecos)) < 1e-9
    d = {x["key"]: x for x in m.as_dict()["measures"]}
    assert d["puerta_u"]["label"] == "Puertas (unidades)" and d["puerta_u"]["unit"] == "u"
    assert d["ventana_u"]["label"] == "Ventanas (unidades)" and d["ventana_u"]["value"] == 2
    assert MEASURE_STAGE["puerta_u"] == MEASURE_STAGE["ventana_u"] == "Aberturas"
    assert _SHORT["puerta_u"] == "puertas" and _SHORT["ventana_u"] == "ventanas"
    # Sin aberturas con subtype: medida en 0 (no falta la clave).
    vacio = measures_from_elements([_el("opening", length=1, height=1)])
    assert vacio.values.get("puerta_u", 0) == 0 and vacio.values.get("ventana_u", 0) == 0


def test_revestimiento_por_material():
    """revestimiento_m2 = L×H (una cara) de muros con material cerámico; esos
    muros siguen en muro_m2. Ladrillo cerámico no es revestimiento."""
    from app.services.budget_rules import (MEASURE_STAGE, MEASURES, is_tiled_wall_material,
                                           measures_from_elements)
    from app.services.budget_schedule import _SHORT

    m = measures_from_elements([
        _el("wall", length=10, height=3, material="Ladrillo"),
        _el("wall", length=4, height=2.5, material="Cerámica blanca"),
        _el("wall", length=2, height=2, material="AZULEJO 20x20"),
        _el("wall", length=3, height=2, material="Revestimiento baño"),
        _el("wall", length=5, height=3, material="Muro por defecto"),
        _el("wall", length=5, height=3, material="Ladrillo cerámico hueco 12"),
        _el("wall", length=5, height=3),                           # sin material
    ])
    assert abs(m.values["revestimiento_m2"] - (10 + 4 + 6)) < 1e-9
    assert m.counts["revestimiento_m2"] == 3
    assert abs(m.values["muro_m2"] - (30 + 10 + 4 + 6 + 15 + 15 + 15)) < 1e-9
    assert is_tiled_wall_material("CERÁMICO") and not is_tiled_wall_material(None)
    assert not is_tiled_wall_material("Bloque cerámico")
    assert MEASURES["revestimiento_m2"] == (
        "Revestimiento cerámico de muros (superficie)", "m2")
    assert MEASURE_STAGE["revestimiento_m2"] == "Revestimientos"
    assert _SHORT["revestimiento_m2"] == "revestimientos"
    assert "revestimiento_m2" not in measures_from_elements(
        [_el("wall", length=5, height=3, material="Ladrillo")]).values


def test_juego_estandar_terminaciones_y_aberturas():
    from app.services.budget_rules import (DEFAULT_LABOR_RULES, DEFAULT_RULES, RuleSpec,
                                           _default_rules, compute_budget, compute_labor,
                                           measures_from_elements)

    mat = {(r[0], r[1]): r for r in DEFAULT_RULES}
    esperado = {
        ("puerta_u", "Puerta"): (["puerta"], "u", 1.0),
        ("ventana_u", "Ventana"): (["ventana"], "u", 1.0),
        ("muro_m2", "Revoque fino (2 caras)"): (["revoque fino"], "kg", 8.0),
        ("muro_m2", "Fijador (2 caras)"): (["fijador"], "l", 0.2),
        ("muro_m2", "Pintura látex (2 caras, 2 manos)"): (["latex", "látex"], "l", 0.5),
        ("revestimiento_m2", "Cerámico de revestimiento"): (["ceramico", "revestimiento"],
                                                            "m2", 1.0),
        ("revestimiento_m2", "Pegamento para cerámicos"): (["pegamento"], "kg", 5.0),
        ("revestimiento_m2", "Pastina"): (["pastina"], "kg", 0.3),
        ("sup_cubierta_m2", "Piso cerámico"): (["piso ceramico", "ceramico"], "m2", 1.0),
        ("sup_cubierta_m2", "Pegamento (piso)"): (["pegamento"], "kg", 5.0),
        ("sup_cubierta_m2", "Pastina (piso)"): (["pastina"], "kg", 0.3),
    }
    for k, (kw, unit, factor) in esperado.items():
        assert k in mat, k
        assert (mat[k][2], mat[k][3], mat[k][4]) == (kw, unit, factor), mat[k]
    assert mat[("muro_m2", "Revoque fino (2 caras)")][6] == 10
    assert mat[("revestimiento_m2", "Cerámico de revestimiento")][6] == 10
    assert mat[("sup_cubierta_m2", "Piso cerámico")][6] == 10
    assert "porcelanato" in mat[("revestimiento_m2", "Pegamento para cerámicos")][7]
    assert "revestimiento" in mat[("sup_cubierta_m2", "Piso cerámico")][7]

    labor = {r[1]: r for r in DEFAULT_LABOR_RULES}
    for lbl, measure, stage in [
            ("Mano de obra: colocación de puertas", "puerta_u", "Aberturas"),
            ("Mano de obra: colocación de ventanas", "ventana_u", "Aberturas"),
            ("Mano de obra: revoque fino (2 caras)", "muro_m2", "Revoques"),
            ("Mano de obra: pintura (2 caras)", "muro_m2", "Pintura"),
            ("Mano de obra: revestimiento cerámico", "revestimiento_m2", "Revestimientos"),
            ("Mano de obra: piso cerámico", "sup_cubierta_m2", "Pisos")]:
        assert labor[lbl][0] == measure and labor[lbl][2] == stage, labor[lbl]
        assert labor[lbl][3] > 0 and labor[lbl][4], labor[lbl]

    # Rubros del juego sembrado: pintura y fijador no quedan en Mampostería.
    seeded = {(r.measure, r.label): r for r in _default_rules()}
    assert seeded[("muro_m2", "Revoque fino (2 caras)")].stage == "Revoques"
    assert seeded[("muro_m2", "Fijador (2 caras)")].stage == "Pintura"
    assert seeded[("muro_m2", "Pintura látex (2 caras, 2 manos)")].stage == "Pintura"
    assert seeded[("muro_m2", "Ladrillo portante 12")].stage == "Mampostería"
    assert seeded[("revestimiento_m2", "Pastina")].stage == "Revestimientos"
    assert seeded[("puerta_u", "Puerta")].stage == "Aberturas"
    assert seeded[("sup_cubierta_m2", "Piso cerámico")].stage == "Pisos"
    lab = seeded[("puerta_u", "Mano de obra: colocación de puertas")]
    assert lab.kind == "labor" and lab.unit == "u"
    assert len({(r.measure, r.label) for r in seeded.values()}) == len(_default_rules())

    # De punta a punta: cerámico por caja de 2,03 m², puertas por unidad.
    m = measures_from_elements([
        _el("wall", length=10, height=3, material="Cerámica blanca"),   # 30 m²
        _el("opening", length=0.9, height=2, subtype="door"),
        _el("opening", length=0.9, height=2, subtype="door"),
        _el("room", area=50),
    ])
    rules = [RuleSpec.of(r) for r in seeded.values()]
    for i, r in enumerate(rules):
        r.id = i
    lines = [
        _line(1, "CERAMICO 45X45 CAJA 2,03 M2", 9000, 2.03, "m2", dims=[45, 45]),
        _line(2, "PUERTA PLACA 80X200", 80000, dims=[80, 200]),
        _line(3, "PEGAMENTO CERAMICOS 30 KG", 7000, 30, "kg"),
        _line(4, "PEGAMENTO PORCELANATO 30 KG", 5000, 30, "kg"),
        _line(5, "LATEX INTERIOR 20 LTS", 60000, 20, "l"),
        _line(6, "LATEX CIELORRASOS 20 LTS", 40000, 20, "l"),
    ]
    r = compute_budget(m, rules, lines)
    it = {i["label"]: i for i in r["items"]}
    rev = it["Cerámico de revestimiento"]
    assert rev["status"] == "ok" and rev["line"]["row"] == 1
    assert abs(rev["quantity"] - 33.0) < 1e-9                      # 30 m² + 10%
    assert abs(rev["units_to_buy"] - 33.0 / 2.03) < 1e-3           # cajas
    piso = it["Piso cerámico"]
    assert piso["line"]["row"] == 1 and abs(piso["quantity"] - 55.0) < 1e-9
    assert it["Puerta"]["status"] == "ok" and it["Puerta"]["units_to_buy"] == 2
    assert it["Ventana"]["status"] == "sin_medida"
    assert it["Pegamento para cerámicos"]["line"]["row"] == 3      # porcelanato excluido
    assert it["Pintura látex (2 caras, 2 manos)"]["line"]["row"] == 5
    # Pintura sobre el muro neto (30 − 2 puertas de 1,8 m²); revestimiento sobre el bruto.
    assert abs(it["Pintura látex (2 caras, 2 manos)"]["quantity"] - 26.4 * 0.5 * 1.05) < 1e-9
    mo = {i["label"]: i for i in compute_labor(m, rules, {})["items"]}
    assert mo["Mano de obra: colocación de puertas"]["quantity"] == 2
    assert mo["Mano de obra: colocación de puertas"]["days"] == 0.5
    assert mo["Mano de obra: revestimiento cerámico"]["quantity"] == 30


def _alerts(elements):
    from app.services.budget_rules import measures_from_elements
    return measures_from_elements(elements).alerts


def _msgs(alerts, texto):
    return [a for a in alerts if texto in a["message"]]


def test_alerta_vigas_vs_columnas():
    cols = [_el("column", area=0.04, height=3) for _ in range(20)]       # 2,4 m³
    # 12 m³ de vigas = 5 veces las columnas → alto
    a = _msgs(_alerts(cols + [_el("beam", length=100, volume_m3=12.0)]), "hormigón de vigas")
    assert len(a) == 1 and a[0]["level"] == "alto", a
    assert "(12,0 m³) es 5 veces el de columnas" in a[0]["message"], a
    # 9 m³ (bajo el mínimo de 10) → no
    assert not _msgs(_alerts(cols + [_el("beam", length=100, volume_m3=9.0)]),
                     "hormigón de vigas")
    # 12 m³ con 4 m³ de columnas (3 veces) → no
    cols4 = [_el("column", area=0.1, height=4) for _ in range(10)]
    assert not _msgs(_alerts(cols4 + [_el("beam", length=100, volume_m3=12.0)]),
                     "hormigón de vigas")
    # Sin columnas: avisa igual, sin dividir por cero.
    a = _msgs(_alerts([_el("beam", length=100, volume_m3=12.0)]), "hormigón de vigas")
    assert len(a) == 1 and "mucho mayor" in a[0]["message"]


def test_alerta_superficie_estimada():
    a = _msgs(_alerts([_el("room", area=100, subtype="estimated_floor")]), "no trae ambientes")
    assert len(a) == 1 and a[0]["level"] == "medio"
    assert not _msgs(_alerts([_el("room", area=100, subtype="room")]), "no trae ambientes")


def test_alerta_sin_losas_de_entrepiso():
    dos_niveles = [_el("wall", length=10, height=3, level="PB"),
                   _el("beam", length=5, volume_m3=0.5, level="P1")]
    a = _msgs(_alerts(dos_niveles), "losas de entrepiso")
    assert len(a) == 1 and a[0]["level"] == "medio"
    assert not _msgs(_alerts(dos_niveles + [_el("slab", area=50)]), "losas de entrepiso")
    un_nivel = [_el("wall", length=10, height=3, level="PB"),
                _el("beam", length=5, volume_m3=0.5, level="PB")]
    assert not _msgs(_alerts(un_nivel), "losas de entrepiso")
    # Sin nivel (PDF/DXF): no se puede saber, no avisa.
    assert not _msgs(_alerts([_el("wall", length=10, height=3)]), "losas de entrepiso")


def test_alerta_cuantia_de_hierro():
    def barra(kg):
        return _el("armadura", length=kg / (0.006165 * 100), kg=kg)   # Ø10 exacto

    room = _el("room", area=100)
    a = _msgs(_alerts([room, barra(500)]), "kg por m² cubierto")      # 5 kg/m²
    assert len(a) == 1 and a[0]["level"] == "medio" and "5,0 kg" in a[0]["message"], a
    assert _msgs(_alerts([room, barra(9000)]), "kg por m² cubierto")  # 90 kg/m²
    assert not _msgs(_alerts([room, barra(4000)]), "kg por m² cubierto")  # 40 kg/m²
    # Sin superficie cubierta o sin armadura: no se puede calcular, no avisa.
    assert not _msgs(_alerts([barra(500)]), "kg por m² cubierto")
    assert not _msgs(_alerts([room]), "kg por m² cubierto")


def test_alerta_cuantia_dice_que_falta():
    def barra(kg, host):
        return _el("armadura", length=kg / (0.006165 * 100), kg=kg, host=host)

    estructura = [_el("room", area=100), _el("column", area=0.04, height=3),
                  _el("beam", length=5, volume_m3=0.5), _el("slab", area=50),
                  _el("riostra", length=10)]
    # Barras solo en vigas (5 kg/m²): dice qué falta, en el orden de la lista.
    (a,) = _msgs(_alerts(estructura + [barra(300, "beam"), barra(200, "beam")]),
                 "kg por m² cubierto")
    assert a["message"] == ("La armadura da 5,0 kg por m² cubierto (lo habitual es 15 a 80). "
                            "El modelo trae hierro solo en vigas: faltan columnas, losas y "
                            "vigas de fundación."), a
    # Columnas y VF con barras: faltan vigas y losas.
    (a,) = _msgs(_alerts(estructura + [barra(300, "column"), barra(200, "riostra")]),
                 "kg por m² cubierto")
    assert a["message"].endswith("solo en columnas y vigas de fundación: faltan vigas y losas."), a
    # Barras con host pero ninguna en un elemento (host desconocido para el modelo).
    (a,) = _msgs(_alerts(estructura + [barra(500, "otro")]), "kg por m² cubierto")
    assert "Ninguna barra del modelo cae en columnas, vigas, losas y vigas de fundación." \
        in a["message"], a
    # Todos los tipos tienen barras pero son pocas: aviso genérico.
    todas = [barra(100, h) for h in ("column", "beam", "slab", "riostra", "beam")]
    (a,) = _msgs(_alerts(estructura + todas), "kg por m² cubierto")
    assert "revisá las barras del modelo" in a["message"], a
    # IFC viejo (barras sin host): aviso genérico, sin decir qué falta.
    viejo = [_el("armadura", length=500 / (0.006165 * 100), kg=500)]
    (a,) = _msgs(_alerts(estructura + viejo), "kg por m² cubierto")
    assert "revisá las barras del modelo" in a["message"] and "faltan" not in a["message"], a
    # Cuantía alta: nunca dice "faltan".
    (a,) = _msgs(_alerts(estructura + [barra(9000, "beam")]), "kg por m² cubierto")
    assert "faltan" not in a["message"], a


def test_proyecto_viejo_solo_largo_de_vigas():
    """Un IFC importado antes de guardar el volumen (beam solo con length) sigue
    dando presupuesto con el juego estándar: viga_m3 estimada a 18×25."""
    from app.services.budget_rules import (DEFAULT_RULES, RuleSpec, compute_budget,
                                           measures_from_elements)

    m = measures_from_elements([_el("beam", length=40) for _ in range(5)]
                               + [_el("column", area=0.04, height=3) for _ in range(10)])
    assert abs(m.values["viga_m3"] - 200 * 0.045) < 1e-9
    assert _msgs(m.alerts, "5 vigas sin sección")
    rules = [RuleSpec(id=i, measure=r[0], label=r[1], keywords=r[2], unit=r[3], factor=r[4],
                      mode=r[5], waste_pct=r[6], exclude_keywords=r[7])
             for i, r in enumerate(DEFAULT_RULES)]
    lines = [_line(1, "CEMENTO X 25 KG", 6000, 25, "kg")]
    r = compute_budget(m, rules, lines)
    cem = next(i for i in r["items"] if i["label"] == "Cemento (hormigón vigas)")
    assert cem["status"] == "ok" and cem["measure"] == "viga_m3"
    assert abs(cem["quantity"] - 9.0 * 350 * 1.05) < 1e-6
    assert r["totals"]["net"] > 0


# --- API ---------------------------------------------------------------------

def _client_as(user):
    from fastapi.testclient import TestClient

    from app.core.deps import get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), lambda: app.dependency_overrides.pop(get_current_user, None)


def _org_admin(db):
    from app.models import Organization, User

    org = Organization(name=f"__test_org__{uuid.uuid4().hex[:8]}")
    db.add(org); db.flush()
    admin = User(email=f"__test_{uuid.uuid4().hex[:8]}@t.local", password_hash="x",
                 organization_id=org.id, org_role="admin")
    member = User(email=f"__test_{uuid.uuid4().hex[:8]}@t.local", password_hash="x",
                  organization_id=org.id, org_role="member")
    db.add_all([admin, member]); db.commit()
    return org, admin, member


def test_api_juegos_de_reglas():
    from app.core.database import SessionLocal
    from app.models import Organization, User
    from app.services.budget_rules import DEFAULT_RULE_SET_NAME

    db = SessionLocal()
    org, admin, member = _org_admin(db)
    client, reset = _client_as(admin)
    try:
        rs = client.get("/api/v1/rule-sets").json()
        estandar = [r for r in rs if r["is_system"]]
        assert len(estandar) == 1, "siempre hay UN juego estándar global"
        std = estandar[0]
        assert std["name"] == DEFAULT_RULE_SET_NAME and std["is_default"]
        assert std["organization_id"] is None and rs[0]["id"] == std["id"], "el estándar va primero"
        std_id = std["id"]

        # Un admin de org NO puede editar ni borrar el estándar...
        r = client.put(f"/api/v1/rule-sets/{std_id}", json={"name": "x", "rules": []})
        assert r.status_code == 403, r.text
        assert client.delete(f"/api/v1/rule-sets/{std_id}").status_code == 400
        # ...pero sí duplicarlo a su org y editar la copia.
        copia = client.post("/api/v1/rule-sets",
                            json={"name": "Económica", "copy_from_id": std_id}).json()
        assert copia["organization_id"] == org.id and not copia["is_system"]
        assert not copia["is_default"] and len(copia["rules"]) == len(std["rules"])

        upd = client.put(f"/api/v1/rule-sets/{copia['id']}", json={
            "name": "Económica", "description": "solo cemento", "is_default": True,
            "rules": [{"measure": "muro_m2", "label": "Cemento", "keywords": [" cemento  "],
                       "unit": "kg", "factor": 2.5}],
        })
        assert upd.status_code == 200, upd.text
        body = upd.json()
        assert [r["keywords"] for r in body["rules"]] == [["cemento"]]
        assert not body["is_default"], "el predeterminado es siempre el estándar"

        bad = client.put(f"/api/v1/rule-sets/{copia['id']}", json={
            "name": "x", "rules": [{"measure": "inventada", "label": "x", "keywords": ["x"],
                                    "unit": "kg", "factor": 1}]})
        assert bad.status_code == 422
        assert bad.json()["detail"] == "Regla 1: Medida inválida: inventada", bad.text

        # 422 legible: detail es UN string en castellano, no la lista de Pydantic.
        regla = {"measure": "muro_m2", "label": "Cemento", "keywords": ["cemento"],
                 "unit": "kg", "factor": 2.5}
        bad = client.put(f"/api/v1/rule-sets/{copia['id']}", json={
            "name": "x", "rules": [regla, {**regla, "waste_pct": 150, "factor": "mucho"}]})
        assert bad.status_code == 422
        detail = bad.json()["detail"]
        assert isinstance(detail, str), detail
        assert "Regla 2: Desperdicio tiene que ser menor o igual a 100" in detail, detail
        assert "Regla 2: Cantidad tiene que ser un número" in detail, detail
        assert "; " in detail and "Input should" not in detail and "body." not in detail
        bad = client.put(f"/api/v1/rule-sets/{copia['id']}", json={"rules": []})
        assert bad.status_code == 422 and bad.json()["detail"] == "Nombre es obligatorio", bad.text

        # Otra org no ve la copia (sí el estándar).
        otra = Organization(name=f"__test_org__{uuid.uuid4().hex[:8]}")
        db.add(otra); db.flush()
        ajeno = User(email=f"test-{uuid.uuid4().hex[:8]}@example.com", password_hash="x",
                     organization_id=otra.id, org_role="admin")
        db.add(ajeno); db.commit()
        reset()
        client, reset = _client_as(ajeno)
        ids = [r["id"] for r in client.get("/api/v1/rule-sets").json()]
        assert std_id in ids and copia["id"] not in ids
        assert client.get(f"/api/v1/rule-sets/{copia['id']}").status_code == 404
        db.delete(otra); db.commit()

        reset()
        client, reset = _client_as(admin)
        assert client.delete(f"/api/v1/rule-sets/{copia['id']}").status_code == 204

        reset()
        client, reset = _client_as(member)
        assert client.get("/api/v1/rule-sets").status_code == 200
        assert client.post("/api/v1/rule-sets", json={"name": "x"}).status_code == 403
    finally:
        reset()
        db.delete(db.get(Organization, org.id))
        db.commit()
        db.close()


def test_superadmin_edita_el_estandar():
    from app.core.database import SessionLocal
    from app.models import Organization, RuleSet, User

    db = SessionLocal()
    org, _, _ = _org_admin(db)
    sa = User(email=f"test-{uuid.uuid4().hex[:8]}@example.com", password_hash="x",
              organization_id=org.id, org_role="member", is_superadmin=True)
    db.add(sa); db.commit()
    client, reset = _client_as(sa)
    std = next(r for r in client.get("/api/v1/rule-sets").json() if r["is_system"])
    original = db.get(RuleSet, std["id"])
    backup = {"name": original.name, "description": original.description,
              "rules": [{k: getattr(r, k) for k in ("measure", "label", "keywords",
                         "exclude_keywords", "unit", "factor", "mode", "waste_pct", "notes",
                         "kind", "stage", "daily_yield", "labor_mode", "unit_price", "crew")}
                        for r in original.rules]}
    try:
        payload = {**backup, "rules": backup["rules"][:1]}
        assert any(r["kind"] == "labor" for r in backup["rules"]), "el estándar trae mano de obra"
        r = client.put(f"/api/v1/rule-sets/{std['id']}", json=payload)
        assert r.status_code == 200, r.text
        assert len(r.json()["rules"]) == 1 and r.json()["is_system"]
    finally:
        # Restaurar el estándar tal cual estaba.
        r = client.put(f"/api/v1/rule-sets/{std['id']}", json=backup)
        assert r.status_code == 200 and len(r.json()["rules"]) == len(backup["rules"])
        reset()
        db.delete(db.get(Organization, org.id))
        db.commit()
        db.close()


def test_seed_concurrente_no_duplica():
    """La UI pide la lista de juegos y el presupuesto a la vez: los dos
    requests siembran en paralelo y antes se creaban dos estándar.

    Para reproducirlo sin tocar el estándar real, se lo "esconde" (is_system
    = false) mientras corre el test y se lo restaura al final."""
    import threading
    import time

    from app.core.database import SessionLocal
    from app.models import RuleSet
    from app.services.budget_rules import ensure_system_rule_set

    db = SessionLocal()
    hidden = [r.id for r in db.query(RuleSet).filter_by(is_system=True)]
    for rid in hidden:
        db.get(RuleSet, rid).is_system = False
    db.commit()
    barrier = threading.Barrier(4)
    errors = []

    def seed():
        s = SessionLocal()
        try:
            barrier.wait()
            ensure_system_rule_set(s)
            # Transacción abierta un rato: sin el lock, los demás threads no
            # ven el seed sin confirmar y siembran otro.
            time.sleep(0.5)
            s.commit()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            s.close()

    threads = [threading.Thread(target=seed) for _ in range(4)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, errors
        nuevos = db.query(RuleSet).filter_by(is_system=True).all()
        assert len(nuevos) == 1, f"se crearon {len(nuevos)} juegos estándar"
    finally:
        db.rollback()
        for r in db.query(RuleSet).filter_by(is_system=True).all():
            if r.id not in hidden:
                db.delete(r)
        for rid in hidden:
            db.get(RuleSet, rid).is_system = True
        db.commit()
        db.close()


if __name__ == "__main__":
    tests = sorted((n, f) for n, f in globals().items()
                   if n.startswith("test_") and callable(f))
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok    {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests pasaron")
    sys.exit(1 if failed else 0)
