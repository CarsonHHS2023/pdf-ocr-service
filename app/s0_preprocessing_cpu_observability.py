"""Staging-only worker CPU evidence; no workflow state, retries or PDF ownership."""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
import math
import re
from threading import Lock, get_ident
import time
import uuid

from app import s0_preprocessing_cpu_metrics as contract

_ROOT = ContextVar("s0_worker_cpu_root", default=None)
_REQUEST = ContextVar("s0_worker_cpu_request", default=None)
_WORKER = ContextVar("s0_worker_cpu_worker", default=None)


def _safe(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception:
        return None


def _revision():
    from app.processing import processing_events
    try:
        value = processing_events._STAGING_REVISION_FILE.read_text(encoding="utf-8").strip()
        return value if re.fullmatch(r"[0-9a-f]{40}", value) else None
    except Exception:
        return None


@dataclass
class Scope:
    root: Root
    index: int
    scope_id: str = field(default_factory=lambda: "pcpu_" + uuid.uuid4().hex)
    submitted: bool = False
    submit_failed: bool = False
    entered: bool = False
    measurement: dict | None = None
    terminal: dict | None = None

    def common(self):
        return {**self.root.common(), "scope_index": self.index, "scope_id": self.scope_id}


@dataclass
class Root:
    run_id: str
    document_id: str
    source_id: str
    revision: str
    scope_id: str = field(default_factory=lambda: "cpu_" + uuid.uuid4().hex)
    lock: object = field(default_factory=Lock)
    scopes: list = field(default_factory=list)
    closed: bool = False
    claimed: bool = False
    invalidation_claimed: bool = False
    invalidation_pending: bool = False
    invalidation_issue: str = "protocol_violation"
    issue: str = "none"
    outcome: str = "unknown"

    def common(self):
        return {"contract_version": contract.VERSION, "method": contract.METHOD,
                "measurement_scope": "worker_thread_only", "run_scope_id": self.scope_id,
                "source_scope_id": contract.source_scope_id(self.source_id), "backend_revision": self.revision}

    def _issue(self, reason):
        if self.issue == "none":
            self.issue = reason

    def _invalidate(self, reason):
        if self.claimed and not self.invalidation_pending:
            self.invalidation_pending = True
            self.invalidation_issue = reason

    def problem(self, reason):
        with self.lock:
            self._issue(reason)
            if reason in {"protocol_violation", "persistence_loss"}:
                self._invalidate(reason)

    def register(self):
        with self.lock:
            if self.closed:
                self._issue("protocol_violation")
                self._invalidate("protocol_violation")
                return None
            if len(self.scopes) >= contract.MAX_SCOPES:
                self._issue("scope_overflow")
                return None
            scope = Scope(self, len(self.scopes) + 1)
            self.scopes.append(scope)
            return scope

    def settle(self, scope, values):
        with self.lock:
            if scope.terminal is not None:
                if scope.terminal != values:
                    self._issue("protocol_violation")
                    self._invalidate("protocol_violation")
                return
            scope.terminal = dict(values)

    def seal(self):
        with self.lock:
            self.closed = True
            if self.outcome == "unknown":
                self._issue("logical_terminal_unknown")

    def _claim_invalidation(self):
        if self.invalidation_pending and not self.invalidation_claimed:
            self.invalidation_claimed = True
            return [(contract.INVALID, {**self.common(), "ordinal": 18,
                                        "issue": self.invalidation_issue})]
        return []

    def claim_invalidation(self):
        with self.lock:
            return self._claim_invalidation()

    def claim(self):
        with self.lock:
            invalidation = self._claim_invalidation()
            if invalidation:
                return invalidation
            if self.claimed or not self.closed or any(s.terminal is None for s in self.scopes):
                return []
            self.claimed = True
            rows = [(contract.SCOPE_END, {**s.common(), "ordinal": 2 * s.index, **s.terminal})
                    for s in self.scopes]
            rows.append((contract.END, {**self.common(), "ordinal": 2 * len(self.scopes) + 1,
                        "scope_count": len(self.scopes), "complete": self.issue == "none",
                        "logical_outcome": self.outcome, "issue": self.issue}))
            return rows


def _persist(root, records, *, session_factory=None):
    """Fresh session per publication; deterministic IDs and one atomic batch."""
    try:
        if not records or _revision() != root.revision:
            return False
        from sqlalchemy import select
        from app.database import SessionLocal
        from app.models import SourceFile, ProcessingRun, encode_json_text
        from app.processing.processing_event_model import ProcessingEvent
        from app.processing.processing_events import sanitize_processing_event_payload, PROCESSING_EVENT_SCHEMA_VERSION
        if any(not isinstance(v, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,255}", v) is None
               for v in (root.run_id, root.document_id, root.source_id)):
            return False
        if len(records) > contract.MAX_SCOPES + 1:
            return False
        rows = []
        for name, payload in records:
            if (not contract.valid_payload(name, payload)
                    or any(payload[k] != v for k, v in root.common().items())
                    or sanitize_processing_event_payload(payload) != payload):
                return False
            encoded = encode_json_text(payload)
            if len(encoded.encode("utf-8")) > 8192:
                return False
            event_id = str(uuid.uuid5(uuid.NAMESPACE_OID,
                f"{contract.VERSION}:{root.scope_id}:{payload['ordinal']}"))
            rows.append(ProcessingEvent(id=event_id, processing_run_id=root.run_id,
                document_id=root.document_id, schema_version=PROCESSING_EVENT_SCHEMA_VERSION,
                event_name=name, severity="info", page_number=None, payload_json=encoded))
        with (session_factory or SessionLocal)() as db:
            with db.begin():
                source_document = db.execute(select(SourceFile.document_id).where(SourceFile.id == root.source_id)).scalar_one_or_none()
                run = db.execute(select(ProcessingRun.document_id, ProcessingRun.source_file_id)
                    .where(ProcessingRun.processing_run_id == root.run_id)).one_or_none()
                if source_document != root.document_id or (run is not None and tuple(run) != (root.document_id, root.source_id)):
                    return False
                db.add_all(rows)
        return True
    except Exception:
        return False


def _publish_invalidation(root):
    # One shared slot, one attempt; no recursive publication or batch replay.
    records = root.claim_invalidation()
    if records and not _safe(_persist, root, records):
        root.problem("persistence_loss")


def _publish(root, records):
    if records and not _safe(_persist, root, records):
        root.problem("persistence_loss")
    # A cancelled waiter cannot stop an already-running writer. That writer
    # retains completion ownership and drains invalidation even after loop.close().
    _publish_invalidation(root)


async def _publish_async(root, records):
    if not records:
        return
    try:
        await asyncio.to_thread(_publish, root, records)
    except asyncio.CancelledError:
        root.problem("persistence_loss")
        # The writer may already have returned before cancellation is delivered.
        # Submit a synchronous owner now (not an unowned coroutine/done callback).
        # The executor retains the call/root until it runs; no live event loop is
        # needed by the writer. Races with the original writer share one claim.
        try:
            asyncio.get_running_loop().run_in_executor(None, _publish_invalidation, root)
        except Exception:
            # If shutdown refuses submission, an in-flight writer still drains
            # the pending slot. Publisher/process loss remains an explicit limit.
            pass
        raise
    except Exception:
        root.problem("persistence_loss")


def _not_started(reason):
    return {"operation_outcome": "not_started", "clock_status": "not_started",
            "cpu_delta_ns": None, "clock_resolution_ns": None, "reason": reason}


def _clock_read():
    return get_ident(), time.thread_time_ns()


def _clock_resolution():
    resolution = time.get_clock_info("thread_time").resolution
    if type(resolution) not in (int, float) or not math.isfinite(resolution) or not 0 < resolution <= 1:
        return None
    return math.ceil(resolution * 1e9)


def measure_preprocessing_delegate(delegate, *args, **kwargs):
    scope = _WORKER.get()
    if scope is None:
        return delegate(*args, **kwargs)
    with scope.root.lock:
        if scope.entered:
            scope.root._issue("protocol_violation")
            scope.root._invalidate("protocol_violation")
            enabled = False
        else:
            scope.entered = True
            enabled = True
    if not enabled:
        return delegate(*args, **kwargs)
    resolution = _safe(_clock_resolution)
    start = _safe(_clock_read)
    outcome = "failed"
    try:
        result = delegate(*args, **kwargs)
        outcome = "completed"
        return result
    finally:
        end = _safe(_clock_read)
        def capture():
            values = {"operation_outcome": outcome, "clock_status": "unavailable",
                      "cpu_delta_ns": None, "clock_resolution_ns": None, "reason": "clock_unavailable"}
            if start is not None and end is not None and resolution is not None:
                if (type(start[0]) is int and start[0] > 0 and start[0] == end[0]
                        and type(start[1]) is int and start[1] >= 0
                        and type(end[1]) is int and end[1] >= 0
                        and contract.integer(end[1] - start[1]) and contract.integer(resolution, 1, 1_000_000_000)):
                    values.update(clock_status="measured", cpu_delta_ns=end[1] - start[1],
                                  clock_resolution_ns=resolution, reason="none")
                else:
                    values["reason"] = "invalid_clock"
            with scope.root.lock:
                scope.measurement = values
        _safe(capture)


def run_preprocessing_worker(delegate, *, cpu_scope=None, **kwargs):
    if cpu_scope is None:
        return delegate(**kwargs)
    token = _WORKER.set(cpu_scope)
    failed = False
    try:
        return delegate(**kwargs)
    except BaseException:
        failed = True
        raise
    finally:
        _WORKER.reset(token)
        def finish():
            root = cpu_scope.root
            values = cpu_scope.measurement
            if values is None:
                if cpu_scope.entered or not failed:
                    root.problem("protocol_violation")
                values = _not_started("pre_delegate_failure")
            root.settle(cpu_scope, values)
            # Outer worker finally: original Phase 2 measurement has finished.
            _publish(root, root.claim())
        _safe(finish)


def current_preprocessing_scope():
    return _REQUEST.get()


def note_preprocessing_future(future):
    def note():
        scope = _REQUEST.get()
        if scope is None:
            return
        with scope.root.lock:
            scope.submitted = True
        def done(completed):
            def finish_cancelled():
                if completed.cancelled():
                    scope.root.settle(scope, _not_started("cancelled_before_entry"))
                    _publish(scope.root, scope.root.claim())
            _safe(finish_cancelled)
        future.add_done_callback(done)
    _safe(note)


def note_preprocessing_submit_failed():
    def note():
        scope = _REQUEST.get()
        if scope is not None:
            scope.submit_failed = True
    _safe(note)


def note_cpu_terminal(document_id, processing_attempt_id, status):
    def note():
        root = _ROOT.get()
        if root is not None and (document_id, processing_attempt_id) == (root.document_id, root.run_id):
            with root.lock:
                if status in ("completed", "failed"):
                    root.outcome = status
    _safe(note)


async def observe_preprocessing_request(delegate, *args, **kwargs):
    root = _ROOT.get()
    if root is None:
        return await delegate(*args, **kwargs)
    descriptor = kwargs.get("descriptor")
    if (kwargs.get("processing_attempt_id"), kwargs.get("document_id"),
        getattr(descriptor, "document_id", None), getattr(descriptor, "source_file_id", None)) != (
            root.run_id, root.document_id, root.document_id, root.source_id):
        root.problem("identity_mismatch")
        scope = None
    else:
        scope = _safe(root.register)
        if scope is None and root.issue == "none":
            root.problem("protocol_violation")
    token = _REQUEST.set(scope)
    try:
        if scope is not None:
            await _publish_async(root, [(contract.REGISTER, {**scope.common(), "ordinal": 2 * scope.index - 1})])
        else:
            await _publish_async(root, root.claim())
        return await delegate(*args, **kwargs)
    except BaseException as exc:
        if scope is not None and not scope.submitted:
            reason = ("submit_failed" if scope.submit_failed else "cancelled_before_entry"
                      if isinstance(exc, asyncio.CancelledError) else "admission_rejected"
                      if type(exc).__name__ == "PdfPreprocessingCapacityError" else "pre_delegate_failure")
            root.settle(scope, _not_started(reason))
        raise
    finally:
        _REQUEST.reset(token)
        if scope is not None and not scope.submitted and scope.terminal is None:
            root.problem("protocol_violation")
            root.settle(scope, _not_started("pre_delegate_failure"))


async def observe_pdf_processing(delegate, document_id, source_file_id, ids):
    revision = _safe(_revision)
    if revision is None:
        return await delegate(document_id, source_file_id, ids)
    try:
        root = Root(ids.processing_attempt_id, document_id, source_file_id, revision)
    except Exception:
        return await delegate(document_id, source_file_id, ids)
    token = _ROOT.set(root)
    primary_exception = None
    try:
        await _publish_async(root, [(contract.START, {**root.common(), "ordinal": 0})])
        return await delegate(document_id, source_file_id, ids)
    except asyncio.CancelledError as exc:
        primary_exception = exc
        root.outcome = "cancelled"
        raise
    except BaseException as exc:
        primary_exception = exc
        root.outcome = "failed"
        raise
    finally:
        _ROOT.reset(token)
        root.seal()
        try:
            await _publish_async(root, root.claim())
        except asyncio.CancelledError:
            if primary_exception is None:
                raise


def install_preprocessing_cpu_observability():
    """Called only by the Staging overlay, after the final ingestion wrappers."""
    from app.processing import pdf_ingestion
    original = pdf_ingestion.process_pdf_document_background
    request = pdf_ingestion._prepare_geometry_provider_input_async
    flags = [getattr(fn, "_s0_worker_cpu_installed", False) for fn in (original, request)]
    if all(flags):
        return
    if any(flags):
        raise RuntimeError("Worker CPU runtime partially installed")

    @wraps(original)
    async def observed(document_id, source_file_id, ids):
        return await observe_pdf_processing(original, document_id, source_file_id, ids)

    @wraps(request)
    async def requested(*args, **kwargs):
        return await observe_preprocessing_request(request, *args, **kwargs)

    observed._s0_worker_cpu_installed = True
    requested._s0_worker_cpu_installed = True
    pdf_ingestion.process_pdf_document_background = observed
    pdf_ingestion._prepare_geometry_provider_input_async = requested
