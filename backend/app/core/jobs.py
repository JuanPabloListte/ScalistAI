"""Cola de trabajos pesados (rq sobre el Redis existente) con fallback in-process.

El procesamiento pesado (IFC de cientos de MB, import vectorial de PDF,
detección ML) NO debe correr dentro del worker web: satura CPU/memoria del
proceso que atiende requests, y bajo presión de memoria la geometría de
IfcOpenShell llegó a corromperse en silencio (plan con 8 de 92 muros).
Estos trabajos van al contenedor `worker` (rq) que consume de Redis.

Diseño:
- `enqueue(func, *args)` encola en rq si Redis + rq están disponibles.
- Fallback: sin Redis (dev pelado) o sin rq instalado, ejecuta como siempre
  (BackgroundTasks del request o thread daemon) — degradación elegante, el
  producto nunca se rompe por infraestructura faltante.
- Las funciones encoladas deben ser importables por path (rq las resuelve como
  "modulo.funcion" en el worker) y abrir su propia sesión de DB (SessionLocal),
  como ya hacen process_ifc / try_vector_import / run_initial_detection.
- rq necesita una conexión de bytes crudos (decode_responses=False), distinta
  del cliente de app.core.redis (que decodifica strings para el estado del
  pipeline). Acá se mantiene una conexión propia.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

QUEUE_NAME = "scalist-jobs"
# Un IFC de 200+ MB o una lámina A0 con miles de entidades puede tardar
# varios minutos; el default de rq (180 s) mataría el job a mitad de camino.
_DEFAULT_JOB_TIMEOUT = 3600

_raw_client = None
_raw_lock = threading.Lock()


def _get_raw_redis():
    """Conexión Redis en bytes crudos para rq (lazy, None si no hay Redis)."""
    global _raw_client
    if _raw_client is not None:
        return _raw_client
    with _raw_lock:
        if _raw_client is not None:
            return _raw_client
        try:
            import redis

            c = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                decode_responses=False,  # rq serializa en bytes (pickle)
                socket_connect_timeout=2,
                socket_timeout=5,
            )
            c.ping()
            _raw_client = c
        except Exception as exc:  # noqa: BLE001
            logger.warning("jobs: Redis no disponible (%s) — fallback in-process", exc)
            _raw_client = None
    return _raw_client


def enqueue(
    func: Callable[..., Any],
    *args: Any,
    background_tasks: Optional[Any] = None,
    job_timeout: int = _DEFAULT_JOB_TIMEOUT,
) -> str:
    """Manda `func(*args)` al worker. Devuelve cómo quedó despachado:
    "queued" (worker rq) | "inline-background" | "inline-thread" (fallback).

    `background_tasks`: el BackgroundTasks del request, usado SOLO como
    fallback para conservar el comportamiento previo si no hay cola.
    """
    r = _get_raw_redis()
    if r is not None:
        try:
            from rq import Queue

            Queue(QUEUE_NAME, connection=r).enqueue(func, *args, job_timeout=job_timeout)
            logger.info("job encolado: %s%r", getattr(func, "__name__", func), args)
            return "queued"
        except Exception as exc:  # noqa: BLE001
            logger.warning("jobs: rq falló (%s) — ejecutando in-process", exc)

    if background_tasks is not None:
        background_tasks.add_task(func, *args)
        return "inline-background"
    threading.Thread(
        target=func, args=args, daemon=True,
        name=f"job-{getattr(func, '__name__', 'fn')}",
    ).start()
    return "inline-thread"


def reset_client() -> None:
    """Fuerza reconexión en el próximo enqueue(). Útil en tests."""
    global _raw_client
    with _raw_lock:
        _raw_client = None
