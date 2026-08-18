from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    Document,
    ProcessingRun,
    decode_json_text,
    encode_json_text,
)
from app.processing import s0_stale_processing_run_recovery as recovery


def _session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'stale-recovery.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _heartbeat_extensions(at: datetime, *, page_number: int = 140) -> str:
    return encode_json_text(
        {
            "other_provenance": {"keep": True},
            "s0_resource_heartbeat": {
                "version": "atlas-s0-pdf-resource-v2",
                "latest": {
                    "at": at.astimezone(timezone.utc).isoformat(),
                    "phase": "opencv_page_completed",
                    "page_number": page_number,
                    "page_count": 528,
                    "current_stage": "page_completed",
                },
                "checkpoints": [
                    {
                        "at": at.astimezone(timezone.utc).isoformat(),
                        "phase": "opencv_page_completed",
                        "page_number": page_number,
                    }
                ],
            },
        }
    )


def _seed_run(
    factory,
    *,
    document_id: str,
    run_id: str,
    now: datetime,
    heartbeat_age_seconds: float | None,
    document_status: str = "processing",
    policy_ref: str = recovery.S0_PDF_PROCESSING_POLICY_REF,
) -> None:
    db = factory()
    try:
        started_at = now - timedelta(minutes=20)
        created_at = started_at - timedelta(seconds=1)
        document = Document(
            id=document_id,
            title="stale recovery test",
            file_type="pdf",
            status=document_status,
            pages_count=528,
            created_at=created_at.replace(tzinfo=None),
            updated_at=created_at.replace(tzinfo=None),
        )
        extensions = None
        metrics = None
        if heartbeat_age_seconds is not None:
            heartbeat_at = now - timedelta(seconds=heartbeat_age_seconds)
            extensions = _heartbeat_extensions(heartbeat_at)
            metrics = encode_json_text(
                {
                    "s0_resource": {
                        "last_heartbeat_at": heartbeat_at.astimezone(timezone.utc).isoformat(),
                        "last_page_number": 140,
                    }
                }
            )
        run = ProcessingRun(
            processing_run_id=run_id,
            document_id=document_id,
            status="running",
            provider_ref="paddle-vl",
            processing_policy_ref=policy_ref,
            started_at=started_at.replace(tzinfo=None),
            created_at=created_at.replace(tzinfo=None),
            metrics_json=metrics,
            extensions_json=extensions,
        )
        db.add_all([document, run])
        db.commit()
    finally:
        db.close()


def test_stale_s0_run_is_failed_and_heartbeat_evidence_is_preserved(tmp_path):
    factory = _session_factory(tmp_path)
    now = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
    _seed_run(
        factory,
        document_id="doc-stale",
        run_id="pdf-ingest-stale",
        now=now,
        heartbeat_age_seconds=600,
    )

    report = recovery.recover_stale_s0_pdf_processing_runs(
        session_factory=factory,
        now=now,
        stale_after_seconds=300,
    )

    assert report.scanned == 1
    assert report.recovered == 1
    assert report.skipped_fresh == 0
    assert report.errors == 0

    db = factory()
    try:
        run = db.query(ProcessingRun).filter_by(processing_run_id="pdf-ingest-stale").one()
        document = db.get(Document, "doc-stale")
        assert run.status == "failed"
        assert run.failed_at == now.replace(tzinfo=None)
        assert run.safe_error_code == recovery.PROCESSING_WORKER_LOST_CODE
        assert run.safe_error_summary == recovery.PROCESSING_WORKER_LOST_SUMMARY
        assert document.status == "failed"
        assert document.error_message == recovery.PROCESSING_WORKER_LOST_SUMMARY

        extensions = decode_json_text(run.extensions_json)
        assert extensions["other_provenance"] == {"keep": True}
        heartbeat = extensions["s0_resource_heartbeat"]
        assert heartbeat["latest"]["page_number"] == 140
        assert heartbeat["checkpoints"][0]["page_number"] == 140
        recovered = extensions["s0_recovery"]
        assert recovered["version"] == recovery.RECOVERY_VERSION
        assert recovered["reason"] == "stale_heartbeat_lease_expired"
        assert recovered["stale_after_seconds"] == 300.0
    finally:
        db.close()


def test_fresh_s0_run_is_not_recovered(tmp_path):
    factory = _session_factory(tmp_path)
    now = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
    _seed_run(
        factory,
        document_id="doc-fresh",
        run_id="pdf-ingest-fresh",
        now=now,
        heartbeat_age_seconds=120,
    )

    report = recovery.recover_stale_s0_pdf_processing_runs(
        session_factory=factory,
        now=now,
        stale_after_seconds=300,
    )

    assert report.scanned == 1
    assert report.recovered == 0
    assert report.skipped_fresh == 1
    db = factory()
    try:
        assert db.get(Document, "doc-fresh").status == "processing"
        assert db.query(ProcessingRun).filter_by(processing_run_id="pdf-ingest-fresh").one().status == "running"
    finally:
        db.close()


def test_non_s0_run_and_terminal_document_are_preserved(tmp_path):
    factory = _session_factory(tmp_path)
    now = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
    _seed_run(
        factory,
        document_id="doc-other-policy",
        run_id="other-run",
        now=now,
        heartbeat_age_seconds=900,
        policy_ref="some-other-processing-policy",
    )
    _seed_run(
        factory,
        document_id="doc-completed",
        run_id="pdf-ingest-completed-doc",
        now=now,
        heartbeat_age_seconds=900,
        document_status="completed",
    )

    report = recovery.recover_stale_s0_pdf_processing_runs(
        session_factory=factory,
        now=now,
        stale_after_seconds=300,
    )

    # Only the S0 row is in the discovery scope; completed business truth is not
    # downgraded by stale-worker recovery.
    assert report.scanned == 1
    assert report.recovered == 0
    assert report.skipped_non_processing_document == 1
    db = factory()
    try:
        assert db.query(ProcessingRun).filter_by(processing_run_id="other-run").one().status == "running"
        assert db.query(ProcessingRun).filter_by(processing_run_id="pdf-ingest-completed-doc").one().status == "running"
        assert db.get(Document, "doc-completed").status == "completed"
    finally:
        db.close()


def test_missing_heartbeat_falls_back_to_started_at(tmp_path):
    factory = _session_factory(tmp_path)
    now = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
    _seed_run(
        factory,
        document_id="doc-no-heartbeat",
        run_id="pdf-ingest-no-heartbeat",
        now=now,
        heartbeat_age_seconds=None,
    )

    report = recovery.recover_stale_s0_pdf_processing_runs(
        session_factory=factory,
        now=now,
        stale_after_seconds=300,
    )
    assert report.recovered == 1


@pytest.mark.skipif(
    os.getenv("ATLAS_POSTGRESQL_SCHEMA_TEST") != "1",
    reason="requires staging PostgreSQL integration database",
)
def test_postgresql_stale_run_recovery_commits_terminal_pair():
    from app.database import SessionLocal

    token = uuid.uuid4().hex
    document_id = f"doc-stale-pg-{token}"
    run_id = f"pdf-ingest-stale-pg-{token}"
    now = datetime.now(timezone.utc)
    started_at = now - timedelta(minutes=20)
    created_at = started_at - timedelta(seconds=1)
    stale_at = now - timedelta(minutes=10)

    db = SessionLocal()
    try:
        db.add(
            Document(
                id=document_id,
                title="postgres stale recovery test",
                file_type="pdf",
                status="processing",
                pages_count=528,
                created_at=created_at.replace(tzinfo=None),
                updated_at=created_at.replace(tzinfo=None),
            )
        )
        db.add(
            ProcessingRun(
                processing_run_id=run_id,
                document_id=document_id,
                status="running",
                provider_ref="paddle-vl",
                processing_policy_ref=recovery.S0_PDF_PROCESSING_POLICY_REF,
                started_at=started_at.replace(tzinfo=None),
                created_at=created_at.replace(tzinfo=None),
                extensions_json=_heartbeat_extensions(stale_at),
            )
        )
        db.commit()

        report = recovery.recover_stale_s0_pdf_processing_runs(
            session_factory=SessionLocal,
            now=now,
            stale_after_seconds=300,
        )
        assert report.recovered >= 1

        db.expire_all()
        run = db.query(ProcessingRun).filter_by(processing_run_id=run_id).one()
        document = db.get(Document, document_id)
        assert run.status == "failed"
        assert run.safe_error_code == recovery.PROCESSING_WORKER_LOST_CODE
        assert document.status == "failed"
    finally:
        db.rollback()
        run = db.query(ProcessingRun).filter_by(processing_run_id=run_id).one_or_none()
        if run is not None:
            db.delete(run)
            db.flush()
        document = db.get(Document, document_id)
        if document is not None:
            db.delete(document)
        db.commit()
        db.close()
