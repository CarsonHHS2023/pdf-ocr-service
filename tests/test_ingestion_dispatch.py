from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Document, SourceFile
from app.processing.ingestion_dispatch import (
    DispatchPayload,
    claim_ingestion_dispatch,
    create_ingestion_dispatch,
    get_dispatch_by_acceptance_key,
    mark_ingestion_dispatch_running,
    new_dispatch_payload,
    recover_ingestion_dispatches,
    run_ingestion_dispatch,
    stable_storage_reference,
)
from app.processing.ingestion_dispatch_model import IngestionDispatch


def _session_factory(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'dispatch.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _accepted_source(session_factory, *, kind: str = "pdf") -> tuple[str, str]:
    document_id = str(uuid.uuid4())
    source_file_id = str(uuid.uuid4())
    db = session_factory()
    try:
        db.add(
            Document(
                id=document_id,
                document_type="book",
                title="Dispatch fixture",
                file_type=kind,
                status="processing",
            )
        )
        db.add(
            SourceFile(
                id=source_file_id,
                document_id=document_id,
                original_filename=f"fixture.{kind}",
                file_type=kind,
                mime_type=("application/pdf" if kind == "pdf" else "text/plain"),
                byte_size=3,
                checksum_sha256="a" * 64,
                storage_reference=f"src_{uuid.uuid4().hex}",
                retained=1,
                is_primary=1,
            )
        )
        db.commit()
    finally:
        db.close()
    return document_id, source_file_id


def _create_dispatch(
    session_factory,
    *,
    kind: str = "pdf",
    acceptance_key: str | None = None,
    now: datetime | None = None,
):
    document_id, source_file_id = _accepted_source(session_factory, kind=kind)
    payload = new_dispatch_payload(kind)
    db = session_factory()
    try:
        row = create_ingestion_dispatch(
            db,
            acceptance_key=acceptance_key or f"test:{uuid.uuid4().hex}",
            document_id=document_id,
            source_file_id=source_file_id,
            payload=payload,
            now=now,
        )
        db.commit()
        dispatch_id = row.id
    finally:
        db.close()
    return dispatch_id, document_id, source_file_id, payload


def _row(session_factory, dispatch_id: str) -> IngestionDispatch:
    db = session_factory()
    try:
        row = db.get(IngestionDispatch, dispatch_id)
        assert row is not None
        db.expunge(row)
        return row
    finally:
        db.close()


def _document_status(session_factory, document_id: str) -> tuple[str, str | None]:
    db = session_factory()
    try:
        document = db.get(Document, document_id)
        assert document is not None
        return document.status, document.error_message
    finally:
        db.close()


def _set_document_status(session_factory, document_id: str, status: str, error: str | None = None) -> None:
    db = session_factory()
    try:
        document = db.get(Document, document_id)
        assert document is not None
        document.status = status
        document.error_message = error
        db.commit()
    finally:
        db.close()


def test_stable_storage_reference_is_deterministic_and_acceptance_scoped():
    first = stable_storage_reference("resumable:upload-1")
    assert first == stable_storage_reference("resumable:upload-1")
    assert first != stable_storage_reference("resumable:upload-2")
    assert str(first).startswith("src_")
    assert len(str(first)) == 36


def test_payload_contract_fails_closed_before_database_commit(tmp_path):
    session_factory = _session_factory(tmp_path)
    document_id, source_file_id = _accepted_source(session_factory)
    db = session_factory()
    try:
        try:
            create_ingestion_dispatch(
                db,
                acceptance_key="test:partial-pdf",
                document_id=document_id,
                source_file_id=source_file_id,
                payload=DispatchPayload(
                    kind="pdf",
                    processing_attempt_id="pdf-ingest-only",
                ),
            )
        except ValueError as exc:
            assert "exactly the PDF" in str(exc)
        else:  # pragma: no cover - regression guard
            raise AssertionError("partial provider identity was accepted")
    finally:
        db.close()


def test_acceptance_key_lookup_returns_same_durable_business_envelope(tmp_path):
    session_factory = _session_factory(tmp_path)
    dispatch_id, document_id, source_file_id, _ = _create_dispatch(
        session_factory,
        acceptance_key="resumable:stable-upload-id",
    )
    db = session_factory()
    try:
        row = get_dispatch_by_acceptance_key(db, "resumable:stable-upload-id")
        assert row is not None
        assert row.id == dispatch_id
        assert row.document_id == document_id
        assert row.source_file_id == source_file_id
        assert row.status == "queued"
    finally:
        db.close()


def test_claim_is_compare_and_swap_and_running_work_is_never_reclaimed(tmp_path):
    session_factory = _session_factory(tmp_path)
    dispatch_id, _, _, _ = _create_dispatch(session_factory)
    now = datetime(2026, 8, 19, 12, 0, 0)

    first = claim_ingestion_dispatch(
        dispatch_id,
        session_factory=session_factory,
        now=now,
        lease_seconds=10,
    )
    assert first is not None
    assert claim_ingestion_dispatch(
        dispatch_id,
        session_factory=session_factory,
        now=now,
    ) is None
    assert mark_ingestion_dispatch_running(
        first,
        session_factory=session_factory,
        now=now,
        lease_seconds=1,
    )
    assert claim_ingestion_dispatch(
        dispatch_id,
        session_factory=session_factory,
        now=now + timedelta(seconds=2),
    ) is None


def test_expired_prestart_claim_is_safe_to_reclaim(tmp_path):
    session_factory = _session_factory(tmp_path)
    dispatch_id, _, _, _ = _create_dispatch(session_factory)
    now = datetime(2026, 8, 19, 12, 0, 0)

    first = claim_ingestion_dispatch(
        dispatch_id,
        session_factory=session_factory,
        now=now,
        lease_seconds=1,
    )
    assert first is not None
    report = recover_ingestion_dispatches(
        session_factory=session_factory,
        now=now + timedelta(seconds=2),
    )
    assert report.ready_dispatch_ids == (dispatch_id,)

    second = claim_ingestion_dispatch(
        dispatch_id,
        session_factory=session_factory,
        now=now + timedelta(seconds=2),
    )
    assert second is not None
    assert second.claim_token != first.claim_token
    assert second.attempt_count == 2


def test_fresh_running_rows_do_not_starve_queued_work_at_recovery_limit(tmp_path):
    session_factory = _session_factory(tmp_path)
    now = datetime(2026, 8, 19, 12, 0, 0)
    running_id, _, _, _ = _create_dispatch(session_factory, now=now)
    queued_id, _, _, _ = _create_dispatch(
        session_factory,
        now=now + timedelta(seconds=1),
    )
    claim = claim_ingestion_dispatch(
        running_id,
        session_factory=session_factory,
        now=now,
    )
    assert claim is not None
    assert mark_ingestion_dispatch_running(
        claim,
        session_factory=session_factory,
        now=now,
        lease_seconds=300,
    )

    report = recover_ingestion_dispatches(
        session_factory=session_factory,
        now=now + timedelta(seconds=2),
        limit=1,
    )
    assert report.scanned == 1
    assert report.ready_dispatch_ids == (queued_id,)
    assert report.failed_running == 0


def test_stale_running_work_fails_instead_of_being_requeued(tmp_path):
    session_factory = _session_factory(tmp_path)
    dispatch_id, document_id, _, _ = _create_dispatch(session_factory)
    now = datetime(2026, 8, 19, 12, 0, 0)
    claim = claim_ingestion_dispatch(
        dispatch_id,
        session_factory=session_factory,
        now=now,
    )
    assert claim is not None
    assert mark_ingestion_dispatch_running(
        claim,
        session_factory=session_factory,
        now=now,
        lease_seconds=1,
    )

    report = recover_ingestion_dispatches(
        session_factory=session_factory,
        now=now + timedelta(seconds=2),
    )
    assert report.ready_dispatch_ids == ()
    assert report.failed_running == 1
    row = _row(session_factory, dispatch_id)
    assert row.status == "failed"
    status, error = _document_status(session_factory, document_id)
    assert status == "failed"
    assert "worker stopped" in (error or "").lower()


def test_pdf_runner_reconstructs_durable_ids_and_finishes_succeeded(tmp_path):
    session_factory = _session_factory(tmp_path)
    dispatch_id, document_id, source_file_id, payload = _create_dispatch(session_factory)
    captured = {}

    async def fake_pdf_processor(received_document_id, received_source_file_id, ids):
        captured["document_id"] = received_document_id
        captured["source_file_id"] = received_source_file_id
        captured["ids"] = ids
        _set_document_status(session_factory, received_document_id, "completed")

    assert asyncio.run(
        run_ingestion_dispatch(
            dispatch_id,
            session_factory=session_factory,
            pdf_processor=fake_pdf_processor,
        )
    )
    assert captured["document_id"] == document_id
    assert captured["source_file_id"] == source_file_id
    assert captured["ids"].processing_attempt_id == payload.processing_attempt_id
    assert captured["ids"].provider_job_id == payload.provider_job_id
    assert captured["ids"].provider_request_id == payload.provider_request_id
    row = _row(session_factory, dispatch_id)
    assert row.status == "succeeded"
    assert row.attempt_count == 1
    assert row.claim_token is None
    assert row.claim_expires_at is None


def test_txt_runner_reconstructs_durable_id_and_finishes_failed(tmp_path):
    session_factory = _session_factory(tmp_path)
    dispatch_id, document_id, source_file_id, payload = _create_dispatch(
        session_factory,
        kind="txt",
    )
    captured = {}

    def fake_txt_processor(received_document_id, received_source_file_id, ids):
        captured["document_id"] = received_document_id
        captured["source_file_id"] = received_source_file_id
        captured["ids"] = ids
        _set_document_status(
            session_factory,
            received_document_id,
            "failed",
            "fixture failure",
        )

    assert asyncio.run(
        run_ingestion_dispatch(
            dispatch_id,
            session_factory=session_factory,
            txt_processor=fake_txt_processor,
        )
    )
    assert captured["document_id"] == document_id
    assert captured["source_file_id"] == source_file_id
    assert captured["ids"].processing_run_ref == payload.txt_processing_run_ref
    row = _row(session_factory, dispatch_id)
    assert row.status == "failed"
    assert row.error_message == "fixture failure"


def test_lost_running_claim_fences_late_worker_success(tmp_path):
    session_factory = _session_factory(tmp_path)
    dispatch_id, document_id, _, _ = _create_dispatch(session_factory)
    future = datetime.utcnow() + timedelta(hours=1)

    async def fake_pdf_processor(received_document_id, _source_file_id, _ids):
        report = recover_ingestion_dispatches(
            session_factory=session_factory,
            now=future,
        )
        assert report.failed_running == 1
        # Simulate a stalled old worker returning after recovery already fenced it.
        _set_document_status(session_factory, received_document_id, "completed")

    assert asyncio.run(
        run_ingestion_dispatch(
            dispatch_id,
            session_factory=session_factory,
            pdf_processor=fake_pdf_processor,
        )
    )
    row = _row(session_factory, dispatch_id)
    assert row.status == "failed"
    status, error = _document_status(session_factory, document_id)
    assert status == "failed"
    assert "claim" in (error or "").lower() or "worker stopped" in (error or "").lower()
