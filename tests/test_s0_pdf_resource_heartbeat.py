from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Document, ProcessingRun, SourceFile, decode_json_text
from app.processing import s0_pdf_resource_heartbeat as heartbeat
from app.processing import s0_provider_wait_lease as provider_lease
from app.processing import s0_stale_processing_run_recovery as recovery


def _session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'heartbeat.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _seed(factory):
    db = factory()
    try:
        document = Document(
            id="doc-1",
            title="test",
            file_type="pdf",
            status="processing",
            pages_count=528,
        )
        source = SourceFile(
            id="source-1",
            document_id="doc-1",
            original_filename="test.pdf",
            file_type="pdf",
            byte_size=65445424,
            checksum_sha256="a" * 64,
            storage_reference="src_test",
            retained=1,
            is_primary=1,
        )
        db.add(document)
        db.add(source)
        db.commit()
    finally:
        db.close()


def test_durable_resource_heartbeats_survive_as_bounded_processing_run_history(tmp_path, monkeypatch):
    factory = _session_factory(tmp_path)
    _seed(factory)
    monkeypatch.setattr(heartbeat, "SessionLocal", factory)
    monkeypatch.setattr(
        heartbeat,
        "resource_snapshot",
        lambda: {"pid": 123, "rss_mb": 400.0, "peak_rss_mb": 450.0, "disk_free_mb": 9000.0},
    )

    heartbeat.start_pdf_processing_run(
        processing_run_id="pdf-ingest-test",
        document_id="doc-1",
        source_file_id="source-1",
    )
    for page_number in range(1, 301):
        heartbeat.record_pdf_processing_heartbeat(
            processing_run_id="pdf-ingest-test",
            document_id="doc-1",
            phase="opencv_page_completed",
            page_number=page_number,
            page_count=528,
        )

    db = factory()
    try:
        run = db.query(ProcessingRun).filter_by(processing_run_id="pdf-ingest-test").one()
        assert run.status == "running"
        extensions = decode_json_text(run.extensions_json)
        heartbeat_state = extensions["s0_resource_heartbeat"]
        assert heartbeat_state["version"] == "atlas-s0-pdf-resource-v2"
        checkpoints = heartbeat_state["checkpoints"]
        assert len(checkpoints) == heartbeat.MAX_DURABLE_CHECKPOINTS
        assert checkpoints[-1]["page_number"] == 300
        metrics = decode_json_text(run.metrics_json)["s0_resource"]
        assert metrics["max_observed_rss_mb"] == 400.0
        assert metrics["last_page_number"] == 300
    finally:
        db.close()


def test_sync_terminal_state_marks_processing_run_succeeded_or_failed(tmp_path, monkeypatch):
    factory = _session_factory(tmp_path)
    _seed(factory)
    monkeypatch.setattr(heartbeat, "SessionLocal", factory)

    heartbeat.start_pdf_processing_run(
        processing_run_id="pdf-ingest-test",
        document_id="doc-1",
        source_file_id="source-1",
    )

    db = factory()
    try:
        document = db.get(Document, "doc-1")
        document.status = "completed"
        db.commit()
    finally:
        db.close()

    heartbeat.sync_pdf_processing_run_terminal(
        processing_run_id="pdf-ingest-test",
        document_id="doc-1",
    )
    db = factory()
    try:
        run = db.query(ProcessingRun).filter_by(processing_run_id="pdf-ingest-test").one()
        assert run.status == "succeeded"
        assert run.completed_at is not None
    finally:
        db.close()


def test_page_checkpoint_cadence_is_low_rate_and_keeps_last_page():
    assert heartbeat._should_record_page(1, 528) is True
    assert heartbeat._should_record_page(10, 528) is True
    assert heartbeat._should_record_page(11, 528) is False
    assert heartbeat._should_record_page(520, 528) is True
    assert heartbeat._should_record_page(528, 528) is True


def test_deep_stage_and_liveness_expose_current_page_and_operation(monkeypatch):
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        heartbeat,
        "record_pdf_processing_heartbeat",
        lambda **kwargs: events.append(kwargs) or {},
    )
    state = heartbeat._new_observation_state(
        processing_run_id="pdf-ingest-test",
        document_id="doc-1",
        page_count=528,
    )
    previous = getattr(heartbeat._CONTEXT, "value", None)
    heartbeat._CONTEXT.value = state
    try:
        heartbeat._set_opencv_stage(
            "source_render_300dpi_start",
            page_number=1,
        )
        heartbeat._record_liveness_heartbeat(state)
    finally:
        heartbeat._CONTEXT.value = previous

    assert events[0]["phase"] == "opencv_stage"
    assert events[0]["page_number"] == 1
    assert events[0]["current_stage"] == "source_render_300dpi_start"
    assert events[1]["phase"] == "opencv_liveness"
    assert events[1]["page_number"] == 1
    assert events[1]["current_stage"] == "source_render_300dpi_start"
    assert events[1]["last_completed_page"] == 0


def test_page_decision_updates_liveness_state_even_when_not_durable_cadence(monkeypatch):
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        heartbeat,
        "record_pdf_processing_heartbeat",
        lambda **kwargs: events.append(kwargs) or {},
    )
    state = heartbeat._new_observation_state(
        processing_run_id="pdf-ingest-test",
        document_id="doc-1",
        page_count=528,
    )
    previous = getattr(heartbeat._CONTEXT, "value", None)
    heartbeat._CONTEXT.value = state
    try:
        heartbeat._handle_page_decision({"page_number": 2, "route": "normalized_scan"})
        assert events == []
        heartbeat._record_liveness_heartbeat(state)
        heartbeat._handle_page_decision({"page_number": 10, "route": "normalized_scan"})
    finally:
        heartbeat._CONTEXT.value = previous

    assert events[0]["phase"] == "opencv_liveness"
    assert events[0]["page_number"] == 2
    assert events[0]["last_completed_page"] == 2
    assert events[1]["phase"] == "opencv_page_completed"
    assert events[1]["page_number"] == 10
    assert events[1]["last_completed_page"] == 10


def test_provider_wait_lease_keeps_run_fresh_then_expires_after_worker_stops(
    tmp_path,
    monkeypatch,
):
    factory = _session_factory(tmp_path)
    _seed(factory)
    monkeypatch.setattr(heartbeat, "SessionLocal", factory)
    monkeypatch.setattr(provider_lease, "record_pdf_processing_heartbeat", heartbeat.record_pdf_processing_heartbeat)

    heartbeat.start_pdf_processing_run(
        processing_run_id="pdf-ingest-provider-wait",
        document_id="doc-1",
        source_file_id="source-1",
    )

    async def provider_work():
        await asyncio.sleep(0.045)
        return "provider-result"

    result = asyncio.run(
        provider_lease.await_with_pdf_processing_lease(
            provider_work(),
            processing_run_id="pdf-ingest-provider-wait",
            document_id="doc-1",
            page_count=528,
            provider_job_id="pdf-job-provider-wait",
            heartbeat_interval_seconds=0.01,
        )
    )
    assert result == "provider-result"

    db = factory()
    try:
        run = db.query(ProcessingRun).filter_by(
            processing_run_id="pdf-ingest-provider-wait"
        ).one()
        extensions = decode_json_text(run.extensions_json)
        latest = extensions["s0_resource_heartbeat"]["latest"]
        assert latest["phase"] == "provider_wait_liveness"
        assert latest["page_number"] == 528
        assert latest["provider_job_id"] == "pdf-job-provider-wait"
        assert run.status == "running"
    finally:
        db.close()

    lease_stopped_at = datetime.now(timezone.utc)
    fresh_report = recovery.recover_stale_s0_pdf_processing_runs(
        session_factory=factory,
        now=lease_stopped_at + timedelta(seconds=120),
        stale_after_seconds=300,
    )
    assert fresh_report.recovered == 0
    assert fresh_report.skipped_fresh == 1

    stale_report = recovery.recover_stale_s0_pdf_processing_runs(
        session_factory=factory,
        now=lease_stopped_at + timedelta(seconds=301),
        stale_after_seconds=300,
    )
    assert stale_report.recovered == 1
    db = factory()
    try:
        run = db.query(ProcessingRun).filter_by(
            processing_run_id="pdf-ingest-provider-wait"
        ).one()
        document = db.get(Document, "doc-1")
        assert run.status == "failed"
        assert run.safe_error_code == recovery.PROCESSING_WORKER_LOST_CODE
        assert document.status == "failed"
    finally:
        db.close()


def test_resource_snapshot_shape_is_bounded():
    snapshot = heartbeat.resource_snapshot()
    assert set(snapshot) == {"pid", "rss_mb", "peak_rss_mb", "disk_free_mb"}
    assert isinstance(snapshot["pid"], int)
