"""Durable initial-ingestion dispatch state machine.

The HTTP acceptance transaction owns creating an IngestionDispatch row alongside
Document/SourceFile. Immediate BackgroundTasks are only a latency optimization:
startup/periodic recovery can see queued durable work and safely kick it again.

Only work that has *not* entered ``running`` is automatically reclaimable. Once
a processor starts, an expired running lease is failed conservatively instead of
blindly re-running potentially partial OCR/canonicalization work.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import logging
from typing import Callable
import uuid

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Document
from app.processing.ingestion_dispatch_model import IngestionDispatch
from app.storage.models import StorageReference

logger = logging.getLogger("uvicorn.error")

DISPATCH_PRESTART_LEASE_SECONDS = 300
DISPATCH_RUNNING_LEASE_SECONDS = 300
DISPATCH_HEARTBEAT_SECONDS = 60
DISPATCH_RECOVERY_LIMIT = 32


@dataclass(frozen=True, slots=True)
class DispatchPayload:
    kind: str
    processing_attempt_id: str | None = None
    provider_job_id: str | None = None
    provider_request_id: str | None = None
    txt_processing_run_ref: str | None = None


@dataclass(frozen=True, slots=True)
class DispatchClaim:
    dispatch_id: str
    acceptance_key: str
    document_id: str
    source_file_id: str
    claim_token: str
    attempt_count: int
    payload: DispatchPayload


@dataclass(frozen=True, slots=True)
class DispatchRecoveryReport:
    scanned: int
    ready_dispatch_ids: tuple[str, ...]
    failed_running: int
    skipped_fresh: int
    errors: int


def utcnow() -> datetime:
    return datetime.utcnow()


def stable_storage_reference(acceptance_key: str) -> StorageReference:
    """Derive one opaque retained-source ref from one durable acceptance key."""
    normalized = str(acceptance_key).strip()
    if not normalized:
        raise ValueError("acceptance_key is required")
    token = hashlib.sha256(f"atlas-book-source:{normalized}".encode("utf-8")).hexdigest()[:32]
    return StorageReference.parse(f"src_{token}")


def new_dispatch_payload(kind: str) -> DispatchPayload:
    token = uuid.uuid4().hex
    if kind == "pdf":
        return DispatchPayload(
            kind="pdf",
            processing_attempt_id=f"pdf-ingest-{token}",
            provider_job_id=f"pdf-job-{token}",
            provider_request_id=f"pdf-request-{token}",
        )
    if kind == "txt":
        return DispatchPayload(
            kind="txt",
            txt_processing_run_ref=f"txt-ingest-{token}",
        )
    raise ValueError("dispatch kind must be pdf or txt")


def create_ingestion_dispatch(
    db: Session,
    *,
    acceptance_key: str,
    document_id: str,
    source_file_id: str,
    payload: DispatchPayload,
    dispatch_id: str | None = None,
    now: datetime | None = None,
) -> IngestionDispatch:
    """Stage a queued dispatch in the caller-owned acceptance transaction."""
    normalized_key = str(acceptance_key).strip()
    if not normalized_key:
        raise ValueError("acceptance_key is required")
    timestamp = now or utcnow()
    row = IngestionDispatch(
        id=dispatch_id or str(uuid.uuid4()),
        acceptance_key=normalized_key,
        document_id=document_id,
        source_file_id=source_file_id,
        kind=payload.kind,
        processing_attempt_id=payload.processing_attempt_id,
        provider_job_id=payload.provider_job_id,
        provider_request_id=payload.provider_request_id,
        txt_processing_run_ref=payload.txt_processing_run_ref,
        status="queued",
        claim_token=None,
        claim_expires_at=None,
        attempt_count=0,
        error_message=None,
        created_at=timestamp,
        updated_at=timestamp,
        started_at=None,
        finished_at=None,
    )
    db.add(row)
    return row


def get_dispatch_by_acceptance_key(
    db: Session,
    acceptance_key: str,
) -> IngestionDispatch | None:
    return db.execute(
        select(IngestionDispatch).where(
            IngestionDispatch.acceptance_key == str(acceptance_key).strip()
        )
    ).scalar_one_or_none()


def _payload_from_row(row: IngestionDispatch) -> DispatchPayload:
    return DispatchPayload(
        kind=row.kind,
        processing_attempt_id=row.processing_attempt_id,
        provider_job_id=row.provider_job_id,
        provider_request_id=row.provider_request_id,
        txt_processing_run_ref=row.txt_processing_run_ref,
    )


def claim_ingestion_dispatch(
    dispatch_id: str,
    *,
    session_factory=SessionLocal,
    now: datetime | None = None,
    lease_seconds: int = DISPATCH_PRESTART_LEASE_SECONDS,
) -> DispatchClaim | None:
    """CAS-claim queued or expired-prestart work; running work is never reclaimed."""
    timestamp = now or utcnow()
    token = uuid.uuid4().hex
    expires_at = timestamp + timedelta(seconds=max(1, int(lease_seconds)))
    db = session_factory()
    try:
        result = db.execute(
            update(IngestionDispatch)
            .where(IngestionDispatch.id == dispatch_id)
            .where(
                or_(
                    IngestionDispatch.status == "queued",
                    and_(
                        IngestionDispatch.status == "claimed",
                        IngestionDispatch.claim_expires_at.is_not(None),
                        IngestionDispatch.claim_expires_at < timestamp,
                    ),
                )
            )
            .values(
                status="claimed",
                claim_token=token,
                claim_expires_at=expires_at,
                attempt_count=IngestionDispatch.attempt_count + 1,
                updated_at=timestamp,
                error_message=None,
            )
        )
        if result.rowcount != 1:
            db.rollback()
            return None
        db.commit()
        row = db.get(IngestionDispatch, dispatch_id)
        if row is None or row.claim_token != token or row.status != "claimed":
            raise RuntimeError("claimed dispatch disappeared before snapshot")
        return DispatchClaim(
            dispatch_id=row.id,
            acceptance_key=row.acceptance_key,
            document_id=row.document_id,
            source_file_id=row.source_file_id,
            claim_token=token,
            attempt_count=int(row.attempt_count),
            payload=_payload_from_row(row),
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def mark_ingestion_dispatch_running(
    claim: DispatchClaim,
    *,
    session_factory=SessionLocal,
    now: datetime | None = None,
    lease_seconds: int = DISPATCH_RUNNING_LEASE_SECONDS,
) -> bool:
    timestamp = now or utcnow()
    expires_at = timestamp + timedelta(seconds=max(1, int(lease_seconds)))
    db = session_factory()
    try:
        result = db.execute(
            update(IngestionDispatch)
            .where(
                IngestionDispatch.id == claim.dispatch_id,
                IngestionDispatch.status == "claimed",
                IngestionDispatch.claim_token == claim.claim_token,
            )
            .values(
                status="running",
                started_at=timestamp,
                claim_expires_at=expires_at,
                updated_at=timestamp,
            )
        )
        db.commit()
        return result.rowcount == 1
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def heartbeat_ingestion_dispatch(
    claim: DispatchClaim,
    *,
    session_factory=SessionLocal,
    now: datetime | None = None,
    lease_seconds: int = DISPATCH_RUNNING_LEASE_SECONDS,
) -> bool:
    timestamp = now or utcnow()
    expires_at = timestamp + timedelta(seconds=max(1, int(lease_seconds)))
    db = session_factory()
    try:
        result = db.execute(
            update(IngestionDispatch)
            .where(
                IngestionDispatch.id == claim.dispatch_id,
                IngestionDispatch.status == "running",
                IngestionDispatch.claim_token == claim.claim_token,
            )
            .values(
                claim_expires_at=expires_at,
                updated_at=timestamp,
            )
        )
        db.commit()
        return result.rowcount == 1
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _finish_claim(
    claim: DispatchClaim,
    *,
    status: str,
    error_message: str | None,
    session_factory=SessionLocal,
    now: datetime | None = None,
) -> bool:
    if status not in {"succeeded", "failed"}:
        raise ValueError("terminal dispatch status must be succeeded or failed")
    timestamp = now or utcnow()
    db = session_factory()
    try:
        result = db.execute(
            update(IngestionDispatch)
            .where(
                IngestionDispatch.id == claim.dispatch_id,
                IngestionDispatch.status.in_(("claimed", "running")),
                IngestionDispatch.claim_token == claim.claim_token,
            )
            .values(
                status=status,
                claim_token=None,
                claim_expires_at=None,
                finished_at=timestamp,
                updated_at=timestamp,
                error_message=error_message,
            )
        )
        db.commit()
        return result.rowcount == 1
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _set_processing_document_failed(
    db: Session,
    document_id: str,
    message: str,
) -> None:
    document = db.get(Document, document_id)
    if document is not None and document.status == "processing":
        document.status = "failed"
        document.error_message = message
        document.original_file_path = None
        document.processed_file_path = None


def _document_status(
    document_id: str,
    *,
    session_factory=SessionLocal,
) -> tuple[str | None, str | None]:
    db = session_factory()
    try:
        document = db.get(Document, document_id)
        if document is None:
            return None, "Accepted document is unavailable"
        return str(document.status), document.error_message
    finally:
        db.close()


def finalize_dispatch_from_document(
    claim: DispatchClaim,
    *,
    session_factory=SessionLocal,
) -> bool:
    status, error_message = _document_status(
        claim.document_id,
        session_factory=session_factory,
    )
    if status == "completed":
        return _finish_claim(
            claim,
            status="succeeded",
            error_message=None,
            session_factory=session_factory,
        )
    if status == "failed":
        return _finish_claim(
            claim,
            status="failed",
            error_message=error_message or "Ingestion worker failed",
            session_factory=session_factory,
        )

    message = (
        "Ingestion worker returned without a terminal document state"
        if status is not None
        else "Accepted document disappeared during ingestion"
    )
    db = session_factory()
    try:
        _set_processing_document_failed(db, claim.document_id, message)
        result = db.execute(
            update(IngestionDispatch)
            .where(
                IngestionDispatch.id == claim.dispatch_id,
                IngestionDispatch.status.in_(("claimed", "running")),
                IngestionDispatch.claim_token == claim.claim_token,
            )
            .values(
                status="failed",
                claim_token=None,
                claim_expires_at=None,
                finished_at=utcnow(),
                updated_at=utcnow(),
                error_message=message,
            )
        )
        db.commit()
        return result.rowcount == 1
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def _dispatch_heartbeat_loop(
    claim: DispatchClaim,
    stop_event: asyncio.Event,
    *,
    session_factory=SessionLocal,
) -> None:
    while True:
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=DISPATCH_HEARTBEAT_SECONDS,
            )
            return
        except asyncio.TimeoutError:
            pass
        try:
            alive = await asyncio.to_thread(
                heartbeat_ingestion_dispatch,
                claim,
                session_factory=session_factory,
            )
        except Exception:
            logger.exception(
                "Ingestion dispatch heartbeat failed open dispatch_id=%s document_id=%s",
                claim.dispatch_id,
                claim.document_id,
            )
            continue
        if not alive:
            logger.warning(
                "Ingestion dispatch heartbeat lost claim dispatch_id=%s document_id=%s",
                claim.dispatch_id,
                claim.document_id,
            )
            return


async def run_ingestion_dispatch(
    dispatch_id: str,
    *,
    session_factory=SessionLocal,
    pdf_processor: Callable | None = None,
    txt_processor: Callable | None = None,
) -> bool:
    """Claim and execute one durable dispatch; duplicate kicks collapse at CAS claim."""
    claim = await asyncio.to_thread(
        claim_ingestion_dispatch,
        dispatch_id,
        session_factory=session_factory,
    )
    if claim is None:
        return False

    document_status, document_error = await asyncio.to_thread(
        _document_status,
        claim.document_id,
        session_factory=session_factory,
    )
    if document_status in {"completed", "failed"}:
        await asyncio.to_thread(
            _finish_claim,
            claim,
            status=("succeeded" if document_status == "completed" else "failed"),
            error_message=(None if document_status == "completed" else document_error),
            session_factory=session_factory,
        )
        return True

    started = await asyncio.to_thread(
        mark_ingestion_dispatch_running,
        claim,
        session_factory=session_factory,
    )
    if not started:
        return False

    stop_event = asyncio.Event()
    heartbeat_task = asyncio.create_task(
        _dispatch_heartbeat_loop(
            claim,
            stop_event,
            session_factory=session_factory,
        ),
        name=f"ingestion-dispatch-heartbeat:{dispatch_id}",
    )
    try:
        if claim.payload.kind == "pdf":
            if pdf_processor is None:
                from app.processing.pdf_ingestion import PdfIngestionIds, process_pdf_document_background

                pdf_processor = process_pdf_document_background
            else:
                from app.processing.pdf_ingestion import PdfIngestionIds
            ids = PdfIngestionIds(
                processing_attempt_id=str(claim.payload.processing_attempt_id),
                provider_job_id=str(claim.payload.provider_job_id),
                provider_request_id=str(claim.payload.provider_request_id),
            )
            await pdf_processor(
                claim.document_id,
                claim.source_file_id,
                ids,
            )
        elif claim.payload.kind == "txt":
            if txt_processor is None:
                from app.processing.txt.ingestion import TxtIngestionIds, process_txt_document_background

                txt_processor = process_txt_document_background
            else:
                from app.processing.txt.ingestion import TxtIngestionIds
            ids = TxtIngestionIds(
                processing_run_ref=str(claim.payload.txt_processing_run_ref),
            )
            await asyncio.to_thread(
                txt_processor,
                claim.document_id,
                claim.source_file_id,
                ids,
            )
        else:  # database check constraint should make this unreachable
            raise RuntimeError("Unsupported durable ingestion dispatch kind")
    except asyncio.CancelledError:
        # Preserve running+lease state. If the process is actually disappearing,
        # the lease will expire and recovery will fail it conservatively. If a
        # caller merely cancels this coroutine while the process lives, it must
        # not silently re-run potentially partial processing.
        raise
    except Exception as exc:
        logger.exception(
            "Durable ingestion dispatch failed dispatch_id=%s document_id=%s",
            claim.dispatch_id,
            claim.document_id,
        )
        message = "Ingestion dispatch failed before document processing became ready"
        db = session_factory()
        try:
            _set_processing_document_failed(db, claim.document_id, message)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception(
                "Could not persist durable dispatch failure document_id=%s",
                claim.document_id,
            )
        finally:
            db.close()
        await asyncio.to_thread(
            _finish_claim,
            claim,
            status="failed",
            error_message=message,
            session_factory=session_factory,
        )
        return True
    finally:
        stop_event.set()
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass

    await asyncio.to_thread(
        finalize_dispatch_from_document,
        claim,
        session_factory=session_factory,
    )
    return True


def recover_ingestion_dispatches(
    *,
    session_factory=SessionLocal,
    now: datetime | None = None,
    limit: int = DISPATCH_RECOVERY_LIMIT,
) -> DispatchRecoveryReport:
    """Discover safe pre-start work and fail expired work that had already started."""
    timestamp = now or utcnow()
    db = session_factory()
    ready: list[str] = []
    scanned = 0
    failed_running = 0
    skipped_fresh = 0
    errors = 0
    try:
        rows = db.execute(
            select(IngestionDispatch)
            .where(IngestionDispatch.status.in_(("queued", "claimed", "running")))
            .order_by(IngestionDispatch.created_at.asc(), IngestionDispatch.id.asc())
            .limit(max(1, int(limit)))
        ).scalars().all()
        scanned = len(rows)
        for row in rows:
            try:
                if row.status == "queued":
                    ready.append(row.id)
                    continue
                if row.claim_expires_at is None or row.claim_expires_at >= timestamp:
                    skipped_fresh += 1
                    continue
                if row.status == "claimed":
                    # Claim CAS itself knows how to reclaim expired pre-start work.
                    ready.append(row.id)
                    continue

                message = "Processing worker stopped after durable ingestion dispatch started"
                result = db.execute(
                    update(IngestionDispatch)
                    .where(
                        IngestionDispatch.id == row.id,
                        IngestionDispatch.status == "running",
                        IngestionDispatch.claim_expires_at.is_not(None),
                        IngestionDispatch.claim_expires_at < timestamp,
                    )
                    .values(
                        status="failed",
                        claim_token=None,
                        claim_expires_at=None,
                        finished_at=timestamp,
                        updated_at=timestamp,
                        error_message=message,
                    )
                )
                if result.rowcount == 1:
                    _set_processing_document_failed(db, row.document_id, message)
                    failed_running += 1
                else:
                    skipped_fresh += 1
            except Exception:
                errors += 1
                logger.exception(
                    "Durable ingestion dispatch recovery failed open dispatch_id=%s",
                    row.id,
                )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return DispatchRecoveryReport(
        scanned=scanned,
        ready_dispatch_ids=tuple(ready),
        failed_running=failed_running,
        skipped_fresh=skipped_fresh,
        errors=errors,
    )


__all__ = [
    "DISPATCH_HEARTBEAT_SECONDS",
    "DISPATCH_PRESTART_LEASE_SECONDS",
    "DISPATCH_RECOVERY_LIMIT",
    "DISPATCH_RUNNING_LEASE_SECONDS",
    "DispatchClaim",
    "DispatchPayload",
    "DispatchRecoveryReport",
    "claim_ingestion_dispatch",
    "create_ingestion_dispatch",
    "finalize_dispatch_from_document",
    "get_dispatch_by_acceptance_key",
    "heartbeat_ingestion_dispatch",
    "mark_ingestion_dispatch_running",
    "new_dispatch_payload",
    "recover_ingestion_dispatches",
    "run_ingestion_dispatch",
    "stable_storage_reference",
]
