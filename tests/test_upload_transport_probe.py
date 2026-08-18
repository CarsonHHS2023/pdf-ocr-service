"""Upload-session HTTP boundary observability regressions."""
from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.main import UploadTransportProbeMiddleware


def _messages(log_info) -> list[str]:
    return [call.args[0] % call.args[1:] for call in log_info.call_args_list]


def _probe_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://carsonhhs2023.github.io"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(UploadTransportProbeMiddleware)

    @app.post("/api/v1/upload-sessions/test/chunks/1/multipart")
    async def receive_chunk(request: Request) -> dict:
        body = await request.body()
        return {"received_bytes": len(body)}

    return app


def test_upload_transport_probe_observes_cors_preflight_before_route():
    app = _probe_app()
    with TestClient(app) as client, patch("app.main.logger.info") as log_info:
        response = client.options(
            "/api/v1/upload-sessions/test/chunks/1/multipart",
            headers={
                "Origin": "https://carsonhhs2023.github.io",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization",
            },
        )

    assert response.status_code == 200
    messages = _messages(log_info)
    entered = next(message for message in messages if message.startswith("RESUMABLE_UPLOAD_HTTP_ENTERED"))
    completed = next(message for message in messages if message.startswith("RESUMABLE_UPLOAD_HTTP_COMPLETED"))
    assert "method=OPTIONS" in entered
    assert "origin=https://carsonhhs2023.github.io" in entered
    assert "access_control_request_method=POST" in entered
    assert "access_control_request_headers=authorization" in entered
    assert "authorization_present=False" in entered
    assert "status=200" in completed
    assert "elapsed_ms=" in completed


def test_upload_transport_probe_does_not_consume_post_body_or_log_token_value():
    app = _probe_app()
    secret_token = "secret-token-that-must-not-appear"
    with TestClient(app) as client, patch("app.main.logger.info") as log_info:
        response = client.post(
            "/api/v1/upload-sessions/test/chunks/1/multipart",
            content=b"abcd",
            headers={
                "Origin": "https://carsonhhs2023.github.io",
                "Authorization": f"Bearer {secret_token}",
                "Content-Type": "application/octet-stream",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"received_bytes": 4}
    messages = _messages(log_info)
    entered = next(message for message in messages if message.startswith("RESUMABLE_UPLOAD_HTTP_ENTERED"))
    completed = next(message for message in messages if message.startswith("RESUMABLE_UPLOAD_HTTP_COMPLETED"))
    assert "method=POST" in entered
    assert "authorization_present=True" in entered
    assert "content_length=4" in entered
    assert secret_token not in "\n".join(messages)
    assert "status=200" in completed
