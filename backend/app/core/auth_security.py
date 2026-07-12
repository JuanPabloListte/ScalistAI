"""Validación de secretos y rate limit de login."""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict

from fastapi import HTTPException, Request

from app.core.config import settings
from app.core.redis import get_redis

logger = logging.getLogger(__name__)

_WEAK_JWT_SECRETS = frozenset({
    "",
    "change-me",
    "change-me-in-production-please",
    "secret",
    "jwt-secret",
    "jwt_secret",
    "scalistai",
    "dev",
    "development",
})

# Fallback in-memory: {key: [timestamps]}
_memory_hits: dict[str, list[float]] = defaultdict(list)
_memory_lock = threading.Lock()


def jwt_secret_is_weak(secret: str | None = None) -> bool:
    s = (secret if secret is not None else settings.JWT_SECRET) or ""
    if s.strip().lower() in _WEAK_JWT_SECRETS:
        return True
    if len(s) < 32:
        return True
    return False


def validate_jwt_secret_on_startup() -> None:
    """Fail-fast en producción si JWT_SECRET es inseguro; warning en dev."""
    if not jwt_secret_is_weak():
        return
    msg = (
        "JWT_SECRET inseguro (default, vacío o < 32 caracteres). "
        "Definí un secreto largo y aleatorio en el entorno "
        "(p.ej. `openssl rand -hex 32`)."
    )
    if settings.is_production:
        logger.critical("startup ABORT: %s", msg)
        raise RuntimeError(msg)
    logger.warning("startup: %s (ENVIRONMENT=%s — se permite solo en no-prod)",
                   msg, settings.ENVIRONMENT)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _memory_hit(key: str, window: int, limit: int) -> int:
    now = time.monotonic()
    with _memory_lock:
        hits = [t for t in _memory_hits[key] if now - t < window]
        hits.append(now)
        _memory_hits[key] = hits
        return len(hits)


def _memory_clear(key: str) -> None:
    with _memory_lock:
        _memory_hits.pop(key, None)


def enforce_login_rate_limit(request: Request, email: str) -> None:
    """Cuenta intentos de login por IP y por email. Si supera el tope → HTTP 429."""
    limit = settings.LOGIN_RATE_LIMIT_MAX
    window = settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS
    if limit <= 0:
        return

    ip = client_ip(request)
    keys = [f"login_rl:ip:{ip}"]
    em = (email or "").strip().lower()[:128]
    if em:
        keys.append(f"login_rl:em:{em}")

    for key in keys:
        _hit_or_raise(key, limit, window)


def _hit_or_raise(key: str, limit: int, window: int) -> None:
    r = get_redis()
    if r is not None:
        try:
            count = int(r.incr(key))
            if count == 1:
                r.expire(key, window)
        except Exception as exc:  # noqa: BLE001
            logger.warning("rate limit Redis falló (%s) — fallback memoria", exc)
            count = _memory_hit(key, window, limit)
    else:
        count = _memory_hit(key, window, limit)

    if count > limit:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Demasiados intentos de login. "
                f"Esperá {window} segundos e intentá de nuevo."
            ),
            headers={"Retry-After": str(window)},
        )


def clear_login_rate_limit(request: Request, email: str = "") -> None:
    """Tras login exitoso, limpia contadores de esa IP/email."""
    ip = client_ip(request)
    keys = [f"login_rl:ip:{ip}"]
    em = (email or "").strip().lower()[:128]
    if em:
        keys.append(f"login_rl:em:{em}")
    r = get_redis()
    for key in keys:
        if r is not None:
            try:
                r.delete(key)
            except Exception:  # noqa: BLE001
                pass
        _memory_clear(key)
