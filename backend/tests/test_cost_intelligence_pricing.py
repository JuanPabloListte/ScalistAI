"""Tests de Fase 1a: `PricePoint` + casos de uso de precios con un repo FAKE
in-memory (sin DB). Demuestra la testabilidad de la Clean Architecture: la
lógica de aplicación se prueba sin tocar Postgres.

Corre directo:  python tests/test_cost_intelligence_pricing.py
"""
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.cost_intelligence.application.ports import PriceHistoryRepository  # noqa: E402
from app.cost_intelligence.application.use_cases.get_price_series import GetPriceSeries  # noqa: E402
from app.cost_intelligence.application.use_cases.record_material_price import RecordMaterialPrice  # noqa: E402
from app.cost_intelligence.domain.pricing import PricePoint  # noqa: E402
from app.cost_intelligence.domain.value_objects import Money  # noqa: E402


class FakePriceHistoryRepository(PriceHistoryRepository):
    """Implementación in-memory del puerto, para testear casos de uso sin DB."""

    def __init__(self) -> None:
        self.points: list[PricePoint] = []

    def add(self, point: PricePoint) -> PricePoint:
        self.points.append(point)
        return point

    def latest(self, material_id: int) -> Optional[PricePoint]:
        ps = [p for p in self.points if p.material_id == material_id]
        return max(ps, key=lambda p: p.observed_on) if ps else None

    def series(self, material_id: int, since: Optional[date] = None) -> list[PricePoint]:
        ps = sorted((p for p in self.points if p.material_id == material_id),
                    key=lambda p: p.observed_on)
        return [p for p in ps if since is None or p.observed_on >= since]

    def has_history(self, material_id: int) -> bool:
        return any(p.material_id == material_id for p in self.points)


def test_pricepoint_requires_source():
    try:
        PricePoint(1, Money(100), date.today(), source="")
        assert False, "source vacío debería fallar"
    except ValueError:
        pass


def test_pricepoint_negative_price_raises():
    try:
        PricePoint(1, Money(-1), date.today())
        assert False, "precio negativo debería fallar"
    except ValueError:
        pass


def test_record_adds_point():
    repo = FakePriceHistoryRepository()
    p = RecordMaterialPrice(repo).execute(7, 18000, source="manual", observed_on=date(2026, 1, 1))
    assert p.material_id == 7
    assert p.price.amount == Decimal("18000")
    assert len(repo.points) == 1


def test_series_ordered_and_filtered():
    repo = FakePriceHistoryRepository()
    uc = RecordMaterialPrice(repo)
    uc.execute(7, 100, observed_on=date(2026, 1, 1))
    uc.execute(7, 120, observed_on=date(2026, 3, 1))
    uc.execute(7, 110, observed_on=date(2026, 2, 1))
    series = GetPriceSeries(repo).execute(7)
    assert [float(p.price.amount) for p in series] == [100, 110, 120]  # ordenado por fecha
    assert len(GetPriceSeries(repo).execute(7, since=date(2026, 2, 1))) == 2


def test_latest_returns_most_recent():
    repo = FakePriceHistoryRepository()
    uc = RecordMaterialPrice(repo)
    uc.execute(7, 100, observed_on=date(2026, 1, 1))
    uc.execute(7, 200, observed_on=date(2026, 5, 1))
    assert float(repo.latest(7).price.amount) == 200


def test_has_history_isolates_material():
    repo = FakePriceHistoryRepository()
    RecordMaterialPrice(repo).execute(7, 100)
    assert repo.has_history(7) is True
    assert repo.has_history(99) is False


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
