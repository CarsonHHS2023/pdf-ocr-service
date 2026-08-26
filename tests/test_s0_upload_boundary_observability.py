from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app import s0_upload_boundary_observability as upload


RUN_ID = "pdf-ingest-" + "a" * 32
DOCUMENT_ID = "document-upload-boundary"
SOURCE_FILE_ID = "source-upload-boundary"


def _pdf_background_task(*args, **kwargs):
    return None


_pdf_background_task.__module__ = "app.processing.pdf_ingestion"
_pdf_background_task.__name__ = "process_pdf_document_background"


def test_canonical_request_measures_ingress_through_durable_acceptance(monkeypatch) -> None:
    recorded: list[dict[str, object]] = []
    diagnostics: list[tuple[str, dict[str, object]]] = []
    clock = iter((10.0, 12.5))
    monkeypatch.setattr(upload, "perf_counter", lambda: next(clock))
    monkeypatch.setattr(upload, "_load_accepted_source_size", lambda source_id: 120)
    monkeypatch.setattr(
        upload,
        "_record_success",
        lambda **kwargs: recorded.append(dict(kwargs)) or True,
    )
    monkeypatch.setattr(
        upload,
        "_diagnostic",
        lambda event, **fields: diagnostics.append((event, dict(fields))),
    )

    receive_messages = iter(
        (
            {"type": "http.request", "body": b"a" * 100, "more_body": True},
            {"type": "http.request", "body": b"b" * 50, "more_body": False},
        )
    )
    sent: list[dict[str, object]] = []

    async def receive():
        return next(receive_messages)

    async def send(message):
        sent.append(dict(message))

    async def read_delegate(file_self, *args, **kwargs):
        return b"x" * 120

    read = upload._wrap_uploadfile_read(read_delegate)

    def add_delegate(background_self, func, *args, **kwargs):
        return "queued"

    add_task = upload._wrap_background_add_task(add_delegate)

    async def app_delegate(app_self, scope, observed_receive, observed_send):
        await observed_receive()
        await observed_receive()
        assert await read(object()) == b"x" * 120
        ids = SimpleNamespace(processing_attempt_id=RUN_ID)
        assert (
            add_task(
                object(),
                _pdf_background_task,
                DOCUMENT_ID,
                SOURCE_FILE_ID,
                ids,
            )
            == "queued"
        )
        await observed_send({"type": "http.response.start", "status": 200})
        await observed_send({"type": "http.response.body", "body": b"{}"})
        return "response"

    wrapped_app = upload._wrap_fastapi_call(app_delegate)
    result = asyncio.run(
        wrapped_app(
            object(),
            {"type": "http", "path": upload.CANONICAL_UPLOAD_PATH},
            receive,
            send,
        )
    )

    assert result == "response"
    assert len(recorded) == 1
    event = recorded[0]
    assert event["processing_run_id"] == RUN_ID
    assert event["document_id"] == DOCUMENT_ID
    fields = event["fields"]
    assert fields["succeeded"] is True
    assert fields["upload_route"] == upload.CANONICAL_UPLOAD_ROUTE
    assert fields["measurement_scope"] == upload.UPLOAD_MEASUREMENT_SCOPE
    assert fields["upload_duration_seconds"] == 2.5
    assert fields["accepted_source_size_bytes"] == 120
    assert fields["http_body_bytes_received"] == 150
    assert fields["max_asgi_receive_chunk_bytes"] == 100
    assert fields["uploadfile_read_total_bytes"] == 120
    assert fields["max_uploadfile_read_bytes"] == 120
    assert fields["memory_component_scope"] == upload.UPLOAD_MEMORY_COMPONENT_SCOPE
    assert "backend_upload_peak_memory_mb" not in fields
    assert "peak_rss_mb" not in fields
    assert diagnostics == []


def test_noncanonical_route_is_not_measured(monkeypatch) -> None:
    recorded: list[dict[str, object]] = []
    monkeypatch.setattr(
        upload,
        "_record_success",
        lambda **kwargs: recorded.append(dict(kwargs)) or True,
    )

    async def app_delegate(app_self, scope, receive, send):
        assert upload._CURRENT_UPLOAD.get() is None
        return "ok"

    wrapped = upload._wrap_fastapi_call(app_delegate)

    async def receive():
        return {"type": "http.request", "body": b"chunk", "more_body": False}

    async def send(message):
        return None

    assert (
        asyncio.run(
            wrapped(
                object(),
                {"type": "http", "path": "/api/v1/upload-sessions/session/chunks/0"},
                receive,
                send,
            )
        )
        == "ok"
    )
    assert recorded == []


def test_background_task_without_canonical_context_cannot_create_measurement(monkeypatch) -> None:
    recorded: list[dict[str, object]] = []
    monkeypatch.setattr(
        upload,
        "_record_success",
        lambda **kwargs: recorded.append(dict(kwargs)) or True,
    )

    def add_delegate(background_self, func, *args, **kwargs):
        return None

    wrapped = upload._wrap_background_add_task(add_delegate)
    wrapped(
        object(),
        _pdf_background_task,
        DOCUMENT_ID,
        SOURCE_FILE_ID,
        SimpleNamespace(processing_attempt_id=RUN_ID),
    )
    assert recorded == []


def test_failed_request_emits_bounded_diagnostic_without_completed_duration(monkeypatch) -> None:
    diagnostics: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(upload, "perf_counter", lambda: 20.0)
    monkeypatch.setattr(
        upload,
        "_diagnostic",
        lambda event, **fields: diagnostics.append((event, dict(fields))),
    )

    async def app_delegate(app_self, scope, receive, send):
        await receive()
        raise RuntimeError("upload failed")

    wrapped = upload._wrap_fastapi_call(app_delegate)

    async def receive():
        return {"type": "http.request", "body": b"abc", "more_body": False}

    async def send(message):
        return None

    with pytest.raises(RuntimeError, match="upload failed"):
        asyncio.run(
            wrapped(
                object(),
                {"type": "http", "path": upload.CANONICAL_UPLOAD_PATH},
                receive,
                send,
            )
        )

    assert len(diagnostics) == 1
    event, fields = diagnostics[0]
    assert event == "S0_UPLOAD_REQUEST_FAILED"
    assert fields["upload_route"] == upload.CANONICAL_UPLOAD_ROUTE
    assert fields["error_type"] == "RuntimeError"
    assert fields["http_body_bytes_received"] == 3
    assert "upload_duration_seconds" not in fields
    assert "filename" not in fields
    assert "document_id" not in fields


def test_unaccepted_completed_request_does_not_fabricate_upload_duration(monkeypatch) -> None:
    diagnostics: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(upload, "perf_counter", lambda: 30.0)
    monkeypatch.setattr(
        upload,
        "_diagnostic",
        lambda event, **fields: diagnostics.append((event, dict(fields))),
    )

    async def app_delegate(app_self, scope, receive, send):
        await receive()
        await send({"type": "http.response.start", "status": 413})
        await send({"type": "http.response.body", "body": b"rejected"})
        return None

    wrapped = upload._wrap_fastapi_call(app_delegate)

    async def receive():
        return {"type": "http.request", "body": b"abcde", "more_body": False}

    async def send(message):
        return None

    asyncio.run(
        wrapped(
            object(),
            {"type": "http", "path": upload.CANONICAL_UPLOAD_PATH},
            receive,
            send,
        )
    )

    assert len(diagnostics) == 1
    event, fields = diagnostics[0]
    assert event == "S0_UPLOAD_REQUEST_NOT_ACCEPTED"
    assert fields["http_status_code"] == 413
    assert fields["http_body_bytes_received"] == 5
    assert "upload_duration_seconds" not in fields


def test_txt_background_identity_is_supported() -> None:
    def txt_task(*args, **kwargs):
        return None

    txt_task.__module__ = "app.processing.txt.ingestion"
    txt_task.__name__ = "process_txt_document_background"
    identity = upload._background_identity(
        txt_task,
        (
            DOCUMENT_ID,
            SOURCE_FILE_ID,
            SimpleNamespace(processing_run_ref="txt-ingest-" + "b" * 32),
        ),
        {},
    )
    assert identity == ("txt-ingest-" + "b" * 32, DOCUMENT_ID, SOURCE_FILE_ID)


def test_installer_is_noop_when_staging_runtime_gate_is_closed(monkeypatch) -> None:
    monkeypatch.setattr(upload, "_INSTALLED", False)
    monkeypatch.setattr(upload, "staging_upload_observability_enabled", lambda: False)
    assert upload.install_s0_upload_boundary_observability() is False
    assert upload._INSTALLED is False
