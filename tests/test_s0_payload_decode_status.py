from __future__ import annotations

from datetime import datetime, timedelta
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Document, ProcessingRun, SourceFile, encode_json_text
from app.processing.processing_event_model import ProcessingEvent
from app.processing.processing_events import MAX_EVENT_PAYLOAD_BYTES
from app.processing.s0_baseline import collect_s0_run_snapshot, render_s0_markdown


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _metric(snapshot, key: str):
    for metric in (*snapshot.required_metrics, *snapshot.auxiliary_metrics):
        if metric.key == key:
            return metric
    raise AssertionError(f"metric not found: {key}")


def _seed_document_run(db, *, suffix: str) -> tuple[ProcessingRun, datetime]:
    started = datetime(2026, 8, 23, 14, 0, 0)
    document = Document(
        id=f"doc-{suffix}",
        title="payload-status-fixture",
        file_type="pdf",
        pages_count=2,
        status="completed",
        created_at=started - timedelta(seconds=5),
        updated_at=started + timedelta(seconds=30),
    )
    source = SourceFile(
        id=f"source-{suffix}",
        document_id=document.id,
        original_filename="fixture.pdf",
        file_type="pdf",
        byte_size=2048,
        checksum_sha256="b" * 64,
        retained=1,
        is_primary=1,
        created_at=started - timedelta(seconds=4),
    )
    run = ProcessingRun(
        id=f"run-row-{suffix}",
        processing_run_id=f"pdf-ingest-{suffix}",
        document_id=document.id,
        source_file_id=source.id,
        status="succeeded",
        started_at=started,
        completed_at=started + timedelta(seconds=20),
        created_at=started,
    )
    db.add_all([document, source, run])
    db.flush()
    return run, started


def _add_valid_payload_event(db, run: ProcessingRun, started: datetime) -> None:
    db.add(
        ProcessingEvent(
            id=f"event-valid-{run.processing_run_id}",
            processing_run_id=run.processing_run_id,
            document_id=run.document_id,
            schema_version="atlas.processing.event.v1",
            event_name="PDF_S0_RESOURCE_HEARTBEAT",
            severity="info",
            payload_json=encode_json_text(
                {"peak_rss_mb": 321.5, "retryable": True}
            ),
            created_at=started + timedelta(seconds=5),
        )
    )


def _add_overflowing_numeric_event(
    db,
    run: ProcessingRun,
    started: datetime,
) -> None:
    payload_json = encode_json_text(
        {"peak_rss_mb": 10**500, "retryable": True}
    )
    assert payload_json is not None
    assert len(payload_json.encode("utf-8")) <= MAX_EVENT_PAYLOAD_BYTES
    db.add(
        ProcessingEvent(
            id=f"event-overflowing-numeric-{run.processing_run_id}",
            processing_run_id=run.processing_run_id,
            document_id=run.document_id,
            schema_version="atlas.processing.event.v1",
            event_name="PDF_S0_RESOURCE_HEARTBEAT",
            severity="info",
            payload_json=payload_json,
            created_at=started + timedelta(seconds=10),
        )
    )


def _seed_malformed_run(db, *, valid_payload: bool) -> str:
    run, started = _seed_document_run(db, suffix="payload-status")
    if valid_payload:
        _add_valid_payload_event(db, run, started)
    db.add(
        ProcessingEvent(
            id="event-malformed-payload",
            processing_run_id=run.processing_run_id,
            document_id=run.document_id,
            schema_version="atlas.processing.event.v1",
            event_name="PDF_PROVIDER_REQUEST_STARTED",
            severity="error",
            payload_json="{malformed-json",
            created_at=started + timedelta(seconds=10),
        )
    )
    db.commit()
    return run.processing_run_id


def _oversized_multibyte_payload() -> str:
    payload = json.dumps(
        {"note": "界" * 2800, "peak_rss_mb": 9999.0, "retryable": True},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    # This fixture specifically proves SQLite must count encoded bytes, not TEXT
    # characters: character length is under the contract while UTF-8 bytes exceed it.
    assert len(payload) < MAX_EVENT_PAYLOAD_BYTES
    assert len(payload.encode("utf-8")) > MAX_EVENT_PAYLOAD_BYTES
    return payload


def _seed_oversized_run(db, *, valid_payload: bool) -> str:
    run, started = _seed_document_run(db, suffix="oversized-payload")
    if valid_payload:
        _add_valid_payload_event(db, run, started)
    db.add(
        ProcessingEvent(
            id="event-oversized-payload",
            processing_run_id=run.processing_run_id,
            document_id=run.document_id,
            schema_version="atlas.processing.event.v1",
            event_name="PDF_PROVIDER_REQUEST_STARTED",
            severity="error",
            payload_json=_oversized_multibyte_payload(),
            created_at=started + timedelta(seconds=10),
        )
    )
    db.commit()
    return run.processing_run_id


def test_malformed_payload_marks_payload_aggregates_partial() -> None:
    db = _session()
    run_id = _seed_malformed_run(db, valid_payload=True)

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)

    assert snapshot.event_payload_decode_incomplete is True
    assert snapshot.event_payload_oversized_incomplete is False
    assert _metric(snapshot, "durable_event_count").value == 2

    # Severity is a row-level field and remains complete when the window is not truncated.
    error_count = _metric(snapshot, "durable_error_event_count")
    assert error_count.status == "observed"
    assert error_count.value == 1

    retryable = _metric(snapshot, "durable_retryable_signal_count")
    assert retryable.status == "partial"
    assert retryable.value == 1
    assert "could not be decoded" in (retryable.note or "")

    peak_rss = _metric(snapshot, "max_observed_peak_rss_mb")
    assert peak_rss.status == "partial"
    assert peak_rss.value == 321.5
    assert "could not be decoded" in (peak_rss.note or "")

    markdown = render_s0_markdown([snapshot])
    assert "event payload decode incomplete: `true`" in markdown
    assert "event payload oversized/incomplete: `false`" in markdown


def test_all_malformed_payloads_do_not_claim_observed_zero_or_maximum() -> None:
    db = _session()
    run_id = _seed_malformed_run(db, valid_payload=False)

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)

    assert snapshot.event_payload_decode_incomplete is True
    assert snapshot.event_payload_oversized_incomplete is False

    retryable = _metric(snapshot, "durable_retryable_signal_count")
    assert retryable.status == "not_available"
    assert retryable.value is None

    peak_rss = _metric(snapshot, "max_observed_peak_rss_mb")
    assert peak_rss.status == "not_available"
    assert peak_rss.value is None


def test_oversized_payload_is_omitted_before_payload_aggregation() -> None:
    db = _session()
    run_id = _seed_oversized_run(db, valid_payload=True)

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)

    assert snapshot.event_payload_decode_incomplete is False
    assert snapshot.event_payload_oversized_incomplete is True
    assert _metric(snapshot, "durable_event_count").value == 2

    # Row metadata remains usable even when the oversized Text body is omitted.
    error_count = _metric(snapshot, "durable_error_event_count")
    assert error_count.status == "observed"
    assert error_count.value == 1

    retryable = _metric(snapshot, "durable_retryable_signal_count")
    assert retryable.status == "partial"
    assert retryable.value == 1
    assert "omitted by the database projection before materialization" in (
        retryable.note or ""
    )

    peak_rss = _metric(snapshot, "max_observed_peak_rss_mb")
    assert peak_rss.status == "partial"
    assert peak_rss.value == 321.5
    assert "omitted before materialization" in (peak_rss.note or "")

    # The hidden 9999 signal and large body must not enter payload-derived output.
    assert snapshot.observed_numeric_event_fields == ("peak_rss_mb",)
    markdown = render_s0_markdown([snapshot])
    assert "event payload oversized/incomplete: `true`" in markdown
    assert "9999" not in markdown
    assert "界" not in markdown


def test_all_oversized_payloads_leave_payload_aggregates_unavailable() -> None:
    db = _session()
    run_id = _seed_oversized_run(db, valid_payload=False)

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)

    assert snapshot.event_payload_decode_incomplete is False
    assert snapshot.event_payload_oversized_incomplete is True
    assert snapshot.observed_numeric_event_fields == ()

    retryable = _metric(snapshot, "durable_retryable_signal_count")
    assert retryable.status == "not_available"
    assert retryable.value is None

    peak_rss = _metric(snapshot, "max_observed_peak_rss_mb")
    assert peak_rss.status == "not_available"
    assert peak_rss.value is None


def test_overflowing_numeric_payload_marks_peak_rss_partial_without_crashing() -> None:
    db = _session()
    run, started = _seed_document_run(db, suffix="overflowing-numeric-mixed")
    _add_valid_payload_event(db, run, started)
    _add_overflowing_numeric_event(db, run, started)
    db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run.processing_run_id)

    assert snapshot.event_payload_decode_incomplete is False
    assert snapshot.event_payload_oversized_incomplete is False
    assert snapshot.observed_numeric_event_fields == ("peak_rss_mb",)

    # Numeric overflow affects only numeric evidence; the decoded retryable signal
    # remains usable and complete.
    retryable = _metric(snapshot, "durable_retryable_signal_count")
    assert retryable.status == "observed"
    assert retryable.value == 2

    peak_rss = _metric(snapshot, "max_observed_peak_rss_mb")
    assert peak_rss.status == "partial"
    assert peak_rss.value == 321.5
    assert "unusable peak_rss_mb numeric value" in (peak_rss.note or "")


def test_only_overflowing_peak_rss_is_not_available() -> None:
    db = _session()
    run, started = _seed_document_run(db, suffix="overflowing-numeric-only")
    _add_overflowing_numeric_event(db, run, started)
    db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run.processing_run_id)

    assert snapshot.event_payload_decode_incomplete is False
    assert snapshot.event_payload_oversized_incomplete is False
    assert snapshot.observed_numeric_event_fields == ()

    retryable = _metric(snapshot, "durable_retryable_signal_count")
    assert retryable.status == "observed"
    assert retryable.value == 1

    peak_rss = _metric(snapshot, "max_observed_peak_rss_mb")
    assert peak_rss.status == "not_available"
    assert peak_rss.value is None
    assert "unusable peak_rss_mb numeric value" in (peak_rss.note or "")
