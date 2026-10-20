"""Mano de obra y precio de venta (services/budget_rules.compute_labor / compute_price).

Corre directo: python tests/test_labor_budget.py (dentro del contenedor). Sin DB.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CUADRILLA = [{"trade": "Oficial", "count": 1}, {"trade": "Ayudante", "count": 1}]
JORNALES = {"Oficial": 60000.0, "Ayudante": 45000.0}


def _measures(**values):
    from app.services.budget_rules import Measures
    return Measures(values=values)


def _labor(id, measure, label, stage, yield_=8.0, mode="unit", price=None, crew=CUADRILLA):
    from app.services.budget_rules import RuleSpec
    return RuleSpec(id=id, measure=measure, label=label, keywords=[], unit="m2", factor=1.0,
                    kind="labor", stage=stage, daily_yield=yield_, labor_mode=mode,
                    unit_price=price, crew=crew)


def test_tercerizado_por_unidad():
    from app.services.budget_rules import compute_labor

    r = compute_labor(_measures(muro_m2=100), [_labor(1, "muro_m2", "Mampostería", "Mampostería",
                                                      price=18000)], JORNALES)
    it = r["items"][0]
    assert it["status"] == "ok" and it["cost"] == 1_800_000, it
    assert it["days"] == 12.5, it  # el rendimiento da el plazo aunque se pague por m²
    assert r["total"] == 1_800_000


def test_cuadrilla_propia_por_jornal():
    from app.services.budget_rules import compute_labor

    r = compute_labor(_measures(muro_m2=100), [_labor(1, "muro_m2", "Mampostería", "Mampostería",
                                                      mode="daily")], JORNALES)
    it = r["items"][0]
    # 100 m² / 8 m² por día = 12,5 días × (60.000 + 45.000)
    assert it["status"] == "ok" and it["cost"] == 1_312_500, it
    assert it["workdays"] == 25.0 and it["unit_price"] == 13125, it


def test_el_proyecto_pisa_modo_y_precio():
    from app.services.budget_rules import compute_labor

    rules = [_labor(1, "muro_m2", "Mampostería", "Mampostería", mode="daily"),
             _labor(2, "muro_m2", "Revoques", "Revoques", price=9000)]
    r = compute_labor(_measures(muro_m2=50), rules, JORNALES, {
        "1": {"mode": "unit", "unit_price": 21500},  # esta obra la terceriza
        "2": {"mode": "daily"},                       # y los revoques los hace su gente
    })
    a, b = r["items"]
    assert a["mode"] == "unit" and a["cost"] == 1_075_000 and a["manual"], a
    assert b["mode"] == "daily" and b["cost"] == round(50 / 8 * 105000, 2), b


def test_estados_pendientes():
    from app.services.budget_rules import compute_labor

    r = compute_labor(
        _measures(muro_m2=40, viga_ml=0),
        [_labor(1, "muro_m2", "Sin precio", "Mampostería"),
         _labor(2, "muro_m2", "Sin jornal", "Mampostería", mode="daily",
                crew=[{"trade": "Oficial especializado", "count": 1}]),
         _labor(3, "muro_m2", "Sin rendimiento", "Mampostería", mode="daily", yield_=None),
         _labor(4, "viga_ml", "Sin medida", "Estructura", price=5000)],
        JORNALES)
    st = {i["label"]: i for i in r["items"]}
    assert st["Sin precio"]["status"] == "sin_precio"
    assert st["Sin jornal"]["status"] == "sin_jornal"
    assert st["Sin jornal"]["missing_trades"] == ["Oficial especializado"]
    assert st["Sin rendimiento"]["status"] == "sin_rendimiento"
    assert st["Sin medida"]["status"] == "sin_medida"
    assert r["total"] == 0 and r["counts"]["pendientes"] == 3


def test_agrupa_por_rubro_y_no_mezcla_materiales():
    from app.services.budget_rules import RuleSpec, compute_budget, compute_labor

    mat = RuleSpec(id=9, measure="muro_m2", label="Cemento", keywords=["cemento"], unit="kg",
                   factor=3.0)
    rules = [mat, _labor(1, "muro_m2", "Mampostería", "Mampostería", price=1000),
             _labor(2, "muro_m2", "Revoques", "Mampostería", price=500)]
    labor = compute_labor(_measures(muro_m2=10), rules, JORNALES)
    assert [i["label"] for i in labor["items"]] == ["Mampostería", "Revoques"]
    assert labor["by_stage"] == [{"stage": "Mampostería", "cost": 15000.0, "items": ["1", "2"]}]
    budget = compute_budget(_measures(muro_m2=10), rules, [])
    assert [i["label"] for i in budget["items"]] == ["Cemento"], budget["items"]


def test_precio_de_venta():
    from app.services.budget_rules import compute_price

    p = compute_price(1_000_000, 500_000, overhead_pct=0.15, profit_pct=0.10, iva_pct=0.21)
    assert p["direct"] == 1_500_000
    assert p["overhead"] == 225_000
    assert p["profit"] == 172_500        # 10% sobre directo + GG
    assert p["net"] == 1_897_500
    assert p["iva"] == 398_475
    assert p["total"] == 2_295_975


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
