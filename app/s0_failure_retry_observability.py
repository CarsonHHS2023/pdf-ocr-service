"""S0.3.6 staging-only counters; no new retries, per-call SQL, or raw diagnostics.

One root manifest covers all dispatched orchestration scopes, including shards.
Start is durable before work; all bounded summaries + terminal commit atomically.
Crash/overflow/persistence loss cannot produce a complete zero-failure manifest.
"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
import hashlib
import uuid

from app.s0_failure_retry_metrics import (
    COUNTERS, OPERATIONS, MAX_COUNT, MAX_SCOPES, MEASUREMENT_SCOPE,
    START_EVENT, SCOPE_EVENT, TERMINAL_EVENT, PROVIDER_STATES,
)
from app.s0_provider_source_download_observability import provider_scope_id

_ROOT = ContextVar("s0_failure_retry_root", default=None)
_SCOPE = ContextVar("s0_failure_retry_scope", default=None)


def source_scope_id(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 255:
        return None
    return "source_" + hashlib.sha256(value.encode()).hexdigest()[:16]


def _revision():
    from app.s0_object_store_io_observability import _STAGING_REVISION_FILE, _REVISION_RE
    from app.processing.processing_events import staging_processing_events_enabled
    try:
        revision = _STAGING_REVISION_FILE.read_text(encoding="utf-8").strip()
        return revision if _REVISION_RE.fullmatch(revision) and staging_processing_events_enabled() else None
    except Exception:
        return None


@dataclass
class Run:
    run_id: str
    document_id: str
    source_id: str
    revision: str
    scope_id: str = field(default_factory=lambda: "attempts_" + uuid.uuid4().hex)
    scopes: list = field(default_factory=list)
    complete: bool = True
    outcome: str = "unknown"

    def common(self):
        return {"measurement_scope": MEASUREMENT_SCOPE, "run_scope_id": self.scope_id,
                "source_scope_id": source_scope_id(self.source_id), "backend_revision": self.revision}

    def closed_events(self):
        return [(SCOPE_EVENT, {**self.common(), **s}) for s in self.scopes] + [(TERMINAL_EVENT, {
            **self.common(), "scope_count": len(self.scopes), "outcome": self.outcome,
            "complete": self.complete and self.outcome != "unknown"})]


def _persist(run, events, *, session_factory=None):
    """Worker owns its session; events may precede ProcessingRun initialization."""
    try:
        revision = _revision()
        if revision is None or revision != run.revision:
            return False
        from app.database import SessionLocal
        from sqlalchemy import select
        from app.models import SourceFile, ProcessingRun, encode_json_text
        from app.processing.processing_event_model import ProcessingEvent
        from app.processing.processing_events import (
            PROCESSING_EVENT_SCHEMA_VERSION, sanitize_processing_event_payload, MAX_EVENT_PAYLOAD_BYTES,
        )
        if any(not isinstance(v, str) or not 1 <= len(v) <= 255 for v in (run.run_id, run.document_id, run.source_id)):
            return False
        rows = []
        for name, payload in events:
            cleaned = sanitize_processing_event_payload(payload)
            encoded = encode_json_text(cleaned)
            if cleaned != payload or len(encoded.encode()) > MAX_EVENT_PAYLOAD_BYTES:
                return False
            rows.append(ProcessingEvent(processing_run_id=run.run_id, document_id=run.document_id,
                schema_version=PROCESSING_EVENT_SCHEMA_VERSION, event_name=name, severity="info", payload_json=encoded))
        with (session_factory or SessionLocal)() as db:
            with db.begin():
                source_document_id = db.execute(select(SourceFile.document_id).where(SourceFile.id == run.source_id)).scalar_one_or_none()
                existing = db.execute(select(ProcessingRun.document_id, ProcessingRun.source_file_id)
                    .where(ProcessingRun.processing_run_id == run.run_id)).one_or_none()
                if source_document_id != run.document_id:
                    return False
                if existing is not None and (existing.document_id != run.document_id or existing.source_file_id != run.source_id):
                    return False
                db.add_all(rows)
        return True
    except Exception:
        return False


async def _publish(run, events):
    try:
        return await asyncio.to_thread(_persist, run, events)
    except Exception:
        return False


async def observe_pdf_processing(delegate, document_id, source_file_id, ids):
    revision = _revision()
    if revision is None:
        return await delegate(document_id, source_file_id, ids)
    run = Run(ids.processing_attempt_id, document_id, source_file_id, revision)
    started = await _publish(run, [(START_EVENT, run.common())])
    token = _ROOT.set(run)
    try:
        return await delegate(document_id, source_file_id, ids)
    except asyncio.CancelledError:
        run.outcome = "cancelled"
        raise
    except Exception:
        run.outcome = "failed"
        raise
    finally:
        _ROOT.reset(token)
        if started:
            await _publish(run, run.closed_events())


def note_pdf_terminal(document_id, status):
    """Called only after the existing terminal-state transaction committed."""
    run = _ROOT.get()
    if run is not None and document_id == run.document_id and status in ("completed", "failed"):
        run.outcome = status


async def observe_orchestration(delegate, request, policy):
    run = _ROOT.get()
    if run is None:
        return await delegate(request, policy)
    if ((request.processing_attempt_id, request.document_id, request.source_file_id)
            != (run.run_id, run.document_id, run.source_id) or len(run.scopes) >= MAX_SCOPES):
        run.complete = False
        token = _SCOPE.set(None)
        try:
            return await delegate(request, policy)
        finally:
            _SCOPE.reset(token)
    scope = {"ordinal": len(run.scopes) + 1, "provider_scope_id": provider_scope_id(request.provider_job_id),
             "outcome": "unknown", "provider_terminal_status": "unknown",
             "operations": {op: dict.fromkeys(COUNTERS, 0) for op in OPERATIONS}}
    run.scopes.append(scope)
    # Pending retry state stays in memory, never inferred from diagnostic logs.
    token = _SCOPE.set((run, scope, {}, request.provider_job_id))
    try:
        result = await delegate(request, policy)
        scope["outcome"] = "completed" if result.succeeded else "failed"
        return result
    except asyncio.CancelledError:
        scope["outcome"] = "cancelled"
        raise
    except Exception:
        scope["outcome"] = "failed"
        raise
    finally:
        _SCOPE.reset(token)


async def observe_provider_call(operation, delegate, *args):
    current = _SCOPE.get()
    if current is None:
        return await delegate(*args)
    from app.processing.errors import ProviderClientError, ProviderErrorCategory
    run, scope, pending, job_id = current
    counts = scope["operations"][operation]
    counts["attempts"] += 1
    if pending.pop(operation, False):
        counts["retries"] += 1
    if counts["attempts"] > MAX_COUNT:
        run.complete = False
    try:
        result = await delegate(*args)
    except asyncio.CancelledError:
        counts["cancelled"] += 1
        raise
    except ProviderClientError as exc:
        if operation == "result" and exc.detail.category == ProviderErrorCategory.RESULT_NOT_READY:
            counts["not_ready"] += 1
        else:
            counts["failed"] += 1
            if exc.detail.retryable:
                counts["retryable_failures"] += 1
            pending[operation] = (operation in ("status", "result") and exc.detail.retryable
                and exc.detail.category in (ProviderErrorCategory.TIMEOUT, ProviderErrorCategory.UNAVAILABLE))
        raise
    except Exception:
        counts["failed"] += 1
        raise
    else:
        counts["succeeded"] += 1
        state = getattr(getattr(result, "status", None), "value", None)
        if getattr(result, "job_id", None) == job_id and state in PROVIDER_STATES:
            scope["provider_terminal_status"] = state
        return result


def install_pdf_observability():
    from app.processing import pdf_ingestion
    original = pdf_ingestion.process_pdf_document_background
    if getattr(original, "_s036_installed", False):
        return

    @wraps(original)
    async def observed(document_id, source_file_id, ids):
        return await observe_pdf_processing(original, document_id, source_file_id, ids)

    observed._s036_installed = True
    pdf_ingestion.process_pdf_document_background = observed
