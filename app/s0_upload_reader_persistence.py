"""Bounded, observer-owned transactions; no ingestion/workflow state writes."""
from __future__ import annotations

from functools import lru_cache
import json
import uuid
from threading import Lock

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app import s0_upload_reader_metrics as contract


@lru_cache(maxsize=1)
def _cached_factory():
    from app.database import engine
    # No application-pool reconfiguration. Checkout, connect and each statement
    # are bounded independently; no claim of an end-to-end network deadline.
    if engine.dialect.name != "postgresql":
        raise RuntimeError("Staging observer requires PostgreSQL")
    observed = create_engine(engine.url, pool_size=2, max_overflow=0, pool_timeout=.5,
        isolation_level="READ COMMITTED", connect_args={"connect_timeout": 2})
    return sessionmaker(bind=observed, autoflush=False, expire_on_commit=False)


_FACTORY_LOCK = Lock()


def _factory():
    with _FACTORY_LOCK:
        return _cached_factory()


def slot_id(run_id, ordinal):
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"{contract.VERSION}:{run_id}:{ordinal}"))


def _limits(db):
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SET LOCAL lock_timeout = '250ms'"))
        db.execute(text("SET LOCAL statement_timeout = '1000ms'"))


def _lock(db, document_id):
    from app.models import Document
    return db.execute(select(Document.id).where(Document.id == document_id)
        .with_for_update(key_share=True)).scalar_one_or_none() is not None


def _rows(db, run_id, document_id):
    from app.processing.processing_event_model import ProcessingEvent
    from app.processing.processing_events import PROCESSING_EVENT_SCHEMA_VERSION
    rows = db.execute(select(ProcessingEvent).where(ProcessingEvent.processing_run_id == run_id,
        ProcessingEvent.event_name.like("S0_UPLOAD_READER_%")).limit(4)).scalars().all()
    if len(rows) > 3:
        raise ValueError("event cap")
    result = {}
    for row in rows:
        p, ok = contract.decode_payload(row.payload_json)
        if (not ok or not contract.valid_payload(row.event_name, p) or p["ordinal"] in result
                or row.id != slot_id(run_id, p["ordinal"]) or row.document_id != document_id
                or row.schema_version != PROCESSING_EVENT_SCHEMA_VERSION or row.page_number is not None
                or row.severity != ("warning" if p["ordinal"] == 2 else "info")):
            raise ValueError("invalid stored evidence")
        result[p["ordinal"]] = p
    if 0 in result and any(any(payload[k] != result[0][k]
            for k in contract.COMMON - {"ordinal", "succeeded"}) for payload in result.values()):
        raise ValueError("stored association conflict")
    return result


def _insert(db, run_id, document_id, name, payload):
    from app.processing.processing_event_model import ProcessingEvent
    from app.processing.processing_events import PROCESSING_EVENT_SCHEMA_VERSION, sanitize_processing_event_payload
    encoded = json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True)
    if (not contract.valid_payload(name, payload) or len(encoded.encode("utf-8")) > 8192
            or sanitize_processing_event_payload(payload) != payload):
        raise ValueError("invalid publication")
    db.add(ProcessingEvent(id=slot_id(run_id, payload["ordinal"]), processing_run_id=run_id,
        document_id=document_id, schema_version=PROCESSING_EVENT_SCHEMA_VERSION, event_name=name,
        severity="warning" if name == contract.INVALIDATED else "info", page_number=None, payload_json=encoded))
    db.flush()


def _invalidate(db, run_id, document_id, rows, reason):
    if 2 not in rows:
        p = {k: rows[0][k] for k in contract.COMMON}
        p.update(ordinal=2, succeeded=False, reason=reason)
        _insert(db, run_id, document_id, contract.INVALIDATED, p)


def accept(dispatch_id, root, frontend, backend, *, session_factory=None):
    """Return True only after a committed acceptance; never acknowledge a conflict."""
    from app.models import ProcessingRun, SourceFile
    from app.processing.ingestion_dispatch_model import IngestionDispatch
    if not all(contract.valid_id(k, v) for k, v in (("upload_scope_id", root),
            ("frontend_revision", frontend), ("backend_revision", backend))):
        return False
    try:
        with (session_factory or _factory())() as db, db.begin():
            _limits(db)
            dispatch = db.get(IngestionDispatch, dispatch_id)
            if dispatch is None or dispatch.kind != "pdf" or not _lock(db, dispatch.document_id):
                return False
            run_id, document_id, source_id = dispatch.processing_attempt_id, dispatch.document_id, dispatch.source_file_id
            if not all(contract.source_scope_id(v) for v in (run_id, document_id, source_id)):
                return False
            if db.execute(select(SourceFile.document_id).where(SourceFile.id == source_id)).scalar_one_or_none() != document_id:
                return False
            run = db.execute(select(ProcessingRun.document_id, ProcessingRun.source_file_id)
                .where(ProcessingRun.processing_run_id == run_id)).one_or_none()
            if run is not None and tuple(run) != (document_id, source_id):
                return False
            payload = {**contract.common(root, source_id, frontend, backend), "ordinal": 0,
                "succeeded": True, "upload_route": "POST /api/v1/upload"}
            rows = _rows(db, run_id, document_id)
            if 2 in rows or (rows and 0 not in rows):
                return False
            if 0 in rows:
                if rows[0] == payload:
                    return True
                _invalidate(db, run_id, document_id, rows, "conflicting_acceptance")
                return False
            _insert(db, run_id, document_id, contract.ACCEPTED, payload)
        return True
    except Exception:
        return False


def terminal(document_id, request, backend, *, session_factory=None):
    """204 commits/idempotency, 409 association/conflict, 503 persistence failure."""
    from app.models import ProcessingRun
    from app.models_v2 import StructuredContentCandidateV2Record as Candidate
    if not contract.valid_request(request) or request["backend_revision"] != backend:
        return 409
    try:
        with (session_factory or _factory())() as db, db.begin():
            _limits(db)
            if not _lock(db, document_id):
                return 409
            run = db.execute(select(ProcessingRun.processing_run_id, ProcessingRun.source_file_id)
                .join(Candidate, Candidate.processing_run_ref == ProcessingRun.processing_run_id)
                .where(Candidate.candidate_id == request["candidate_id"], Candidate.document_id == document_id,
                    ProcessingRun.document_id == document_id, ProcessingRun.status == "succeeded")).one_or_none()
            if run is None:
                return 409
            run_id, source_id = run
            rows = _rows(db, run_id, document_id)
            if 0 not in rows or 2 in rows:
                return 409
            expected = contract.common(request["upload_scope_id"], source_id, request["frontend_revision"], backend)
            if any(rows[0][k] != v for k, v in expected.items()):
                return 409
            payload = {**expected, "ordinal": 1, "succeeded": True,
                "open_scope_id": request["open_scope_id"], "candidate_scope_id": contract.candidate_scope_id(request["candidate_id"]),
                "duration_seconds": request["duration_seconds"]}
            if 1 in rows:
                if rows[1] == payload:
                    return 204
                _invalidate(db, run_id, document_id, rows, "conflicting_terminal")
                return 409
            _insert(db, run_id, document_id, contract.TERMINAL, payload)
        return 204
    except Exception:
        return 503
