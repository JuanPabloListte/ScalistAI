"""Tests de Fase 3: `build_price` (costo directo → precio de venta). Sin DB.

Corre directo:  python tests/test_cost_intelligence_pricing_breakdown.py
"""
import sys
from decimal import Decimal as D
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.cost_intelligence.domain.pricing_breakdown import IndirectRates, build_price  # noqa: E402
from app.cost_intelligence.domain.value_objects import Money  # noqa: E402


def test_breakdown_math():
    # directo 100.000 · gastos generales 15% · beneficio 10% · IVA 21%
    bd = build_price(Money(100000), IndirectRates(D("0.15"), D("0.10"), D("0.21")))
    assert bd.direct.amount == D("100000")
    assert bd.overhead.amount == D("15000")    # 100000 × 0.15
    assert bd.profit.amount == D("11500")      # 115000 × 0.10
    assert bd.net.amount == D("126500")        # 115000 + 11500
    assert bd.iva.amount == D("26565")         # 126500 × 0.21
    assert bd.total.amount == D("153065")      # 126500 + 26565


def test_zero_rates_total_equals_direct():
    bd = build_price(Money(1000), IndirectRates(D("0"), D("0"), D("0")))
    assert bd.total.amount == D("1000")


def test_negative_rate_raises():
    try:
        IndirectRates(D("-0.1"), D("0.1"), D("0.21"))
        assert False, "tasa negativa debería fallar"
    except ValueError:
        pass


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"  ok    {t.__name__}")
            passed += 1
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL  {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests pasaron")
    return passed == len(tests)


if __name__ == "__main__":
    sys.exit(0 if _run() else 1)
