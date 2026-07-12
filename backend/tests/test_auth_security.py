"""Tests de JWT fail-fast y rate limit de login (sin DB)."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))


def _reload_auth_security(env: str = "development", secret: str = "change-me",
                          limit: int = 3, window: int = 60):
    """Recarga el módulo con settings mockeados."""
    import app.core.config as config_mod

    config_mod.settings = SimpleNamespace(
        JWT_SECRET=secret,
        ENVIRONMENT=env,
        is_production=(env.strip().lower() in ("production", "prod")),
        LOGIN_RATE_LIMIT_MAX=limit,
        LOGIN_RATE_LIMIT_WINDOW_SECONDS=window,
    )
    # auth_security importa settings al usarlo; forzar reimport limpio
    if "app.core.auth_security" in sys.modules:
        del sys.modules["app.core.auth_security"]
    return importlib.import_module("app.core.auth_security")


def test_jwt_secret_weak_detection():
    sec = _reload_auth_security(secret="change-me")
    assert sec.jwt_secret_is_weak("change-me") is True
    assert sec.jwt_secret_is_weak("short") is True
    assert sec.jwt_secret_is_weak("a" * 32) is False
    assert sec.jwt_secret_is_weak("x" * 40) is False


def test_validate_jwt_aborts_in_production():
    sec = _reload_auth_security(env="production", secret="change-me")
    try:
        sec.validate_jwt_secret_on_startup()
        assert False, "debía abortar"
    except RuntimeError as exc:
        assert "JWT_SECRET" in str(exc)


def test_validate_jwt_warns_in_dev():
    sec = _reload_auth_security(env="development", secret="change-me")
    sec.validate_jwt_secret_on_startup()  # no raises


def test_validate_jwt_ok_strong_secret_in_prod():
    strong = "prod-secret-" + ("x" * 40)
    sec = _reload_auth_security(env="production", secret=strong)
    sec.validate_jwt_secret_on_startup()


def test_login_rate_limit_memory_fallback():
    sec = _reload_auth_security(limit=3, window=60)
    # Forzar sin Redis
    with patch.object(sec, "get_redis", return_value=None):
        sec._memory_hits.clear()
        req = MagicMock()
        req.headers.get.return_value = None
        req.client.host = "203.0.113.10"

        for _ in range(3):
            sec.enforce_login_rate_limit(req, "a@b.com")

        try:
            sec.enforce_login_rate_limit(req, "a@b.com")
            assert False, "debía ser 429"
        except Exception as exc:
            from fastapi import HTTPException
            assert isinstance(exc, HTTPException)
            assert exc.status_code == 429

        sec.clear_login_rate_limit(req, "a@b.com")
        sec.enforce_login_rate_limit(req, "a@b.com")  # ok tras clear


def test_client_ip_from_forwarded_for():
    sec = _reload_auth_security()
    req = MagicMock()
    req.headers.get.return_value = "198.51.100.7, 10.0.0.1"
    assert sec.client_ip(req) == "198.51.100.7"


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok    {name}")
            except AssertionError as exc:
                failed += 1
                print(f"  FAIL  {name}: {exc}")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"  ERROR {name}: {exc}")
    total = sum(1 for n, f in globals().items() if n.startswith("test_") and callable(f))
    print(f"\n{total - failed}/{total} tests pasaron")
    sys.exit(1 if failed else 0)
