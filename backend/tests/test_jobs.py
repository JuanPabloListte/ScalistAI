"""Tests del despachador de trabajos pesados (app/core/jobs.py).

La garantía central es la DEGRADACIÓN: la app nunca depende de que el worker
exista. Se cubren los tres caminos de enqueue():
- "queued": Redis + rq disponibles → el job va a la cola (no se ejecuta acá).
- "inline-background": sin Redis, con BackgroundTasks del request → add_task.
- "inline-thread": sin Redis ni request → thread daemon que SÍ ejecuta.

Corre directo: python tests/test_jobs.py
"""

import importlib.util
import sys
import threading
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _load_jobs():
    # jobs.py importa app.core.config a nivel módulo → el paquete `app`
    # tiene que ser resoluble (corriendo como script no lo es por default).
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    spec = importlib.util.spec_from_file_location(
        "jobs_under_test", BACKEND_DIR / "app" / "core" / "jobs.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _job_marker(value):  # el "trabajo": deja constancia de que corrió
    _job_marker.calls.append(value)


_job_marker.calls = []


def test_fallback_thread_ejecuta():
    jobs = _load_jobs()
    jobs._get_raw_redis = lambda: None  # sin Redis

    _job_marker.calls.clear()
    got = jobs.enqueue(_job_marker, "hola")
    assert got == "inline-thread"
    for _ in range(50):  # el thread daemon tarda un instante
        if _job_marker.calls:
            break
        time.sleep(0.05)
    assert _job_marker.calls == ["hola"], "el fallback por thread no ejecutó el job"


def test_fallback_background_tasks():
    jobs = _load_jobs()
    jobs._get_raw_redis = lambda: None

    class FakeBackgroundTasks:
        def __init__(self):
            self.tasks = []

        def add_task(self, fn, *args):
            self.tasks.append((fn, args))

    bg = FakeBackgroundTasks()
    got = jobs.enqueue(_job_marker, 42, background_tasks=bg)
    assert got == "inline-background"
    assert bg.tasks == [(_job_marker, (42,))], "no delegó en BackgroundTasks"


def test_camino_queued_no_ejecuta_local():
    jobs = _load_jobs()

    enqueued = []

    class FakeQueue:
        def __init__(self, name, connection):
            assert name == jobs.QUEUE_NAME
            self._conn = connection

        def enqueue(self, fn, *args, job_timeout=None):
            enqueued.append((fn, args, job_timeout))

    import types

    jobs._get_raw_redis = lambda: object()          # "hay Redis"
    fake_rq = types.ModuleType("rq")
    fake_rq.Queue = FakeQueue
    sys.modules["rq"] = fake_rq
    try:
        _job_marker.calls.clear()
        got = jobs.enqueue(_job_marker, 7, job_timeout=99)
        assert got == "queued"
        assert enqueued == [(_job_marker, (7,), 99)]
        assert _job_marker.calls == [], "queued no debe ejecutar en el proceso web"
    finally:
        del sys.modules["rq"]


def test_rq_roto_degrada_a_inline():
    jobs = _load_jobs()

    import types

    class BrokenQueue:
        def __init__(self, *a, **k):
            raise ConnectionError("redis se cayó entre el ping y el enqueue")

    jobs._get_raw_redis = lambda: object()
    fake_rq = types.ModuleType("rq")
    fake_rq.Queue = BrokenQueue
    sys.modules["rq"] = fake_rq
    try:
        _job_marker.calls.clear()
        got = jobs.enqueue(_job_marker, "degradado")
        assert got == "inline-thread"
        for _ in range(50):
            if _job_marker.calls:
                break
            time.sleep(0.05)
        assert _job_marker.calls == ["degradado"], "no degradó al fallar rq"
    finally:
        del sys.modules["rq"]


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
