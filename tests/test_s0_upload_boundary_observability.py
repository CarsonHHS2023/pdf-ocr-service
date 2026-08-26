from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import s0_upload_boundary_observability as upload
from app.models import Base, Document, ProcessingRun, SourceFile, encode_json_text
from app.processing.processing_event_model import ProcessingEvent
from app.processing.processing_events import MAX_EVENT_PAYLOAD_BYTES
from app.processing.s0_baseline import collect_s0_run_snapshot


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


def _baseline_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _baseline_metric(snapshot, key: str):
    for metric in (*snapshot.required_metrics, *snapshot.auxiliary_metrics):
        if metric.key == key:
            return metric
    raise AssertionError(f"metric not found: {key}")


def _upload_payload(*, source_size: int = 456) -> dict[str, object]:
    return {
        "succeeded": True,
        "upload_route": upload.CANONICAL_UPLOAD_ROUTE,
        "measurement_scope": upload.UPLOAD_MEASUREMENT_SCOPE,
        "upload_duration_seconds": 4.25,
        "accepted_source_size_bytes": source_size,
        "http_body_bytes_received": 600,
        "max_asgi_receive_chunk_bytes": 128,
        "uploadfile_read_total_bytes": source_size,
        "max_uploadfile_read_bytes": source_size,
        "memory_component_scope": upload.UPLOAD_MEMORY_COMPONENT_SCOPE,
    }


def _seed_upload_baseline_run(
    db,
    *,
    with_measurement: bool = True,
    payload: dict[str, object] | None = None,
) -> str:
    started = datetime(2026, 8, 26, 8, 5, 0)
    document = Document(
        id=DOCUMENT_ID,
        title="private-title",
        file_type="pdf",
        pages_count=1,
        status="completed",
        created_at=started - timedelta(seconds=6),
        updated_at=started + timedelta(seconds=20),
    )
    source = SourceFile(
        id=SOURCE_FILE_ID,
        document_id=DOCUMENT_ID,
        original_filename="private.pdf",
        file_type="pdf",
        byte_size=456,
        checksum_sha256="c" * 64,
        retained=1,
        is_primary=1,
        created_at=started - timedelta(seconds=2),
    )
    run = ProcessingRun(
        id="upload-baseline-row",
        processing_run_id=RUN_ID,
        document_id=DOCUMENT_ID,
        source_file_id=SOURCE_FILE_ID,
        status="succeeded",
        started_at=started,
        completed_at=started + timedelta(seconds=15),
        created_at=started,
    )
    db.add_all([document, source, run])
    db.flush()
    if with_measurement:
        db.add(
            ProcessingEvent(
                id="upload-measured",
                processing_run_id=RUN_ID,
                document_id=DOCUMENT_ID,
                schema_version="atlas.processing.event.v1",
                event_name=upload.UPLOAD_MEASUREMENT_EVENT,
                severity="info",
                payload_json=encode_json_text(payload or _upload_payload()),
                created_at=started - timedelta(seconds=1),
            )
        )
    db.commit()
    return RUN_ID


def test_collector_promotes_only_strict_canonical_upload_duration() -> None:
    db = _baseline_session()
    run_id = _seed_upload_baseline_run(db)

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)

    duration = _baseline_metric(snapshot, "upload_duration_seconds")
    assert duration.status == "observed"
    assert duration.value == 4.25
    assert upload.UPLOAD_MEASUREMENT_EVENT in duration.source
    assert "canonical multipart" in (duration.note or "").lower()

    body_bytes = _baseline_metric(snapshot, "canonical_upload_http_body_bytes_received")
    assert body_bytes.status == "observed"
    assert body_bytes.value == 600

    max_read = _baseline_metric(snapshot, "canonical_upload_max_uploadfile_read_bytes")
    assert max_read.status == "observed"
    assert max_read.value == 456
    assert "not promoted" in (max_read.note or "").lower()

    memory = _baseline_metric(snapshot, "backend_upload_peak_memory_mb")
    assert memory.status == "not_instrumented"
    assert memory.value is None

    assert upload.UPLOAD_MEASUREMENT_EVENT in snapshot.observed_event_names
    assert set(snapshot.observed_numeric_event_fields) >= {
        "upload_duration_seconds",
        "accepted_source_size_bytes",
        "http_body_bytes_received",
        "max_asgi_receive_chunk_bytes",
        "max_uploadfile_read_bytes",
        "uploadfile_read_total_bytes",
    }


def test_collector_requires_exactly_one_upload_measurement_event() -> None:
    db = _baseline_session()
    run_id = _seed_upload_baseline_run(db)
    started = datetime(2026, 8, 26, 8, 5, 0)
    db.add(
        ProcessingEvent(
            id="upload-measured-duplicate",
            processing_run_id=RUN_ID,
            document_id=DOCUMENT_ID,
            schema_version="atlas.processing.event.v1",
            event_name=upload.UPLOAD_MEASUREMENT_EVENT,
            severity="info",
            payload_json=encode_json_text(_upload_payload()),
            created_at=started - timedelta(milliseconds=500),
        )
    )
    db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)
    duration = _baseline_metric(snapshot, "upload_duration_seconds")
    assert duration.status == "not_available"
    assert duration.value is None
    assert "exactly one" in (duration.note or "").lower()


def test_collector_rejects_wrong_upload_scope_or_source_identity() -> None:
    db = _baseline_session()
    wrong_scope = _upload_payload()
    wrong_scope["measurement_scope"] = "handler_only"
    run_id = _seed_upload_baseline_run(db, payload=wrong_scope)

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)
    duration = _baseline_metric(snapshot, "upload_duration_seconds")
    assert duration.status == "not_available"
    assert "unsupported timing scope" in (duration.note or "").lower()

    event = db.get(ProcessingEvent, "upload-measured")
    assert event is not None
    event.payload_json = encode_json_text(_upload_payload(source_size=455))
    db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)
    duration = _baseline_metric(snapshot, "upload_duration_seconds")
    assert duration.status == "not_available"
    assert "does not match" in (duration.note or "").lower()


def test_collector_rejects_wrong_upload_route_and_memory_component_scope() -> None:
    db = _baseline_session()
    wrong_route = _upload_payload()
    wrong_route["upload_route"] = "direct_object"
    run_id = _seed_upload_baseline_run(db, payload=wrong_route)

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)
    assert _baseline_metric(snapshot, "upload_duration_seconds").status == "not_available"

    event = db.get(ProcessingEvent, "upload-measured")
    assert event is not None
    wrong_memory_scope = _upload_payload()
    wrong_memory_scope["memory_component_scope"] = "process_peak"
    event.payload_json = encode_json_text(wrong_memory_scope)
    db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)
    assert _baseline_metric(snapshot, "upload_duration_seconds").status == "observed"
    max_read = _baseline_metric(snapshot, "canonical_upload_max_uploadfile_read_bytes")
    assert max_read.status == "not_available"
    assert "memory-component scope" in (max_read.note or "").lower()


def test_collector_fails_closed_for_malformed_or_oversized_upload_event() -> None:
    db = _baseline_session()
    run_id = _seed_upload_baseline_run(db)
    event = db.get(ProcessingEvent, "upload-measured")
    assert event is not None
    event.payload_json = "{malformed-json"
    db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)
    assert snapshot.event_payload_decode_incomplete is True
    duration = _baseline_metric(snapshot, "upload_duration_seconds")
    assert duration.status == "not_available"
    assert "could not be inspected" in (duration.note or "").lower()

    event.payload_json = "x" * (MAX_EVENT_PAYLOAD_BYTES + 1)
    db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)
    assert snapshot.event_payload_oversized_incomplete is True
    duration = _baseline_metric(snapshot, "upload_duration_seconds")
    assert duration.status == "not_available"
    assert "could not be inspected" in (duration.note or "").lower()


def test_historical_run_without_upload_event_reports_duration_unavailable() -> None:
    db = _baseline_session()
    run_id = _seed_upload_baseline_run(db, with_measurement=False)

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)
    duration = _baseline_metric(snapshot, "upload_duration_seconds")
    assert duration.status == "not_available"
    assert duration.value is None
    assert _baseline_metric(snapshot, "backend_upload_peak_memory_mb").status == "not_instrumented"
