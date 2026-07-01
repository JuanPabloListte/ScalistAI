"""Tests de Fase 1b: `LaborRatePoint` + casos de uso de mano de obra con un repo
FAKE in-memory (sin DB). Mismo patrón testeable que pricing.

Corre directo:  python tests/test_cost_intelligence_labor.py
"""
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.cost_intelligence.application.ports import LaborRateHistoryRepository  # noqa: E402
from app.cost_intelligence.application.use_cases.get_labor_rate_history import GetLaborRateHistory  # noqa: E402
from app.cost_intelligence.application.use_cases.record_labor_rate import RecordLaborRate  # noqa: E402
from app.cost_intelligence.domain.labor import LaborRatePoint  # noqa: E402
from app.cost_intelligence.domain.value_objects import Money  # noqa: E402


class FakeLaborRateHistoryRepository(LaborRateHistoryRepository):
    def __init__(self) -> None:
        self.points: list[LaborRatePoint] = []

    def add(self, point: LaborRatePoint) -> LaborRatePoint:
        self.points.append(point)
        return point

    def latest(self, labor_rate_id: int) -> Optional[LaborRatePoint]:
        ps = [p for p in self.points if p.labor_rate_id == labor_rate_id]
        return max(ps, key=lambda p: p.observed_on) if ps else None

    def series(self, labor_rate_id: int, since: Optional[date] = None) -> list[LaborRatePoint]:
        ps = sorted((p for p in self.points if p.labor_rate_id == labor_rate_id),
                    key=lambda p: p.observed_on)
        return [p for p in ps if since is None or p.observed_on >= since]

    def has_history(self, labor_rate_id: int) -> bool:
        return any(p.labor_rate_id == labor_rate_id for p in self.points)


def test_laborratepoint_requires_source():
    try:
        LaborRatePoint(1, Money(40000), date.today(), source="")
        assert False, "source vacío debería fallar"
    except ValueError:
        pass


def test_laborratepoint_negative_raises():
    try:
        LaborRatePoint(1, Money(-1), date.today())
        assert False, "costo negativo debería fallar"
    except ValueError:
        pass


def test_record_adds_point():
    repo = FakeLaborRateHistoryRepository()
    p = RecordLaborRate(repo).execute(1, 44000, source="manual", observed_on=date(2026, 1, 1))
    assert p.labor_rate_id == 1
    assert p.daily_cost.amount == Decimal("44000")
    assert len(repo.points) == 1


def test_series_ordered_and_filtered():
    repo = FakeLaborRateHistoryRepository()
    uc = RecordLaborRate(repo)
    uc.execute(1, 30000, observed_on=date(2026, 1, 1))
    uc.execute(1, 50000, observed_on=date(2026, 5, 1))
    uc.execute(1, 40000, observed_on=date(2026, 3, 1))
    series = GetLaborRateHistory(repo).execute(1)
    assert [float(p.daily_cost.amount) for p in series] == [30000, 40000, 50000]
    assert len(GetLaborRateHistory(repo).execute(1, since=date(2026, 3, 1))) == 2


def test_latest_returns_most_recent():
    repo = FakeLaborRateHistoryRepository()
    uc = RecordLaborRate(repo)
    uc.execute(1, 30000, observed_on=date(2026, 1, 1))
    uc.execute(1, 60000, observed_on=date(2026, 6, 1))
    assert float(repo.latest(1).daily_cost.amount) == 60000


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
