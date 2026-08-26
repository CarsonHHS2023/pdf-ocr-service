from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import s0_provider_source_download_observability as download
from app import s0_transport_download_observability as transport
from app.models import Base, Document, ProcessingRun, SourceFile, encode_json_text
from app.processing.processing_event_model import ProcessingEvent
from app.processing.s0_baseline import collect_s0_run_snapshot

RUN_ID = "pdf-ingest-" + "7" * 32
DOCUMENT_ID = "33333333-3333-4333-8333-333333333333"
SOURCE_FILE_ID = "44444444-4444-4444-8444-444444444444"
SCOPE_A = "transport_0123456789abcdef"
SCOPE_B = "transport_fedcba9876543210"
PROVIDER_A = "provider_1111111111111111"
PROVIDER_B = "provider_2222222222222222"


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _event(event_id, name, payload, second):
    return ProcessingEvent(
        id=event_id,
        processing_run_id=RUN_ID,
        document_id=DOCUMENT_ID,
        schema_version="atlas.processing.event.v1",
        event_name=name,
        severity="info",
        payload_json=encode_json_text(payload),
        created_at=datetime(2026, 8, 26, 13, 0, second),
    )


def _seed_base(db):
    started = datetime(2026, 8, 26, 13, 0, 0)
    db.add(Document(id=DOCUMENT_ID, title="private", file_type="pdf", pages_count=1, status="completed", created_at=started, updated_at=started))
    db.add(SourceFile(id=SOURCE_FILE_ID, document_id=DOCUMENT_ID, original_filename="private.pdf", file_type="pdf", byte_size=100, checksum_sha256="e" * 64, retained=1, is_primary=1, created_at=started))
    db.add(ProcessingRun(id="row-download", processing_run_id=RUN_ID, document_id=DOCUMENT_ID, source_file_id=SOURCE_FILE_ID, status="succeeded", started_at=started, completed_at=started + timedelta(seconds=10), created_at=started))
    db.add(_event("provider", "PDF_S0_PROVIDER_INTEGRATION_MEASURED", {"succeeded": True, "elapsed_seconds": 5.0}, 1))
    db.commit()


def _decision(required, selected, second=2):
    return _event("decision", "PDF_PROVIDER_TRANSPORT_SHARDING_DECISION", {
        "succeeded": True,
        "sharding_required": required,
        "provider_input_size_bytes": selected,
    }, second)


def _route(scope, route, size, event_id, second):
    return _event(event_id, transport.SOURCE_ROUTE_EVENT, {
        "succeeded": True,
        "measurement_scope": transport.TRANSPORT_MEASUREMENT_SCOPE,
        "stage": transport.TRANSPORT_STAGE,
        "scope_id": scope,
        "route": route,
        "source_object_size_bytes": size,
    }, second)


def _terminal(scope, count, event_id, second):
    return _event(event_id, "S0_OBJECT_STORE_TRANSPORT_SCOPE_TERMINAL", {
        "succeeded": True,
        "measurement_scope": "backend_storage_provider_logical_io_v1",
        "stage": "provider_source_transport",
        "scope_id": scope,
        "terminal_retrieval_count": count,
    }, second)


def _body(scope, ordinal, size, event_id, second):
    return _event(event_id, transport.BACKEND_BODY_EVENT, {
        "succeeded": True,
        "measurement_scope": transport.TRANSPORT_MEASUREMENT_SCOPE,
        "stage": transport.TRANSPORT_STAGE,
        "scope_id": scope,
        "scope_ordinal": ordinal,
        "route": transport.ROUTE_FALLBACK,
        "body_bytes": size,
        "body_messages": 1,
    }, second)


def _download(scope, size, duration, event_id, second):
    return _event(event_id, download.PROVIDER_DOWNLOAD_EVENT, {
        "succeeded": True,
        "measurement_scope": download.PROVIDER_DOWNLOAD_MEASUREMENT_SCOPE,
        "provider_scope_id": scope,
        "download_bytes": size,
        "download_duration_seconds": duration,
    }, second)


def _metric(snapshot, key):
    return next(item for item in snapshot.required_metrics if item.key == key)


def _aux(snapshot, key):
    return next(item for item in snapshot.auxiliary_metrics if item.key == key)


def test_two_presigned_shards_close_consumer_bytes_and_duration_without_order_guessing() -> None:
    db = _session(); _seed_base(db)
    db.add_all([
        _decision(True, 280),
        _event("sharding-terminal", "PDF_PROVIDER_TRANSPORT_SHARDING_TERMINAL", {"succeeded": True, "shard_count": 2}, 3),
        _route(SCOPE_A, transport.ROUTE_PRESIGNED, 200, "route-a", 4),
        _route(SCOPE_B, transport.ROUTE_PRESIGNED, 81, "route-b", 5),
        _terminal(SCOPE_A, 0, "terminal-a", 6),
        _terminal(SCOPE_B, 0, "terminal-b", 7),
        # Deliberately reverse byte order relative to transport scopes.
        _download(PROVIDER_A, 81, 0.2, "download-a", 8),
        _download(PROVIDER_B, 200, 0.1, "download-b", 9),
    ]); db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=RUN_ID)
    backend = _metric(snapshot, "backend_to_modal_transport_bytes")
    modal = _metric(snapshot, "modal_download_seconds")
    byte_aux = _aux(snapshot, "provider_source_download_bytes")
    breakdown = _aux(snapshot, "provider_source_download_breakdown")

    assert backend.status == "observed" and backend.value == 0
    assert modal.status == "observed" and modal.value == 0.3
    assert byte_aux.status == "observed" and byte_aux.value == 281
    assert breakdown.status == "observed"
    assert breakdown.value["download_total_bytes"] == 281
    assert breakdown.value["download_operation_seconds_sum"] == 0.3
    assert len(breakdown.value["downloads"]) == 2


def test_fallback_keeps_backend_send_bytes_separate_from_provider_download_bytes() -> None:
    db = _session(); _seed_base(db)
    db.add_all([
        _decision(False, 120),
        _route(SCOPE_A, transport.ROUTE_FALLBACK, 120, "route", 3),
        _body(SCOPE_A, 1, 120, "body", 4),
        _terminal(SCOPE_A, 1, "terminal", 5),
        _download(PROVIDER_A, 120, 0.4, "download", 6),
    ]); db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=RUN_ID)
    assert _metric(snapshot, "backend_to_modal_transport_bytes").value == 120
    assert _metric(snapshot, "modal_download_seconds").value == 0.4
    assert _aux(snapshot, "provider_source_download_bytes").value == 120


def test_consumer_byte_mismatch_fails_closed_without_invalidating_backend_boundary() -> None:
    db = _session(); _seed_base(db)
    db.add_all([
        _decision(False, 120),
        _route(SCOPE_A, transport.ROUTE_PRESIGNED, 120, "route", 3),
        _terminal(SCOPE_A, 0, "terminal", 4),
        _download(PROVIDER_A, 119, 0.2, "download", 5),
    ]); db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=RUN_ID)
    assert _metric(snapshot, "backend_to_modal_transport_bytes").status == "observed"
    modal = _metric(snapshot, "modal_download_seconds")
    assert modal.status == "not_available"
    assert "byte" in (modal.note or "").lower()
    assert _aux(snapshot, "provider_source_download_bytes").status == "not_available"


def test_duplicate_provider_scope_fails_closed() -> None:
    db = _session(); _seed_base(db)
    db.add_all([
        _decision(True, 280),
        _event("sharding-terminal", "PDF_PROVIDER_TRANSPORT_SHARDING_TERMINAL", {"succeeded": True, "shard_count": 2}, 3),
        _route(SCOPE_A, transport.ROUTE_PRESIGNED, 200, "route-a", 4),
        _route(SCOPE_B, transport.ROUTE_PRESIGNED, 81, "route-b", 5),
        _terminal(SCOPE_A, 0, "terminal-a", 6),
        _terminal(SCOPE_B, 0, "terminal-b", 7),
        _download(PROVIDER_A, 200, 0.1, "download-a", 8),
        _download(PROVIDER_A, 81, 0.2, "download-b", 9),
    ]); db.commit()

    modal = _metric(collect_s0_run_snapshot(db, processing_run_id=RUN_ID), "modal_download_seconds")
    assert modal.status == "not_available"
    assert "Duplicate Provider" in (modal.note or "")


def test_malformed_same_name_provider_download_event_fails_closed() -> None:
    db = _session(); _seed_base(db)
    db.add_all([
        _decision(False, 120),
        _route(SCOPE_A, transport.ROUTE_PRESIGNED, 120, "route", 3),
        _terminal(SCOPE_A, 0, "terminal", 4),
        _download(PROVIDER_A, 120, 0.2, "download", 5),
        ProcessingEvent(
            id="malformed-download",
            processing_run_id=RUN_ID,
            document_id=DOCUMENT_ID,
            schema_version="atlas.processing.event.v1",
            event_name=download.PROVIDER_DOWNLOAD_EVENT,
            severity="info",
            payload_json="{",
            created_at=datetime(2026, 8, 26, 13, 0, 6),
        ),
    ]); db.commit()

    modal = _metric(collect_s0_run_snapshot(db, processing_run_id=RUN_ID), "modal_download_seconds")
    assert modal.status == "not_available"
    assert "could not be inspected" in (modal.note or "")


def test_result_projection_records_only_privacy_safe_provider_download_fields(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(download, "_enabled", lambda: True)
    import app.processing.processing_events as processing_events
    monkeypatch.setattr(
        processing_events,
        "record_processing_event",
        lambda **kwargs: calls.append(kwargs) or True,
    )
    request = SimpleNamespace(
        processing_attempt_id=RUN_ID,
        document_id=DOCUMENT_ID,
        provider_job_id="job-private-123",
    )
    result = SimpleNamespace(raw_provider_payload={
        "documents": [{
            "document_id": DOCUMENT_ID,
            "source_download": {
                "succeeded": True,
                "measurement_scope": download.PROVIDER_DOWNLOAD_MEASUREMENT_SCOPE,
                "bytes": 456,
                "duration_seconds": 0.3333333,
                "url": "https://storage.example.com/source.pdf?sig=secret",
                "token": "private-token",
            },
        }]
    })

    assert download.record_provider_source_download_from_result(request, result) is True
    assert len(calls) == 1
    payload = calls[0]["payload"]
    assert payload == {
        "succeeded": True,
        "measurement_scope": download.PROVIDER_DOWNLOAD_MEASUREMENT_SCOPE,
        "provider_scope_id": download.provider_scope_id("job-private-123"),
        "download_bytes": 456,
        "download_duration_seconds": 0.333333,
    }
    rendered = repr(calls[0])
    assert "storage.example.com" not in rendered
    assert "secret" not in rendered
    assert "private-token" not in rendered
