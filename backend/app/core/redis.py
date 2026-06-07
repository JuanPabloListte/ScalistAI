"""Cliente Redis lazy con fallback en memoria.

Garantiza que la app arranque aunque Redis no esté disponible (útil en
entornos de desarrollo sin docker-compose). En producción Redis siempre
está levantado — el fallback solo cubre errores transitorios.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_client = None
_client_lock = threading.Lock()


def get_redis():
    """Devuelve el cliente Redis. Crea la conexión en el primer llamado (lazy).

    Retorna None si Redis no está disponible — los llamadores deben manejar
    este caso con el fallback en memoria.
    """
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is not None:
            return _client
        try:
            import redis

            c = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            c.ping()
            _client = c
            logger.info("Redis conectado en %s:%s", settings.REDIS_HOST, settings.REDIS_PORT)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Redis no disponible (%s) — usando fallback en memoria. "
                "El estado del pipeline AI no será compartido entre workers.",
                exc,
            )
            _client = None
    return _client


def reset_client() -> None:
    """Fuerza reconexión en el próximo get_redis(). Útil en tests."""
    global _client
    with _client_lock:
        _client = None
