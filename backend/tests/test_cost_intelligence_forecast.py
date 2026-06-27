"""Tests de Fase 4 (Vía A): el `DeterministicForecaster` (interés compuesto) y
el caso de uso. Matemática pura, sin DB.

Corre directo:  python tests/test_cost_intelligence_forecast.py
"""
import sys
from decimal import Decimal as D
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.cost_intelligence.application.use_cases.forecast_cost import ForecastCost  # noqa: E402
from app.cost_intelligence.domain.value_objects import Money  # noqa: E402
from app.cost_intelligence.infrastructure.forecasting.deterministic import DeterministicForecaster  # noqa: E402


def test_compound_projection():
    r = DeterministicForecaster(D("0.05")).project(Money(100), 6)
    assert r.projected_cost.amount == D("134.01")  # 100 × 1.05^6
    assert round(float(r.variation_pct), 2) == 34.01
    assert r.horizon_months == 6 and r.method == "deterministic"


def test_zero_rate_no_change():
    r = DeterministicForecaster(D("0")).project(Money(150000), 6)
    assert r.projected_cost.amount == D("150000")
    assert r.variation_pct == D("0")


def test_high_inflation_argentina():
    # 8%/mes por 12 meses ≈ 1.08^12 = 2.518 → +151.8 %
    r = DeterministicForecaster(D("0.08")).project(Money(1000), 12)
    assert round(float(r.variation_pct), 1) == 151.8


def test_use_case_rejects_nonpositive_horizon():
    uc = ForecastCost(DeterministicForecaster(D("0.05")))
    try:
        uc.execute(Money(100), 0)
        assert False, "horizonte 0 debería fallar"
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
