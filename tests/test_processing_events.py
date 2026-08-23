from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Document, decode_json_text, encode_json_text
from app.processing.processing_event_model import ProcessingEvent
from app.processing import processing_events


def _session_factory(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'events.db'}")
    Base.metadata.create_all(
        engine,
        tables=[Document.__table__, ProcessingEvent.__table__],
    )
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _document(factory, document_id: str = "doc-events") -> None:
    db = factory()
    try:
        db.add(
            Document(
                id=document_id,
                title="Durable events test",
                file_type="pdf",
                status="processing",
            )
        )
        db.commit()
    finally:
        db.close()


def _enable_staging(tmp_path: Path, monkeypatch) -> None:
    marker = tmp_path / "staging-revision.txt"
    marker.write_text("a" * 40 + "\n", encoding="utf-8")
    monkeypatch.setattr(processing_events, "_STAGING_REVISION_FILE", marker)


def test_event_can_be_persisted_before_processing_run_exists(tmp_path, monkeypatch):
    factory = _session_factory(tmp_path)
    _document(factory)
    _enable_staging(tmp_path, monkeypatch)

    assert processing_events.record_processing_event(
        processing_run_id="pdf-ingest-before-run",
        document_id="doc-events",
        event_name="PDF_BACKGROUND_TASK_STARTED",
        payload={"processing_attempt_id": "pdf-ingest-before-run", "phase": "accepted"},
        session_factory=factory,
    ) is True

    db = factory()
    try:
        row = db.query(ProcessingEvent).one()
        assert row.processing_run_id == "pdf-ingest-before-run"
        assert row.document_id == "doc-events"
        assert row.schema_version == processing_events.PROCESSING_EVENT_SCHEMA_VERSION
        assert decode_json_text(row.payload_json)["phase"] == "accepted"
    finally:
        db.close()


def test_payload_is_bounded_and_sensitive_fields_are_removed(tmp_path, monkeypatch):
    factory = _session_factory(tmp_path)
    _document(factory)
    _enable_staging(tmp_path, monkeypatch)

    assert processing_events.record_processing_event(
        processing_run_id="pdf-ingest-safe",
        document_id="doc-events",
        event_name="PDF_PAGE_CLASSIFICATION_SUMMARY",
        page_number=2,
        payload={
            "safe_count": 7,
            "authorization": "Bearer should-never-persist",
            "api_key": "should-never-persist",
            "signed_url": "https://example.invalid/secret",
            "safe_field_with_url_value": "https://example.invalid/also-secret",
            "nested": {
                "safe_reason": "bounded",
                "password": "should-never-persist",
            },
            "long_text": "x" * 2000,
            "not_finite": float("nan"),
        },
        session_factory=factory,
    ) is True

    db = factory()
    try:
        row = db.query(ProcessingEvent).one()
        payload = decode_json_text(row.payload_json)
        assert payload["safe_count"] == 7
        assert payload["nested"] == {"safe_reason": "bounded"}
        assert len(payload["long_text"]) == processing_events.MAX_STRING_CHARS
        assert "authorization" not in payload
        assert "api_key" not in payload
        assert "signed_url" not in payload
        assert "safe_field_with_url_value" not in payload
        assert "not_finite" not in payload
        assert len(row.payload_json.encode("utf-8")) <= processing_events.MAX_EVENT_PAYLOAD_BYTES
        assert row.page_number == 2
    finally:
        db.close()


def test_payload_byte_ceiling_is_strict():
    payload = processing_events.sanitize_processing_event_payload(
        {f"field_{index:02d}": "z" * 2000 for index in range(40)}
    )
    encoded = encode_json_text(payload) or "{}"
    assert len(payload) <= processing_events.MAX_PAYLOAD_FIELDS
    assert len(encoded.encode("utf-8")) <= processing_events.MAX_EVENT_PAYLOAD_BYTES


def test_missing_or_invalid_staging_marker_disables_persistence(tmp_path, monkeypatch):
    factory = _session_factory(tmp_path)
    _document(factory)
    marker = tmp_path / "staging-revision.txt"
    monkeypatch.setattr(processing_events, "_STAGING_REVISION_FILE", marker)

    assert processing_events.record_processing_event(
        processing_run_id="pdf-ingest-disabled",
        document_id="doc-events",
        event_name="PDF_SOURCE_VALIDATED",
        session_factory=factory,
    ) is False

    marker.write_text("not-a-commit\n", encoding="utf-8")
    assert processing_events.record_processing_event(
        processing_run_id="pdf-ingest-disabled",
        document_id="doc-events",
        event_name="PDF_SOURCE_VALIDATED",
        session_factory=factory,
    ) is False

    db = factory()
    try:
        assert db.query(ProcessingEvent).count() == 0
    finally:
        db.close()


def test_query_returns_latest_window_in_chronological_order(tmp_path, monkeypatch):
    factory = _session_factory(tmp_path)
    _document(factory)
    _enable_staging(tmp_path, monkeypatch)

    for index, name in enumerate(
        ("PDF_SOURCE_VALIDATED", "PDF_PROVIDER_REQUEST_STARTED", "PDF_PROVIDER_TERMINAL"),
        start=1,
    ):
        assert processing_events.record_processing_event(
            processing_run_id="pdf-ingest-query",
            document_id="doc-events",
            event_name=name,
            payload={"order": index},
            session_factory=factory,
        ) is True

    db = factory()
    try:
        records = processing_events.list_processing_events(
            db,
            processing_run_id="pdf-ingest-query",
            limit=2,
        )
        assert [item.payload["order"] for item in records] == [2, 3]
        terminal = processing_events.list_processing_events(
            db,
            document_id="doc-events",
            event_name="PDF_PROVIDER_TERMINAL",
        )
        assert len(terminal) == 1
        assert terminal[0].processing_run_id == "pdf-ingest-query"
    finally:
        db.close()


def test_persistence_failure_is_fail_open(tmp_path, monkeypatch):
    _enable_staging(tmp_path, monkeypatch)

    def broken_session_factory():
        raise RuntimeError("database unavailable")

    assert processing_events.record_processing_event(
        processing_run_id="pdf-ingest-fail-open",
        document_id="doc-events",
        event_name="PDF_PROVIDER_TERMINAL",
        session_factory=broken_session_factory,
    ) is False
