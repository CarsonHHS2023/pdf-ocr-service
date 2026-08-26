from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import s0_transport_download_observability as transport
from app.models import Base, Document, ProcessingRun, SourceFile, encode_json_text
from app.processing.processing_event_model import ProcessingEvent
from app.processing.s0_baseline import collect_s0_run_snapshot

RUN_ID = "pdf-ingest-" + "8" * 32
DOCUMENT_ID = "11111111-1111-4111-8111-111111111111"
SOURCE_FILE_ID = "22222222-2222-4222-8222-222222222222"
SCOPE_A = "transport_0123456789abcdef"
SCOPE_B = "transport_fedcba9876543210"


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
        created_at=datetime(2026, 8, 26, 12, 0, second),
    )


def _seed_base(db):
    started = datetime(2026, 8, 26, 12, 0, 0)
    db.add(Document(id=DOCUMENT_ID, title="private", file_type="pdf", pages_count=1, status="completed", created_at=started, updated_at=started))
    db.add(SourceFile(id=SOURCE_FILE_ID, document_id=DOCUMENT_ID, original_filename="private.pdf", file_type="pdf", byte_size=100, checksum_sha256="d" * 64, retained=1, is_primary=1, created_at=started))
    db.add(ProcessingRun(id="row", processing_run_id=RUN_ID, document_id=DOCUMENT_ID, source_file_id=SOURCE_FILE_ID, status="succeeded", started_at=started, completed_at=started + timedelta(seconds=10), created_at=started))
    db.add(_event("provider", "PDF_S0_PROVIDER_INTEGRATION_MEASURED", {"succeeded": True, "elapsed_seconds": 5.0}, 1))
    db.commit()


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


def _decision(required, selected, second=2):
    return _event("decision", "PDF_PROVIDER_TRANSPORT_SHARDING_DECISION", {
        "succeeded": True,
        "sharding_required": required,
        "provider_input_size_bytes": selected,
    }, second)


def _metric(snapshot, key):
    return next(x for x in snapshot.required_metrics if x.key == key)


def _aux(snapshot, key):
    return next(x for x in snapshot.auxiliary_metrics if x.key == key)


def test_fallback_maps_actual_asgi_body_bytes() -> None:
    db = _session(); _seed_base(db)
    db.add_all([
        _decision(False, 120),
        _route(SCOPE_A, transport.ROUTE_FALLBACK, 120, "route", 3),
        _body(SCOPE_A, 1, 120, "body", 4),
        _terminal(SCOPE_A, 1, "terminal", 5),
    ]); db.commit()
    snapshot = collect_s0_run_snapshot(db, processing_run_id=RUN_ID)
    metric = _metric(snapshot, "backend_to_modal_transport_bytes")
    assert metric.status == "observed"
    assert metric.value == 120
    breakdown = _aux(snapshot, "provider_source_transport_breakdown")
    assert breakdown.status == "observed"
    assert breakdown.value["provider_selected_payload_bytes"] == 120
    assert breakdown.value["scopes"][0]["backend_source_body_bytes"] == 120
    assert _metric(snapshot, "modal_download_seconds").status == "not_available"
    assert _aux(snapshot, "provider_source_download_bytes").status == "not_available"


def test_two_presigned_shards_map_zero_backend_source_body_bytes() -> None:
    db = _session(); _seed_base(db)
    db.add_all([
        _decision(True, 280),
        _event("sharding-terminal", "PDF_PROVIDER_TRANSPORT_SHARDING_TERMINAL", {"succeeded": True, "shard_count": 2}, 3),
        _route(SCOPE_A, transport.ROUTE_PRESIGNED, 200, "route-a", 4),
        _route(SCOPE_B, transport.ROUTE_PRESIGNED, 81, "route-b", 5),
        _terminal(SCOPE_A, 0, "terminal-a", 6),
        _terminal(SCOPE_B, 0, "terminal-b", 7),
    ]); db.commit()
    snapshot = collect_s0_run_snapshot(db, processing_run_id=RUN_ID)
    metric = _metric(snapshot, "backend_to_modal_transport_bytes")
    assert metric.status == "observed"
    assert metric.value == 0
    breakdown = _aux(snapshot, "provider_source_transport_breakdown")
    assert breakdown.value["provider_selected_payload_bytes"] == 280
    assert breakdown.value["source_object_total_bytes"] == 281


def test_missing_body_event_fails_closed_against_terminal_count() -> None:
    db = _session(); _seed_base(db)
    db.add_all([
        _decision(False, 120),
        _route(SCOPE_A, transport.ROUTE_FALLBACK, 120, "route", 3),
        _terminal(SCOPE_A, 1, "terminal", 4),
    ]); db.commit()
    metric = _metric(collect_s0_run_snapshot(db, processing_run_id=RUN_ID), "backend_to_modal_transport_bytes")
    assert metric.status == "not_available"
    assert "post-revoke retrieval count" in (metric.note or "")


def test_presigned_scope_rejects_backend_fallback_evidence() -> None:
    db = _session(); _seed_base(db)
    db.add_all([
        _decision(False, 120),
        _route(SCOPE_A, transport.ROUTE_PRESIGNED, 120, "route", 3),
        _body(SCOPE_A, 1, 120, "body", 4),
        _terminal(SCOPE_A, 1, "terminal", 5),
    ]); db.commit()
    metric = _metric(collect_s0_run_snapshot(db, processing_run_id=RUN_ID), "backend_to_modal_transport_bytes")
    assert metric.status == "not_available"
    assert "Presigned" in (metric.note or "")


def test_body_size_must_match_selected_scope_object_size() -> None:
    db = _session(); _seed_base(db)
    db.add_all([
        _decision(False, 120),
        _route(SCOPE_A, transport.ROUTE_FALLBACK, 120, "route", 3),
        _body(SCOPE_A, 1, 119, "body", 4),
        _terminal(SCOPE_A, 1, "terminal", 5),
    ]); db.commit()
    metric = _metric(collect_s0_run_snapshot(db, processing_run_id=RUN_ID), "backend_to_modal_transport_bytes")
    assert metric.status == "not_available"
    assert "source object size" in (metric.note or "")


def test_duplicate_route_evidence_fails_closed() -> None:
    db = _session(); _seed_base(db)
    db.add_all([
        _decision(False, 120),
        _route(SCOPE_A, transport.ROUTE_FALLBACK, 120, "route-a", 3),
        _route(SCOPE_A, transport.ROUTE_FALLBACK, 120, "route-b", 4),
        _body(SCOPE_A, 1, 120, "body", 5),
        _terminal(SCOPE_A, 1, "terminal", 6),
    ]); db.commit()
    metric = _metric(collect_s0_run_snapshot(db, processing_run_id=RUN_ID), "backend_to_modal_transport_bytes")
    assert metric.status == "not_available"
    assert "Duplicate Provider source-route" in (metric.note or "")


def test_malformed_same_name_route_event_fails_closed() -> None:
    db = _session(); _seed_base(db)
    db.add_all([
        _decision(False, 120),
        _route(SCOPE_A, transport.ROUTE_FALLBACK, 120, "route", 3),
        _body(SCOPE_A, 1, 120, "body", 4),
        _terminal(SCOPE_A, 1, "terminal", 5),
        ProcessingEvent(id="malformed-route", processing_run_id=RUN_ID, document_id=DOCUMENT_ID, schema_version="atlas.processing.event.v1", event_name=transport.SOURCE_ROUTE_EVENT, severity="info", payload_json="{", created_at=datetime(2026, 8, 26, 12, 0, 6)),
    ]); db.commit()
    metric = _metric(collect_s0_run_snapshot(db, processing_run_id=RUN_ID), "backend_to_modal_transport_bytes")
    assert metric.status == "not_available"
    assert "could not be inspected" in (metric.note or "")


def test_oversized_same_name_body_event_fails_closed() -> None:
    db = _session(); _seed_base(db)
    db.add_all([
        _decision(False, 120),
        _route(SCOPE_A, transport.ROUTE_FALLBACK, 120, "route", 3),
        _body(SCOPE_A, 1, 120, "body", 4),
        _terminal(SCOPE_A, 1, "terminal", 5),
        ProcessingEvent(id="oversized-body", processing_run_id=RUN_ID, document_id=DOCUMENT_ID, schema_version="atlas.processing.event.v1", event_name=transport.BACKEND_BODY_EVENT, severity="info", payload_json="x" * 9000, created_at=datetime(2026, 8, 26, 12, 0, 6)),
    ]); db.commit()
    metric = _metric(collect_s0_run_snapshot(db, processing_run_id=RUN_ID), "backend_to_modal_transport_bytes")
    assert metric.status == "not_available"
    assert "could not be inspected" in (metric.note or "")


class _FakeResponse:
    def __init__(self, *, content=b"", media_type=None, headers=None):
        self.body = bytes(content)

    async def __call__(self, scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": self.body})


class _Grant:
    grant_id = "grant-1"
    atlas_attempt_id = RUN_ID
    document_id = DOCUMENT_ID
    source_byte_size = 3


def test_response_records_only_after_successful_final_asgi_body_send(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(transport, "record_backend_source_body_transmitted", lambda grant, ordinal, *, body_bytes, body_messages: calls.append((ordinal, body_bytes, body_messages)) or True)
    response = transport.build_source_transport_response(_FakeResponse, content=b"abc")
    assert transport.bind_source_transport_response(response, _Grant(), 1)
    async def send(message):
        return None
    asyncio.run(response({}, None, send))
    assert calls == [(1, 3, 1)]


def test_response_does_not_record_when_asgi_body_send_fails(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(transport, "record_backend_source_body_transmitted", lambda *a, **k: calls.append(1) or True)
    response = transport.build_source_transport_response(_FakeResponse, content=b"abc")
    assert transport.bind_source_transport_response(response, _Grant(), 1)
    async def send(message):
        if message.get("type") == "http.response.body":
            raise RuntimeError("disconnect")
    try:
        asyncio.run(response({}, None, send))
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected disconnect")
    assert calls == []
