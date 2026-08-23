from __future__ import annotations

from datetime import datetime, timedelta

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


def _seed_run(db, *, valid_payload: bool) -> str:
    started = datetime(2026, 8, 23, 14, 0, 0)
    document = Document(
        id="doc-payload-status",
        title="payload-status-fixture",
        file_type="pdf",
        pages_count=2,
        status="completed",
        created_at=started - timedelta(seconds=5),
        updated_at=started + timedelta(seconds=30),
    )
    source = SourceFile(
        id="source-payload-status",
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
        id="run-row-payload-status",
        processing_run_id="pdf-ingest-payload-status",
        document_id=document.id,
        source_file_id=source.id,
        status="succeeded",
        started_at=started,
        completed_at=started + timedelta(seconds=20),
        created_at=started,
    )
    db.add_all([document, source, run])
    db.flush()

    if valid_payload:
        db.add(
            ProcessingEvent(
                id="event-valid-payload",
                processing_run_id=run.processing_run_id,
                document_id=document.id,
                schema_version="atlas.processing.event.v1",
                event_name="PDF_S0_RESOURCE_HEARTBEAT",
                severity="info",
                payload_json=encode_json_text(
                    {"peak_rss_mb": 321.5, "retryable": True}
                ),
                created_at=started + timedelta(seconds=5),
            )
        )

    db.add(
        ProcessingEvent(
            id="event-malformed-payload",
            processing_run_id=run.processing_run_id,
            document_id=document.id,
            schema_version="atlas.processing.event.v1",
            event_name="PDF_PROVIDER_REQUEST_STARTED",
            severity="error",
            payload_json="{malformed-json",
            created_at=started + timedelta(seconds=10),
        )
    )
    db.commit()
    return run.processing_run_id


def test_malformed_payload_marks_payload_aggregates_partial() -> None:
    db = _session()
    run_id = _seed_run(db, valid_payload=True)

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)

    assert snapshot.event_payload_decode_incomplete is True
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


def test_all_malformed_payloads_do_not_claim_observed_zero_or_maximum() -> None:
    db = _session()
    run_id = _seed_run(db, valid_payload=False)

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)

    assert snapshot.event_payload_decode_incomplete is True

    retryable = _metric(snapshot, "durable_retryable_signal_count")
    assert retryable.status == "not_available"
    assert retryable.value is None

    peak_rss = _metric(snapshot, "max_observed_peak_rss_mb")
    assert peak_rss.status == "not_available"
    assert peak_rss.value is None
