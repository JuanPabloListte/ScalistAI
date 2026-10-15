"""Presupuesto por reglas (services/budget_rules.py) + API de juegos de reglas.

Corre directo: python tests/test_budget_rules.py (dentro del contenedor).
Los tests de motor no usan DB; los de API crean una org de test y la borran.
"""
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _el(type, length=None, area=None, height=None, **geom):
    return NS(type=type, length_m=length, area_m2=area, height_m=height, geometry=geom)


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
    m = Measures(values={k: 10.0 for k in ("muro_m2", "columna_m3", "viga_ml", "riostra_ml",
                                           "techo_m2", "armadura_kg")},
                 rebar_kg={6.0: 2.0, 8.0: 3.0, 10.0: 5.0})
    r = compute_budget(m, rules, lines)
    faltan = [i["label"] for i in r["items"] if i["status"] != "ok"]
    assert faltan == [], faltan


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
    from app.models import Organization
    from app.services.budget_rules import DEFAULT_RULES

    db = SessionLocal()
    org, admin, member = _org_admin(db)
    client, reset = _client_as(admin)
    try:
        rs = client.get("/api/v1/rule-sets").json()
        assert len(rs) == 1 and rs[0]["is_default"] and len(rs[0]["rules"]) == len(DEFAULT_RULES)
        default_id = rs[0]["id"]
        assert len(client.get("/api/v1/rule-sets").json()) == 1, "el seed no se duplica"

        copia = client.post("/api/v1/rule-sets",
                            json={"name": "Económica", "copy_from_id": default_id}).json()
        assert copia["name"] == "Económica" and not copia["is_default"]
        assert len(copia["rules"]) == len(DEFAULT_RULES)

        upd = client.put(f"/api/v1/rule-sets/{copia['id']}", json={
            "name": "Económica", "description": "solo cemento", "is_default": True,
            "rules": [{"measure": "muro_m2", "label": "Cemento", "keywords": [" cemento  "],
                       "unit": "kg", "factor": 2.5}],
        })
        assert upd.status_code == 200, upd.text
        body = upd.json()
        assert body["is_default"] and [r["keywords"] for r in body["rules"]] == [["cemento"]]
        assert not client.get(f"/api/v1/rule-sets/{default_id}").json()["is_default"]

        bad = client.put(f"/api/v1/rule-sets/{copia['id']}", json={
            "name": "x", "rules": [{"measure": "inventada", "label": "x", "keywords": ["x"],
                                    "unit": "kg", "factor": 1}]})
        assert bad.status_code == 422

        assert client.delete(f"/api/v1/rule-sets/{copia['id']}").status_code == 204
        assert client.get(f"/api/v1/rule-sets/{default_id}").json()["is_default"]
        assert client.delete(f"/api/v1/rule-sets/{default_id}").status_code == 400

        reset()
        client, reset = _client_as(member)
        assert client.get("/api/v1/rule-sets").status_code == 200
        assert client.post("/api/v1/rule-sets", json={"name": "x"}).status_code == 403
    finally:
        reset()
        db.delete(db.get(Organization, org.id))
        db.commit()
        db.close()


def test_seed_concurrente_no_duplica():
    """La UI pide la lista de juegos y el presupuesto a la vez: los dos
    requests siembran en paralelo y antes se creaban dos predeterminados."""
    import threading
    import time

    from app.core.database import SessionLocal
    from app.models import Organization, RuleSet
    from app.services.budget_rules import ensure_default_rule_set

    db = SessionLocal()
    org = Organization(name=f"__test_org__{uuid.uuid4().hex[:8]}")
    db.add(org); db.commit()
    org_id = org.id  # no tocar `org` desde los threads (es de otra sesión)
    barrier = threading.Barrier(4)
    errors = []

    def seed():
        s = SessionLocal()
        try:
            barrier.wait()
            ensure_default_rule_set(org_id, s)
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
        n = db.query(RuleSet).filter_by(organization_id=org_id).count()
        assert n == 1, f"se crearon {n} juegos por defecto"
    finally:
        db.delete(db.get(Organization, org_id))
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
