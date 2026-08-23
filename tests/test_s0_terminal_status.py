from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Document, ProcessingRun
from app.processing.s0_baseline import collect_s0_run_snapshot


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
    status: str,
    completed_at: datetime | None,
    failed_at: datetime | None,
) -> tuple[str, datetime]:
    started = datetime(2026, 8, 23, 12, 0, 0)
    document = Document(
        id=f"doc-{status}",
        title="private-title-not-emitted",
        file_type="pdf",
        pages_count=1,
        status="completed",
        created_at=started - timedelta(seconds=5),
        updated_at=started + timedelta(seconds=60),
    )
    run = ProcessingRun(
        id=f"run-row-{status}",
        processing_run_id=f"pdf-ingest-{status}",
        document_id=document.id,
        status=status,
        started_at=started,
        completed_at=completed_at,
        failed_at=failed_at,
        created_at=started,
    )
    db.add_all([document, run])
    db.commit()
    return run.processing_run_id, started


def test_failed_run_uses_failed_at_even_when_stale_completed_at_remains() -> None:
    db = _session()
    started = datetime(2026, 8, 23, 12, 0, 0)
    stale_completed = started + timedelta(seconds=10)
    failed = started + timedelta(seconds=40)
    run_id, _ = _seed_run(
        db,
        status="failed",
        completed_at=stale_completed,
        failed_at=failed,
    )

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)

    assert snapshot.terminal_at == failed.isoformat()
    wall = _metric(snapshot, "processing_run_wall_seconds")
    assert wall.status == "observed"
    assert wall.value == 40.0
    acceptance = _metric(snapshot, "document_acceptance_to_terminal_seconds")
    assert acceptance.status == "observed"
    assert acceptance.value == 45.0


def test_succeeded_run_uses_completed_at_even_when_failed_at_is_stale() -> None:
    db = _session()
    started = datetime(2026, 8, 23, 12, 0, 0)
    completed = started + timedelta(seconds=15)
    stale_failed = started + timedelta(seconds=50)
    run_id, _ = _seed_run(
        db,
        status="succeeded",
        completed_at=completed,
        failed_at=stale_failed,
    )

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)

    assert snapshot.terminal_at == completed.isoformat()
    assert _metric(snapshot, "processing_run_wall_seconds").value == 15.0


def test_nonterminal_run_does_not_use_stale_terminal_timestamps() -> None:
    db = _session()
    started = datetime(2026, 8, 23, 12, 0, 0)
    run_id, _ = _seed_run(
        db,
        status="running",
        completed_at=started + timedelta(seconds=10),
        failed_at=started + timedelta(seconds=20),
    )

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)

    assert snapshot.terminal_at is None
    wall = _metric(snapshot, "processing_run_wall_seconds")
    assert wall.status == "not_available"
    assert wall.value is None
    acceptance = _metric(snapshot, "document_acceptance_to_terminal_seconds")
    assert acceptance.status == "not_available"
    assert acceptance.value is None


def test_zero_length_processing_duration_is_not_baseline_evidence() -> None:
    db = _session()
    started = datetime(2026, 8, 23, 12, 0, 0)
    run_id, _ = _seed_run(
        db,
        status="succeeded",
        completed_at=started,
        failed_at=None,
    )

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)

    assert snapshot.terminal_at == started.isoformat()
    wall = _metric(snapshot, "processing_run_wall_seconds")
    assert wall.status == "not_available"
    assert wall.value is None

    # Document acceptance still has independent positive timing evidence in this
    # fixture and should not be discarded merely because run start == terminal.
    acceptance = _metric(snapshot, "document_acceptance_to_terminal_seconds")
    assert acceptance.status == "observed"
    assert acceptance.value == 5.0


def test_negative_processing_duration_is_not_baseline_evidence() -> None:
    db = _session()
    started = datetime(2026, 8, 23, 12, 0, 0)
    completed_before_start = started - timedelta(seconds=1)
    run_id, _ = _seed_run(
        db,
        status="succeeded",
        completed_at=completed_before_start,
        failed_at=None,
    )

    snapshot = collect_s0_run_snapshot(db, processing_run_id=run_id)

    assert snapshot.terminal_at == completed_before_start.isoformat()
    wall = _metric(snapshot, "processing_run_wall_seconds")
    assert wall.status == "not_available"
    assert wall.value is None

    # The document was accepted four seconds before this inconsistent terminal
    # timestamp, so the independent acceptance proxy remains positive/observable.
    acceptance = _metric(snapshot, "document_acceptance_to_terminal_seconds")
    assert acceptance.status == "observed"
    assert acceptance.value == 4.0
