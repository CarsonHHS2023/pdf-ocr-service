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


def _seed_run(
    db,
    *,
    suffix: str,
    checksum: str = "a" * 64,
    file_type: str = "pdf",
) -> tuple[ProcessingRun, datetime]:
    started = datetime(2026, 8, 23, 16, 0, 0)
    document = Document(
        id=f"doc-{suffix}",
        title="private-title-not-for-output",
        file_type=file_type,
        pages_count=3,
        status="completed",
        created_at=started - timedelta(seconds=5),
        updated_at=started + timedelta(seconds=30),
    )
    source = SourceFile(
        id=f"source-{suffix}",
        document_id=document.id,
        original_filename="private.pdf",
        file_type=file_type,
        byte_size=4096,
        checksum_sha256=checksum,
        retained=1,
        is_primary=1,
        created_at=started - timedelta(seconds=4),
    )
    run_prefix = file_type if file_type in {"pdf", "txt"} else "pdf"
    run = ProcessingRun(
        id=f"run-row-{suffix}",
        processing_run_id=f"{run_prefix}-ingest-{suffix}",
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


def _add_event(db, run: ProcessingRun, started: datetime, *, event_id: str, payload: dict, seconds: int) -> None:
    db.add(
        ProcessingEvent(
            id=event_id,
            processing_run_id=run.processing_run_id,
            document_id=run.document_id,
            schema_version="atlas.processing.event.v1",
            event_name="PDF_PROVIDER_REQUEST_STARTED",
            severity="info",
            payload_json=encode_json_text(payload),
            created_at=started + timedelta(seconds=seconds),
        )
    )


@pytest.mark.parametrize("invalid_retryable", [1, "true", None])
def test_only_invalid_retryable_value_is_not_available(invalid_retryable) -> None:
    db = _session()
    run, started = _seed_run(db, suffix=f"invalid-retryable-{type(invalid_retryable).__name__}")
    _add_event(
        db,
        run,
        started,
        event_id="event-invalid-retryable",
        payload={"retryable": invalid_retryable},
        seconds=5,
    )
    db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run.processing_run_id)
    retryable = _metric(snapshot, "durable_retryable_signal_count")

    assert retryable.status == "not_available"
    assert retryable.value is None
    assert "non-Boolean retryable value" in (retryable.note or "")


def test_valid_and_invalid_retryable_values_make_count_partial() -> None:
    db = _session()
    run, started = _seed_run(db, suffix="mixed-retryable")
    _add_event(
        db,
        run,
        started,
        event_id="event-valid-retryable",
        payload={"retryable": True},
        seconds=5,
    )
    _add_event(
        db,
        run,
        started,
        event_id="event-invalid-retryable",
        payload={"retryable": "true"},
        seconds=10,
    )
    db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run.processing_run_id)
    retryable = _metric(snapshot, "durable_retryable_signal_count")

    assert retryable.status == "partial"
    assert retryable.value == 1
    assert "non-Boolean retryable value" in (retryable.note or "")


def test_valid_and_null_peak_rss_values_make_maximum_partial() -> None:
    db = _session()
    run, started = _seed_run(db, suffix="mixed-null-peak-rss")
    _add_event(
        db,
        run,
        started,
        event_id="event-valid-peak-rss",
        payload={"peak_rss_mb": 321.5},
        seconds=5,
    )
    _add_event(
        db,
        run,
        started,
        event_id="event-null-peak-rss",
        payload={"peak_rss_mb": None},
        seconds=10,
    )
    db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run.processing_run_id)
    peak_rss = _metric(snapshot, "max_observed_peak_rss_mb")

    assert peak_rss.status == "partial"
    assert peak_rss.value == 321.5
    assert "unusable peak_rss_mb numeric value" in (peak_rss.note or "")


def test_only_null_peak_rss_is_not_available() -> None:
    db = _session()
    run, started = _seed_run(db, suffix="null-only-peak-rss")
    _add_event(
        db,
        run,
        started,
        event_id="event-null-peak-rss",
        payload={"peak_rss_mb": None},
        seconds=5,
    )
    db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run.processing_run_id)
    peak_rss = _metric(snapshot, "max_observed_peak_rss_mb")

    assert peak_rss.status == "not_available"
    assert peak_rss.value is None
    assert "unusable peak_rss_mb numeric value" in (peak_rss.note or "")


@pytest.mark.parametrize(
    "checksum",
    [
        "g" * 64,
        "a" * 63,
        "a" * 65,
        "private.pdf-not-a-checksum",
    ],
)
def test_invalid_retained_checksum_is_not_exposed(checksum: str) -> None:
    db = _session()
    run, _ = _seed_run(db, suffix=f"invalid-checksum-{len(checksum)}", checksum=checksum)
    db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run.processing_run_id)
    markdown = render_s0_markdown([snapshot])

    assert snapshot.source_checksum_sha256 is None
    assert checksum not in str(snapshot.to_dict())
    assert checksum not in markdown
    assert f"document ID: `{run.document_id}`" in markdown
    assert "source checksum SHA-256: `unavailable`" in markdown


def test_exact_64_hex_checksum_remains_available() -> None:
    db = _session()
    checksum = "A1" * 32
    run, _ = _seed_run(db, suffix="valid-checksum", checksum=checksum)
    db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run.processing_run_id)
    markdown = render_s0_markdown([snapshot])

    assert snapshot.source_checksum_sha256 == checksum
    assert f"document ID: `{run.document_id}`" in markdown
    assert f"source checksum SHA-256: `{checksum}`" in markdown


@pytest.mark.parametrize("file_type", ["secret.pdf", "pdf`\nprivate.pdf"])
def test_invalid_retained_file_type_is_not_exposed(file_type: str) -> None:
    db = _session()
    run, _ = _seed_run(
        db,
        suffix=f"invalid-file-type-{len(file_type)}",
        file_type=file_type,
    )
    db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run.processing_run_id)
    markdown = render_s0_markdown([snapshot])

    assert snapshot.file_type is None
    assert file_type not in str(snapshot.to_dict())
    assert file_type not in markdown
    assert "file type: `unavailable`" in markdown


@pytest.mark.parametrize("file_type", ["pdf", "txt"])
def test_valid_retained_file_type_remains_available(file_type: str) -> None:
    db = _session()
    run, _ = _seed_run(db, suffix=f"valid-file-type-{file_type}", file_type=file_type)
    db.commit()

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run.processing_run_id)
    markdown = render_s0_markdown([snapshot])

    assert snapshot.file_type == file_type
    assert f"file type: `{file_type}`" in markdown
