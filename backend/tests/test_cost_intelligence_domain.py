"""Tests del domain layer del Motor de Inteligencia de Costos (Fase 0).

Verifica los value objects (`Money`, `Quantity`) y el contrato de medición
(`measure_for`) — la fuente de verdad única de "qué medida consume cada receta".

Corre directo (sin pytest):  python tests/test_cost_intelligence_domain.py
"""
import sys
from decimal import Decimal
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.cost_intelligence.domain.measurement import (  # noqa: E402
    ElementGeometry, measure_for, unit_for,
)
from app.cost_intelligence.domain.value_objects import Money, Quantity  # noqa: E402


# ---- Money ----

def test_money_add_sub_mul():
    a = Money(Decimal("100.50"))
    b = Money(Decimal("9.50"))
    assert (a + b).amount == Decimal("110.00")
    assert (a - b).amount == Decimal("91.00")
    assert (a * 3).amount == Decimal("301.50")


def test_money_no_float_drift():
    # 0.1 + 0.2 con float da 0.30000000000000004; con Decimal es exacto.
    assert (Money(0.1) + Money(0.2)).amount == Decimal("0.3")


def test_money_currency_mismatch_raises():
    try:
        Money(10, "ARS") + Money(10, "USD")
        assert False, "debería fallar sumar monedas distintas"
    except ValueError:
        pass


def test_money_rounding():
    assert Money(Decimal("100.005")).rounded().amount == Decimal("100.01")


# ---- Quantity ----

def test_quantity_add_same_unit():
    assert (Quantity(2, "m2") + Quantity(3, "m2")).value == Decimal("5")


def test_quantity_unit_mismatch_raises():
    try:
        Quantity(1, "m2") + Quantity(1, "ml")
        assert False, "debería fallar sumar unidades distintas"
    except ValueError:
        pass


def test_quantity_negative_raises():
    try:
        Quantity(-1, "m2")
        assert False, "cantidad negativa debería fallar"
    except ValueError:
        pass


# ---- measure_for: el contrato por tipo ----

def test_measure_wall_is_length_times_height():
    q = measure_for("wall", ElementGeometry(length_m=10.0, height_m=2.5))
    assert q is not None and q.unit == "m2" and q.value == Decimal("25.0")


def test_measure_wall_default_height():
    q = measure_for("wall", ElementGeometry(length_m=10.0))
    assert q is not None and q.value == Decimal("28.0")  # 10 × 2.8 por defecto


def test_measure_area_types():
    for t in ("room_floor", "roof", "escalera"):
        q = measure_for(t, ElementGeometry(area_m2=45.8))
        assert q is not None and q.unit == "m2" and q.value == Decimal("45.8")


def test_measure_length_types():
    for t in ("beam", "riostra", "cloaca", "electricidad", "room_perimeter"):
        q = measure_for(t, ElementGeometry(length_m=12.3))
        assert q is not None and q.unit == "ml" and q.value == Decimal("12.3")


def test_measure_opening_default_height():
    q = measure_for("opening", ElementGeometry(length_m=1.0))
    assert q is not None and q.value == Decimal("2.1")  # altura abertura por defecto


def test_measure_column_pozo_section_quirk():
    # Preserva el comportamiento actual: sección sin altura.
    for t in ("column", "pozo"):
        q = measure_for(t, ElementGeometry(area_m2=0.0324, height_m=2.8))
        assert q is not None and q.unit == "m2" and q.value == Decimal("0.0324")


def test_measure_unknown_or_missing_returns_none():
    assert measure_for("gas", ElementGeometry(length_m=5.0)) is None
    assert measure_for("wall", ElementGeometry()) is None  # sin geometría
    assert measure_for("roof", ElementGeometry(area_m2=0.0)) is None
    assert unit_for("gas") is None and unit_for("beam") == "ml"


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
