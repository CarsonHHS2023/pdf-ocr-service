"""Recover stale S0 PDF ProcessingRun rows after worker/container loss.

ProcessingRun is durable provenance rather than queue truth.  The current PDF
runtime is nevertheless in-process, so a container restart can leave a run in
``running`` and its Document in ``processing`` forever.  This recovery uses the
durable S0 heartbeat as a conservative lease: only S0 PDF runs whose last
durable activity is older than the configured stale window are failed.

The recovery deliberately does not alter OCR/provider policy and does not try
to resume work.  It only converges business/provenance state after the worker
that owned the in-process attempt is no longer making progress.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any, Callable

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Document, ProcessingRun, decode_json_text, encode_json_text

logger = logging.getLogger("uvicorn.error")

S0_PDF_PROCESSING_POLICY_REF = "pdf-ingestion-s0-observability"
STALE_PROCESSING_RUN_SECONDS = 300.0
PROCESSING_WORKER_LOST_CODE = "processing_worker_lost"
PROCESSING_WORKER_LOST_SUMMARY = (
    "PDF processing worker stopped before the document became ready; retry the document"
)
RECOVERY_VERSION = "atlas-s0-stale-run-recovery-v1"


@dataclass(frozen=True, slots=True)
class StaleProcessingRunRecoveryReport:
    scanned: int = 0
    recovered: int = 0
    skipped_fresh: int = 0
    skipped_non_processing_document: int = 0
    errors: int = 0


def _utcnow_naive() -> datetime:
    return datetime.utcnow()


def _as_utc_naive(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _as_utc_iso(value: datetime) -> str:
    normalized = _as_utc_naive(value)
    if normalized is None:  # pragma: no cover - datetime input is always valid
        normalized = value
    return normalized.replace(tzinfo=timezone.utc).isoformat()


def _decode_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        decoded = decode_json_text(value)
    except Exception:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _last_activity_at(run: ProcessingRun) -> datetime | None:
    """Return the newest trustworthy durable activity timestamp for one run."""
    candidates: list[datetime] = []

    extensions = _decode_object(run.extensions_json)
    heartbeat = extensions.get("s0_resource_heartbeat")
    if isinstance(heartbeat, dict):
        latest = heartbeat.get("latest")
        if isinstance(latest, dict):
            parsed = _as_utc_naive(latest.get("at"))
            if parsed is not None:
                candidates.append(parsed)

    metrics = _decode_object(run.metrics_json)
    resource = metrics.get("s0_resource")
    if isinstance(resource, dict):
        parsed = _as_utc_naive(resource.get("last_heartbeat_at"))
        if parsed is not None:
            candidates.append(parsed)

    for fallback in (run.started_at, run.created_at):
        parsed = _as_utc_naive(fallback)
        if parsed is not None:
            candidates.append(parsed)

    return max(candidates) if candidates else None


def _append_recovery_metadata(
    run: ProcessingRun,
    *,
    recovered_at: datetime,
    last_activity_at: datetime,
    stale_after_seconds: float,
) -> None:
    extensions = _decode_object(run.extensions_json)
    # Preserve the entire heartbeat/checkpoint object. Recovery metadata is a
    # sibling so the evidence used to classify the stale attempt remains intact.
    extensions["s0_recovery"] = {
        "version": RECOVERY_VERSION,
        "recovered_at": _as_utc_iso(recovered_at),
        "reason": "stale_heartbeat_lease_expired",
        "stale_after_seconds": float(stale_after_seconds),
        "last_activity_at": _as_utc_iso(last_activity_at),
    }
    run.extensions_json = encode_json_text(extensions)


def recover_stale_s0_pdf_processing_runs(
    *,
    session_factory: Callable[[], object] | None = None,
    now: datetime | None = None,
    stale_after_seconds: float = STALE_PROCESSING_RUN_SECONDS,
) -> StaleProcessingRunRecoveryReport:
    """Fail stale S0 PDF attempts and their still-processing Documents.

    Discovery and each recovery use separate transactions. Each candidate is
    re-read under a row lock before mutation so another startup/worker can win a
    race by updating the run first. Failures are isolated per run and reported;
    callers may safely continue serving traffic.
    """
    factory = session_factory or SessionLocal
    now_utc = _as_utc_naive(now or _utcnow_naive()) or _utcnow_naive()
    stale_window = max(1.0, float(stale_after_seconds))

    try:
        discovery = factory()
        try:
            candidate_ids = tuple(
                discovery.execute(
                    select(ProcessingRun.processing_run_id)
                    .where(
                        ProcessingRun.processing_policy_ref == S0_PDF_PROCESSING_POLICY_REF,
                        ProcessingRun.status.in_(("created", "running")),
                    )
                    .order_by(ProcessingRun.created_at, ProcessingRun.processing_run_id)
                ).scalars().all()
            )
        finally:
            discovery.close()
    except Exception:
        logger.exception("S0 stale ProcessingRun discovery failed open")
        return StaleProcessingRunRecoveryReport(errors=1)

    recovered = 0
    skipped_fresh = 0
    skipped_non_processing = 0
    errors = 0

    for processing_run_id in candidate_ids:
        db = factory()
        try:
            run = db.execute(
                select(ProcessingRun)
                .where(ProcessingRun.processing_run_id == processing_run_id)
                .with_for_update()
            ).scalar_one_or_none()
            if (
                run is None
                or run.processing_policy_ref != S0_PDF_PROCESSING_POLICY_REF
                or run.status not in {"created", "running"}
            ):
                skipped_fresh += 1
                db.rollback()
                continue

            last_activity = _last_activity_at(run)
            if last_activity is None:
                # ProcessingRun.created_at is non-null in the schema, but fail
                # closed to preservation if a corrupt legacy row lacks any time.
                skipped_fresh += 1
                db.rollback()
                continue

            stale_seconds = (now_utc - last_activity).total_seconds()
            if stale_seconds < stale_window:
                skipped_fresh += 1
                db.rollback()
                continue

            document = db.get(Document, run.document_id)
            if document is None or document.status != "processing":
                # Do not downgrade completed/failed business truth. A later
                # reconciliation slice can handle inconsistent terminal pairs.
                skipped_non_processing += 1
                db.rollback()
                continue

            run.status = "failed"
            run.failed_at = now_utc
            run.safe_error_code = PROCESSING_WORKER_LOST_CODE
            run.safe_error_summary = PROCESSING_WORKER_LOST_SUMMARY
            _append_recovery_metadata(
                run,
                recovered_at=now_utc,
                last_activity_at=last_activity,
                stale_after_seconds=stale_window,
            )

            document.status = "failed"
            document.error_message = PROCESSING_WORKER_LOST_SUMMARY
            db.commit()
            recovered += 1
            logger.warning(
                "PDF_S0_STALE_PROCESSING_RUN_RECOVERED processing_run_id=%s "
                "document_id=%s last_activity_at=%s stale_seconds=%.1f",
                processing_run_id,
                run.document_id,
                _as_utc_iso(last_activity),
                stale_seconds,
            )
        except Exception:
            errors += 1
            db.rollback()
            logger.exception(
                "S0 stale ProcessingRun recovery failed open processing_run_id=%s",
                processing_run_id,
            )
        finally:
            db.close()

    return StaleProcessingRunRecoveryReport(
        scanned=len(candidate_ids),
        recovered=recovered,
        skipped_fresh=skipped_fresh,
        skipped_non_processing_document=skipped_non_processing,
        errors=errors,
    )


__all__ = [
    "PROCESSING_WORKER_LOST_CODE",
    "PROCESSING_WORKER_LOST_SUMMARY",
    "RECOVERY_VERSION",
    "S0_PDF_PROCESSING_POLICY_REF",
    "STALE_PROCESSING_RUN_SECONDS",
    "StaleProcessingRunRecoveryReport",
    "recover_stale_s0_pdf_processing_runs",
]
