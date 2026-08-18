"""Tests for the temporary shared development access gate."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.access_middleware import AppAccessGateMiddleware
from app.access_security import (
    ACCESS_ENABLED_ENV,
    ACCESS_PASSWORD_HASH_ENV,
    ACCESS_TOKEN_SECRET_ENV,
    ACCESS_TOKEN_TTL_ENV,
    AccessConfigurationError,
    AccessTokenError,
    access_token_ttl_seconds,
    hash_password,
    issue_access_token,
    verify_access_token,
)
from app.routers.access import router as access_router

_PASSWORD = "correct horse battery staple"
_TEST_SECRET = "test-token-secret-0123456789abcdefghijklmnopqrstuvwxyz"


@pytest.fixture(autouse=True)
def _clear_access_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        ACCESS_ENABLED_ENV,
        ACCESS_PASSWORD_HASH_ENV,
        ACCESS_TOKEN_SECRET_ENV,
        ACCESS_TOKEN_TTL_ENV,
    ):
        monkeypatch.delenv(name, raising=False)


def _configure_access(monkeypatch: pytest.MonkeyPatch) -> None:
    encoded_hash = hash_password(
        _PASSWORD,
        iterations=100_000,
        salt=b"0123456789abcdef",
    )
    monkeypatch.setenv(ACCESS_ENABLED_ENV, "true")
    monkeypatch.setenv(ACCESS_PASSWORD_HASH_ENV, encoded_hash)
    monkeypatch.setenv(ACCESS_TOKEN_SECRET_ENV, _TEST_SECRET)


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(AppAccessGateMiddleware)
    app.include_router(access_router)

    @app.get("/")
    async def root() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/v1/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/v1/health/database-recovery-cutover")
    async def recovery_cutover_health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/internal/example")
    async def internal() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/private")
    async def private() -> dict[str, bool]:
        return {"ok": True}

    return app


def test_gate_is_disabled_by_default() -> None:
    client = TestClient(_build_app())
    assert client.get("/private").status_code == 200


def test_enabled_gate_rejects_missing_and_bad_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_access(monkeypatch)
    client = TestClient(_build_app())

    missing = client.get("/private")
    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"

    bad = client.get("/private", headers={"Authorization": "Bearer not-a-token"})
    assert bad.status_code == 401


def test_public_and_internal_routes_bypass_shared_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_access(monkeypatch)
    client = TestClient(_build_app())

    assert client.get("/").status_code == 200
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/health/database-recovery-cutover").status_code == 200
    assert client.get("/internal/example").status_code == 200


def test_login_issues_token_that_unlocks_private_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_access(monkeypatch)
    client = TestClient(_build_app())

    response = client.post("/api/access/login", json={"password": _PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 12 * 60 * 60

    private = client.get(
        "/private",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert private.status_code == 200


def test_login_rejects_wrong_password(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_access(monkeypatch)
    client = TestClient(_build_app())

    response = client.post(
        "/api/access/login",
        json={"password": "wrong-password-value"},
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid credentials"}


def test_login_fails_closed_when_token_secret_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_access(monkeypatch)
    monkeypatch.delenv(ACCESS_TOKEN_SECRET_ENV)
    client = TestClient(_build_app())

    response = client.post("/api/access/login", json={"password": _PASSWORD})
    assert response.status_code == 503
    assert response.json() == {"detail": "Application access is not configured"}


def test_expired_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_access(monkeypatch)
    token, ttl = issue_access_token(now=1_000_000)
    assert ttl == access_token_ttl_seconds()

    with pytest.raises(AccessTokenError, match="expired"):
        verify_access_token(token, now=1_000_000 + ttl + 1)


def test_malformed_unicode_token_is_rejected_without_server_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_access(monkeypatch)
    with pytest.raises(AccessTokenError, match="invalid"):
        verify_access_token("é.payload.signature")


def test_ttl_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_access(monkeypatch)
    monkeypatch.setenv(ACCESS_TOKEN_TTL_ENV, "60")

    with pytest.raises(AccessConfigurationError, match="between 300 and 86400"):
        access_token_ttl_seconds()
