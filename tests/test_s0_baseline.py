from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Document, ProcessingRun, SourceFile, encode_json_text
from app.processing.processing_event_model import ProcessingEvent
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


def _seed_run(db, *, with_events: bool = True) -> str:
    started = datetime(2026, 8, 23, 12, 0, 0)
    document = Document(
        id="doc-s0",
        title="private-fixture-name-is-not-emitted",
        file_type="pdf",
        pages_count=11,
        status="completed",
        created_at=started - timedelta(seconds=10),
        updated_at=started + timedelta(seconds=90),
    )
    source = SourceFile(
        id="source-s0",
        document_id=document.id,
        original_filename="private.pdf",
        file_type="pdf",
        byte_size=4_558_903,
        checksum_sha256="a" * 64,
        retained=1,
        is_primary=1,
        created_at=started - timedelta(seconds=9),
    )
    run = ProcessingRun(
        id="run-row-s0",
        processing_run_id="pdf-ingest-s0",
        document_id=document.id,
        source_file_id=source.id,
        status="succeeded",
        started_at=started,
        completed_at=started + timedelta(seconds=82.779),
        created_at=started,
    )
    db.add_all([document, source, run])
    db.flush()

    if with_events:
        db.add_all(
            [
                ProcessingEvent(
                    id="event-1",
                    processing_run_id=run.processing_run_id,
                    document_id=document.id,
                    schema_version="atlas.processing.event.v1",
                    event_name="PDF_S0_RESOURCE_HEARTBEAT",
                    severity="info",
                    payload_json=encode_json_text(
                        {"peak_rss_mb": 512.5, "phase": "page_completed"}
                    ),
                    created_at=started + timedelta(seconds=5),
                ),
                ProcessingEvent(
                    id="event-2",
                    processing_run_id=run.processing_run_id,
                    document_id=document.id,
                    schema_version="atlas.processing.event.v1",
                    event_name="PDF_PROVIDER_RETRY_STARTED",
                    severity="warning",
                    payload_json=encode_json_text(
                        {"peak_rss_mb": 526.25, "retryable": True}
                    ),
                    created_at=started + timedelta(seconds=20),
                ),
                ProcessingEvent(
                    id="event-3",
                    processing_run_id=run.processing_run_id,
                    document_id=document.id,
                    schema_version="atlas.processing.event.v1",
                    event_name="PDF_INGESTION_UNHANDLED_FAILURE",
                    severity="error",
                    payload_json=encode_json_text(
                        {"retryable": False, "provider_http_status": 503}
                    ),
                    created_at=started + timedelta(seconds=30),
                ),
            ]
        )
    db.commit()
    return run.processing_run_id


def test_collect_s0_snapshot_uses_only_durable_authoritative_fields() -> None:
    db = _session()
    run_id = _seed_run(db)

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)

    assert snapshot.schema_version == "atlas.s0.baseline.v1"
    assert snapshot.file_type == "pdf"
    assert snapshot.source_checksum_sha256 == "a" * 64
    assert _metric(snapshot, "source_byte_size").value == 4_558_903
    assert _metric(snapshot, "page_count").value == 11
    assert _metric(snapshot, "processing_run_wall_seconds").value == 82.779
    assert _metric(snapshot, "durable_event_count").value == 3
    assert _metric(snapshot, "durable_event_span_seconds").value == 25.0
    assert _metric(snapshot, "max_observed_peak_rss_mb").value == 526.25
    assert _metric(snapshot, "max_observed_peak_rss_mb").status == "observed"

    required_failure_retry = _metric(snapshot, "failure_retry_counts")
    assert required_failure_retry.status == "not_instrumented"
    assert required_failure_retry.value is None

    error_signals = _metric(snapshot, "durable_error_event_count")
    assert error_signals.status == "observed"
    assert error_signals.value == 1

    retryable_signals = _metric(snapshot, "durable_retryable_signal_count")
    assert retryable_signals.status == "observed"
    assert retryable_signals.value == 1
    assert "does not prove" in (retryable_signals.note or "")


def test_missing_s0_metrics_are_explicit_not_inferred() -> None:
    db = _session()
    run_id = _seed_run(db)

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)

    assert _metric(snapshot, "backend_upload_peak_memory_mb").status == "not_instrumented"
    assert _metric(snapshot, "backend_upload_peak_memory_mb").value is None
    assert _metric(snapshot, "upload_duration_seconds").status == "not_instrumented"
    assert _metric(snapshot, "backend_to_modal_transport_bytes").status == "not_instrumented"
    assert _metric(snapshot, "reader_open_latency_seconds").status == "not_instrumented"
    assert _metric(snapshot, "upload_to_reader_ready_seconds").status == "not_instrumented"
    assert _metric(snapshot, "failure_retry_counts").status == "not_instrumented"


def test_run_without_retained_events_does_not_claim_zero_event_signals() -> None:
    db = _session()
    run_id = _seed_run(db, with_events=False)

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)

    assert _metric(snapshot, "failure_retry_counts").status == "not_instrumented"
    assert _metric(snapshot, "durable_event_count").value == 0
    assert _metric(snapshot, "durable_error_event_count").status == "not_available"
    assert _metric(snapshot, "durable_error_event_count").value is None
    assert _metric(snapshot, "durable_retryable_signal_count").status == "not_available"
    assert _metric(snapshot, "durable_retryable_signal_count").value is None
    assert _metric(snapshot, "max_observed_peak_rss_mb").status == "not_available"


def test_event_window_is_bounded_and_marks_event_aggregates_partial() -> None:
    db = _session()
    run_id = _seed_run(db)

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id, max_events=2)

    assert snapshot.event_window_truncated is True
    assert _metric(snapshot, "durable_event_count").value == 2
    assert _metric(snapshot, "failure_retry_counts").status == "not_instrumented"

    error_signals = _metric(snapshot, "durable_error_event_count")
    assert error_signals.status == "partial"
    assert error_signals.value == 0

    retryable_signals = _metric(snapshot, "durable_retryable_signal_count")
    assert retryable_signals.status == "partial"
    assert retryable_signals.value == 1

    peak_rss = _metric(snapshot, "max_observed_peak_rss_mb")
    assert peak_rss.status == "partial"
    assert peak_rss.value == 526.25
    assert "truncated" in (peak_rss.note or "")

    event_span = _metric(snapshot, "durable_event_span_seconds")
    assert event_span.value == 15.0
    assert "snapshot window" in event_span.label


def test_markdown_does_not_emit_document_title_or_filename() -> None:
    db = _session()
    run_id = _seed_run(db)
    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)

    markdown = render_s0_markdown([snapshot])

    assert "private-fixture-name-is-not-emitted" not in markdown
    assert "private.pdf" not in markdown
    assert "Source byte size" in markdown
    assert "not_instrumented" in markdown
    assert "`partial`" in render_s0_markdown(
        [collect_s0_run_snapshot(db, processing_run_id=run_id, max_events=2)]
    )


def test_unknown_processing_run_fails_closed() -> None:
    db = _session()

    with pytest.raises(LookupError, match="ProcessingRun not found"):
        collect_s0_run_snapshot(db, processing_run_id="missing-run")


def test_invalid_event_limit_is_rejected() -> None:
    db = _session()
    run_id = _seed_run(db)

    with pytest.raises(ValueError, match="max_events must be positive"):
        collect_s0_run_snapshot(db, processing_run_id=run_id, max_events=0)
