"""Test del cross-validation híbrido (vectorial + IA).

Verifica la garantía central del esquema híbrido: las predicciones de la IA
que se superponen con elementos vectoriales del CAD se descartan (no se
duplican muros que ambos motores detectaron), y las que caen en zonas vacías
sobreviven como candidatos gap-fill.

Corre con pytest o directo (python tests/test_hybrid_validation.py) en
cualquier entorno con opencv+numpy: el módulo no depende del stack backend.
"""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "hybrid_validation",
        BACKEND_DIR / "app" / "services" / "hybrid_validation.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hv = _load_module()

# Página de prueba: 2000x1500 px, 100 px/m (20m x 15m).
IMG_W, IMG_H = 2000, 1500
PX_PER_M = 100.0


def _vec(points: list[float]) -> SimpleNamespace:
    """Stub mínimo de DetectedElement: solo .geometry."""
    return SimpleNamespace(geometry={"points": points})


def _cand(points: list[float]) -> dict:
    return {"geometry": {"points": points}, "length_m": 5.0}


def test_overlapping_wall_is_dropped():
    """Muro IA sobre el mismo eje que el muro CAD → duplicado, se descarta."""
    vector = [_vec([100, 100, 600, 100])]   # muro horizontal de 5m
    ai = [_cand([105, 103, 595, 103])]      # mismo muro, corrido ~3px
    kept = hv.filter_gap_fill_candidates(vector, ai, "wall", PX_PER_M, IMG_W, IMG_H)
    assert kept == [], f"el muro duplicado debió descartarse, quedó: {kept}"


def test_distant_wall_is_kept():
    """Muro IA en zona donde el CAD no tiene nada → gap-fill, se conserva."""
    vector = [_vec([100, 100, 600, 100])]
    ai = [_cand([100, 800, 600, 800])]      # 7m más abajo
    kept = hv.filter_gap_fill_candidates(vector, ai, "wall", PX_PER_M, IMG_W, IMG_H)
    assert len(kept) == 1, "el muro nuevo debió conservarse como candidato"


def test_parallel_wall_outside_buffer_is_kept():
    """Muro paralelo a 1m del CAD (fuera del buffer de 35cm) → se conserva."""
    vector = [_vec([100, 100, 600, 100])]
    ai = [_cand([100, 200, 600, 200])]      # paralelo a 1.0 m
    kept = hv.filter_gap_fill_candidates(vector, ai, "wall", PX_PER_M, IMG_W, IMG_H)
    assert len(kept) == 1, "un muro paralelo a 1m no es duplicado"


def test_partial_overlap_below_threshold_is_kept():
    """Muro IA que solo coincide en un tramo corto (<50%) → se conserva."""
    vector = [_vec([100, 100, 300, 100])]   # CAD: 2m
    ai = [_cand([100, 100, 900, 100])]      # IA: 8m sobre la misma línea
    kept = hv.filter_gap_fill_candidates(vector, ai, "wall", PX_PER_M, IMG_W, IMG_H)
    assert len(kept) == 1, "cobertura 25% no alcanza el umbral de duplicado"


def test_no_vector_elements_keeps_all():
    """Sin elementos CAD de ese tipo, todos los candidatos son gap-fill."""
    ai = [_cand([100, 100, 600, 100]), _cand([100, 300, 600, 300])]
    kept = hv.filter_gap_fill_candidates([], ai, "wall", PX_PER_M, IMG_W, IMG_H)
    assert len(kept) == 2


def test_room_polygon_duplicate_dropped():
    """Recinto IA con el mismo contorno que el CAD → duplicado."""
    square = [200, 200, 800, 200, 800, 800, 200, 800]
    vector = [_vec(square)]
    ai = [{"geometry": {"points": [205, 204, 803, 203, 802, 804, 201, 803]}}]
    kept = hv.filter_gap_fill_candidates(vector, ai, "room", PX_PER_M, IMG_W, IMG_H)
    assert kept == [], "el recinto duplicado debió descartarse"


def test_opening_near_vector_center_dropped():
    """Abertura IA a <60cm del centro de una abertura CAD → duplicado."""
    vector = [_vec([300, 300, 380, 300])]   # abertura de 80cm centrada en (340,300)
    ai = [
        {"cx": 350.0, "cy": 305.0},          # a ~11cm → duplicado
        {"cx": 340.0, "cy": 700.0},          # a 4m → gap-fill
    ]
    kept = hv.filter_gap_fill_openings(vector, ai, PX_PER_M)
    assert len(kept) == 1 and kept[0]["cy"] == 700.0


def test_opening_without_scale_keeps_all():
    """Sin escala no se puede matchear: no se descarta nada (conservador)."""
    vector = [_vec([300, 300, 380, 300])]
    ai = [{"cx": 350.0, "cy": 305.0}]
    kept = hv.filter_gap_fill_openings(vector, ai, None)
    assert len(kept) == 1


def _run_all() -> None:
    import traceback

    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok    {t.__name__}")
        except AssertionError:
            failed += 1
            print(f"  FAIL  {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} tests pasaron")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    _run_all()
