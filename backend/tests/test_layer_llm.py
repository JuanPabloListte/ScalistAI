"""Tests del fallback semántico de capas (layer_llm) y su integración DXF.

- _parse_answer: mapea respuestas sucias del LLM a tipos canónicos
  (incluye la regla pluvial → None).
- classify_layers_cached: solo lee caché, distingue miss de "cacheado None".
- prewarm_layers_async: no dispara hilo si todo está cacheado.
- get_dxf_info: una capa críptica (sin keyword) recibe la sugerencia desde la
  caché del LLM, sin llamar a Ollama (endpoint síncrono nunca bloquea).

Corre directo: python tests/test_layer_llm.py
"""

import importlib.util
import json
import sys
import tempfile
import threading
import types
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _load_layer_llm(cache_file: Path):
    spec = importlib.util.spec_from_file_location(
        "layer_llm_under_test", BACKEND_DIR / "app" / "services" / "layer_llm.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._CACHE_FILE = cache_file  # aislar la caché real del producto
    return mod


def test_parse_answer():
    llm = _load_layer_llm(Path(tempfile.mkdtemp()) / "cache.json")
    assert llm._parse_answer("wall") == "wall"
    assert llm._parse_answer("  Muro (pared exterior)") == "wall"
    assert llm._parse_answer("cloacal") == "cloaca"
    assert llm._parse_answer("desagüe pluvial") is None  # pluvial nunca es cloaca
    assert llm._parse_answer("otro") is None
    assert llm._parse_answer("") is None


def test_cached_distingue_miss_de_none():
    tmp = Path(tempfile.mkdtemp())
    cache = tmp / "cache.json"
    cache.write_text(json.dumps({"TUONG": "wall", "HATCH_37": None}), encoding="utf-8")
    llm = _load_layer_llm(cache)

    got = llm.classify_layers_cached(["TUONG", "HATCH_37", "NUNCA_VISTA"])
    assert got == {"TUONG": "wall", "HATCH_37": None}
    assert "NUNCA_VISTA" not in got  # miss: debe ir al prewarm, no confundirse con None


def test_prewarm_no_dispara_si_todo_cacheado():
    tmp = Path(tempfile.mkdtemp())
    cache = tmp / "cache.json"
    cache.write_text(json.dumps({"TUONG": "wall"}), encoding="utf-8")
    llm = _load_layer_llm(cache)

    started: list[str] = []
    real_thread = threading.Thread

    class SpyThread(real_thread):
        def start(self):  # noqa: D102
            started.append(self.name)
            # no arrancamos de verdad: el test no depende de Ollama

    llm.threading = types.SimpleNamespace(Thread=SpyThread)
    llm.prewarm_layers_async(["TUONG"])          # cacheada → nada
    assert started == []
    llm.prewarm_layers_async(["TUONG", "NUEVA"])  # un miss → un hilo
    assert len(started) == 1


def test_get_dxf_info_sugiere_desde_cache_llm():
    """Capa críptica sin keyword → sugerencia desde la caché LLM (sin red)."""
    # Reusar los stubs/loader del test DXF para importar dxf_import aislado.
    sys.path.insert(0, str(BACKEND_DIR / "tests"))
    from test_dxf_import import _load_dxf_import

    import ezdxf

    dxf = _load_dxf_import()
    tmp = Path(tempfile.mkdtemp())

    # DXF con una capa reconocible por keyword y una críptica.
    doc = ezdxf.new("R2010")
    doc.layers.add("ARQ_MURO")
    doc.layers.add("TUONG-01")   # "muro" en vietnamita: keyword no la agarra
    msp = doc.modelspace()
    msp.add_line((0, 0), (10000, 0), dxfattribs={"layer": "ARQ_MURO"})
    msp.add_line((0, 500), (8000, 500), dxfattribs={"layer": "TUONG-01"})
    path = tmp / "plano.dxf"
    doc.saveas(path)

    # Caché LLM ya conoce TUONG-01 (de un import previo) y una decisión "pozo"
    # que el DXF NO debe sugerir (tipo sin soporte en el mapeo).
    cache = tmp / "layer_cache.json"
    cache.write_text(json.dumps({"TUONG-01": "wall", "OTRA": "pozo"}), encoding="utf-8")

    llm_stub = types.ModuleType("app.services.layer_llm")
    real = _load_layer_llm(cache)
    llm_stub.classify_layers_cached = real.classify_layers_cached
    prewarmed: list[list[str]] = []
    llm_stub.prewarm_layers_async = lambda names: prewarmed.append(sorted(names))
    sys.modules["app.services.layer_llm"] = llm_stub

    plan = types.SimpleNamespace(pdf_path=str(path), page_scales={})
    info = dxf.get_dxf_info(plan)
    by_name = {l["name"]: l["suggested_type"] for l in info["layers"]}

    assert by_name["ARQ_MURO"] == "wall"      # keyword, como siempre
    assert by_name["TUONG-01"] == "wall"      # ← vino de la caché del LLM
    assert prewarmed == [], f"con todo cacheado no debería prewarmar: {prewarmed}"


if __name__ == "__main__":
    failed = 0
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        try:
            fn()
            print(f"  ok    {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {name}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests pasaron")
    sys.exit(1 if failed else 0)
