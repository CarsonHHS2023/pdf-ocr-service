"""Bounded observer transactions, isolated from application transactions and pools."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path

from sqlalchemy import case, cast, create_engine, func, LargeBinary, or_, select
from sqlalchemy.pool import NullPool

from app.models import Document, ProcessingRun, SourceFile
from app.models_v2 import StructuredContentCandidateV2Record as Candidate, StructuredContentSourceUnitV2Record as Unit
from app.processing.ingestion_dispatch_model import IngestionDispatch
from app.processing.processing_event_model import ProcessingEvent
from app import s0_txt_worker_metrics as contract


def revision():
    try:
        value = (Path(__file__).resolve().parents[1] / "staging-revision.txt").read_text().strip()
        return value if contract.matches(value, r"[0-9a-f]{40}") else None
    except (OSError, UnicodeError):
        return None


@contextmanager
def observer_connection(engine, *, write=False):
    """Use a fresh connection: no app-pool checkout or inherited transaction.

    SQLite file databases and Psycopg PostgreSQL are supported. Unknown/in-memory
    bindings fail closed. All locks/statements have short database-side bounds.
    """
    dialect = engine.dialect.name
    if dialect == "sqlite" and engine.url.database not in (None, "", ":memory:"):
        args = {"timeout": 0.15}
    elif dialect == "postgresql" and engine.dialect.driver == "psycopg":
        args = {"connect_timeout": 2, "options": str(engine.url.query.get("options", "")) + " -c statement_timeout=500 -c lock_timeout=150"}
    else:
        raise ValueError("unsupported observer database")
    isolated = create_engine(engine.url, poolclass=NullPool, connect_args=args)
    try:
        with isolated.connect() as conn:
            if dialect == "sqlite":
                if not write:
                    conn.exec_driver_sql("PRAGMA query_only = ON")
                conn.exec_driver_sql("BEGIN IMMEDIATE" if write else "BEGIN")
            elif not write:
                conn.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            try:
                yield conn
                if write:
                    conn.commit()
            finally:
                conn.rollback()
    finally:
        isolated.dispose()


def _bounded_rows(conn, run_id):
    event = ProcessingEvent.__table__
    size = (func.octet_length(event.c.payload_json) if conn.dialect.name == "postgresql"
            else func.length(cast(event.c.payload_json, LargeBinary)))
    columns = [event.c[name] for name in sorted(contract.ENVELOPE - {"payload_json"})]
    columns.append(case((size <= contract.MAX_BYTES, event.c.payload_json), else_=None).label("payload_json"))
    return [dict(row) for row in conn.execute(select(*columns).where(
        event.c.processing_run_id == run_id,
        event.c.event_name.startswith(contract.PREFIX, autoescape=True),
    ).limit(4)).mappings()]


def _insert(conn, claim, name, payload):
    if not contract.valid_payload(name, payload):
        return False
    conn.execute(ProcessingEvent.__table__.insert().values(
        id=contract.slot_id(claim.payload.txt_processing_run_ref, payload["ordinal"]),
        processing_run_id=claim.payload.txt_processing_run_ref, document_id=claim.document_id,
        schema_version=contract.SCHEMA, event_name=name,
        severity=("warning" if name == contract.INVALIDATED else
                  "error" if name == contract.TERMINAL and payload["outcome"] == "failed" else "info"),
        page_number=None, payload_json=json.dumps(payload, allow_nan=False, separators=(",", ":")),
    ))
    return True


def publish(engine, claim, name, payload):
    """Serialize per document then dispatch, cap this family at three fixed slots.

    Claims/tokens are used only in SQL predicates, never retained in payloads.
    A fresh actual worker always has a new identity and invalidates prior evidence.
    """
    try:
        with observer_connection(engine, write=True) as conn:
            doc = conn.execute(select(Document.id).where(Document.id == claim.document_id)
                               .with_for_update()).first()
            dispatch = conn.execute(select(IngestionDispatch.id).where(
                IngestionDispatch.id == claim.dispatch_id,
                IngestionDispatch.document_id == claim.document_id,
                IngestionDispatch.source_file_id == claim.source_file_id,
                IngestionDispatch.txt_processing_run_ref == claim.payload.txt_processing_run_ref,
                IngestionDispatch.kind == "txt", IngestionDispatch.status == "running",
                IngestionDispatch.claim_token == claim.claim_token,
                IngestionDispatch.attempt_count == claim.attempt_count,
                IngestionDispatch.claim_expires_at > datetime.utcnow(),
            ).with_for_update()).first()
            if not doc or not dispatch:
                return False
            source = conn.execute(select(SourceFile.id).where(
                SourceFile.id == claim.source_file_id, SourceFile.document_id == claim.document_id,
                SourceFile.file_type == "txt", SourceFile.retained == 1,
                SourceFile.byte_size > 0, SourceFile.byte_size <= contract.MAX_NS,
                SourceFile.storage_reference.is_not(None), SourceFile.storage_reference != "",
            )).first()
            if not source:
                return False
            rows = _bounded_rows(conn, claim.payload.txt_processing_run_ref)
            if len(rows) > 3:
                return False
            by_id = {row["id"]: row for row in rows}
            invalid_slot = contract.slot_id(claim.payload.txt_processing_run_ref, 2)
            if invalid_slot in by_id:
                return False
            reason = None
            if revision() != payload["backend_revision"]:
                reason = "revision_changed"
            slot = contract.slot_id(claim.payload.txt_processing_run_ref, payload["ordinal"])
            if slot in by_id:
                stored, valid = contract.decode_payload(by_id[slot]["payload_json"])
                if valid and stored == payload and by_id[slot]["event_name"] == name:
                    return True
                reason = "duplicate_worker" if name == contract.START else "conflicting_terminal"
            elif name == contract.START and rows:
                reason = "duplicate_worker"
            elif name == contract.TERMINAL:
                start = by_id.get(contract.slot_id(claim.payload.txt_processing_run_ref, 0))
                stored, valid = contract.decode_payload(start["payload_json"] if start else None)
                if not valid or any(stored.get(k) != payload[k] for k in contract.COMMON):
                    reason = "conflicting_terminal"
            if reason:
                # Never create a fourth row, including after foreign/malformed events.
                if len(rows) < 3:
                    invalid = {key: payload[key] for key in contract.COMMON}
                    _insert(conn, claim, contract.INVALIDATED, dict(invalid, ordinal=2, reason=reason))
                return False
            if len(rows) >= 3:
                return False
            return _insert(conn, claim, name, payload)
    except Exception:
        # Evidence failure is not a processing failure; do not log DB/payload data.
        return False


def collect(engine, run_id):
    """Resolve one TXT projection in a fresh read-only consistent snapshot."""
    missing = contract.Reading("not_available", None, "incomplete_or_ineligible_context")
    backend = revision()
    if not backend or not contract.matches(run_id, r"txt-ingest-[0-9a-f]{32}"):
        return missing
    try:
        with observer_connection(engine) as conn:
            run = conn.execute(select(
                ProcessingRun.document_id, ProcessingRun.source_file_id, ProcessingRun.status,
                ProcessingRun.structured_processing_result_ref, ProcessingRun.provider_ref,
            ).where(ProcessingRun.processing_run_id == run_id)).mappings().one_or_none()
            if run is None or run["provider_ref"] != "txt-structure-analyzer" or not run["structured_processing_result_ref"]:
                return missing
            doc = conn.execute(select(Document.status, Document.file_type).where(
                Document.id == run["document_id"])).mappings().one_or_none()
            source = conn.execute(select(SourceFile.byte_size, SourceFile.file_type).where(
                SourceFile.id == run["source_file_id"], SourceFile.document_id == run["document_id"],
                SourceFile.retained == 1, SourceFile.storage_reference.is_not(None),
                SourceFile.storage_reference != "",
            )).mappings().one_or_none()
            dispatches = conn.execute(select(IngestionDispatch.id, IngestionDispatch.status,
                IngestionDispatch.document_id, IngestionDispatch.source_file_id,
                IngestionDispatch.kind, IngestionDispatch.attempt_count).where(
                IngestionDispatch.txt_processing_run_ref == run_id).limit(2)).mappings().all()
            candidates = conn.execute(select(Candidate.id, Candidate.candidate_id,
                Candidate.document_id,
                Candidate.structured_processing_result_ref).where(
                Candidate.processing_run_ref == run_id).limit(2)).mappings().all()
            if not doc or doc["file_type"] != "txt" or not source or len(dispatches) != 1 or len(candidates) != 1:
                return missing
            dispatch, candidate = dispatches[0], candidates[0]
            if (dispatch["kind"] != "txt" or dispatch["document_id"] != run["document_id"]
                or dispatch["source_file_id"] != run["source_file_id"]
                or candidate["document_id"] != run["document_id"]
                or candidate["structured_processing_result_ref"] != run["structured_processing_result_ref"]):
                return missing
            has_unit = conn.execute(select(Unit.id).where(Unit.candidate_id == candidate["id"]).limit(1)).first()
            foreign_unit = conn.execute(select(Unit.id).where(Unit.candidate_id == candidate["id"],
                or_(Unit.source_ref != run["source_file_id"], Unit.kind != "text_flow")).limit(1)).first()
            if not has_unit or foreign_unit:
                return missing
            context = contract.AdmissionContext(run_id, run["document_id"], run["source_file_id"],
                candidate["candidate_id"], dispatch["id"], dispatch["attempt_count"], backend,
                source["byte_size"], source["file_type"], run["status"], doc["status"], dispatch["status"])
            rows = _bounded_rows(conn, run_id)
            if revision() != backend:
                return missing
            return contract.evaluate(rows, context)
    except Exception:
        return missing
