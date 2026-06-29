"""Tests del forecaster por-material (Vía B-lite): proyecta desde la SERIE PROPIA
del material, cae a IPC si no alcanza. Matemática pura, sin DB.

Corre directo:  python tests/test_cost_intelligence_material_trend.py
"""
import sys
from datetime import date
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.cost_intelligence.domain.material_trend import (  # noqa: E402
    METHOD_IPC, METHOD_NONE, METHOD_OWN, project_material,
)


def test_own_trend_two_points():
    # Hormigón: $100 hace 3 meses, $133.10 hoy -> ~10%/mes; proyecta 6 meses.
    f = project_material(
        [(date(2024, 1, 1), 100.0), (date(2024, 4, 1), 133.10)],
        horizon_months=6, ipc_monthly_rate=0.05)
    assert f.method == METHOD_OWN
    assert f.n_points == 2
    assert round(f.monthly_rate, 3) == 0.100          # (1.331)^(1/3)-1 ≈ 0.10
    assert round(f.projected_price, 0) == 236.0        # 133.1 × 1.10^6
    assert f.beats_inflation is True                   # 10%/mes > 5%/mes IPC


def test_single_point_falls_back_to_ipc():
    f = project_material([(date(2026, 6, 1), 1000.0)], 6, ipc_monthly_rate=0.04)
    assert f.method == METHOD_IPC
    assert f.n_points == 1
    assert f.monthly_rate == 0.04
    assert round(f.projected_price, 2) == round(1000.0 * 1.04 ** 6, 2)
    assert f.beats_inflation is None


def test_single_point_no_ipc_is_flat():
    f = project_material([(date(2026, 6, 1), 1000.0)], 6, ipc_monthly_rate=None)
    assert f.method == METHOD_NONE
    assert f.projected_price == 1000.0                 # sin dato -> no proyecta
    assert f.variation_pct == 0.0


def test_same_day_multiple_vendors_count_as_one_point():
    # 3 cotizaciones el mismo día (varios proveedores) = 1 punto de tendencia.
    f = project_material(
        [(date(2023, 9, 27), 2482.0), (date(2023, 9, 27), 2624.0),
         (date(2023, 9, 27), 2434.0)],
        6, ipc_monthly_rate=0.05)
    assert f.n_points == 1
    assert f.method == METHOD_IPC                       # 1 fecha distinta -> IPC


def test_below_inflation_flag():
    # Sube 2%/mes, IPC 5%/mes -> NO le gana a la inflación.
    f = project_material(
        [(date(2024, 1, 1), 100.0), (date(2024, 7, 1), 112.6)],
        6, ipc_monthly_rate=0.05)
    assert f.method == METHOD_OWN
    assert f.beats_inflation is False


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("todos los tests pasaron")
