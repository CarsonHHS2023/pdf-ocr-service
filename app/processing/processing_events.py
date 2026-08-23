"""Staging-only durable processing event persistence and bounded querying.

This module persists selected structured diagnostics alongside normal stdout
logging. It intentionally does not mirror arbitrary log lines, exception traces,
request bodies, provider payloads, credentials, or signed URLs.

Persistence is fail-open and observability-only: event storage must never change
processing outcomes or become workflow/queue truth.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Document, ProcessingRun, decode_json_text, encode_json_text
from app.processing.processing_event_model import ProcessingEvent


PROCESSING_EVENT_SCHEMA_VERSION = "atlas.processing.event.v1"
MAX_EVENT_PAYLOAD_BYTES = 8192
MAX_PAYLOAD_FIELDS = 32
MAX_NESTED_FIELDS = 16
MAX_LIST_ITEMS = 12
MAX_STRING_CHARS = 256
MAX_NESTING_DEPTH = 2
MAX_QUERY_LIMIT = 500

_RUNTIME_ROOT = Path(__file__).resolve().parents[2]
_STAGING_REVISION_FILE = _RUNTIME_ROOT / "staging-revision.txt"
_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
_EVENT_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_DROP = object()

_SENSITIVE_KEY_PARTS = (
    "authorization",
    "password",
    "secret",
    "token",
    "credential",
    "cookie",
    "api_key",
    "apikey",
)
_SENSITIVE_EXACT_KEYS = {
    "url",
    "signed_url",
    "presigned_url",
    "request_body",
    "response_body",
    "raw_payload",
    "raw_result",
    "source_bytes",
    "pdf_bytes",
}


@dataclass(frozen=True, slots=True)
class ProcessingEventRecord:
    event_id: str
    processing_run_id: str
    document_id: str
    schema_version: str
    event_name: str
    severity: str
    page_number: int | None
    payload: dict[str, Any]
    created_at: datetime


def staging_processing_events_enabled() -> bool:
    """Return whether this runtime is a verified Staging deployment artifact."""
    try:
        revision = _STAGING_REVISION_FILE.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return False
    return _REVISION_RE.fullmatch(revision) is not None


def _safe_key(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    key = raw.strip()
    if not key or len(key) > 64:
        return None
    normalized = key.lower()
    if normalized in _SENSITIVE_EXACT_KEYS or normalized.endswith("_url"):
        return None
    if any(part in normalized for part in _SENSITIVE_KEY_PARTS):
        return None
    return key


def _safe_value(value: object, *, depth: int) -> object:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _DROP
    if isinstance(value, str):
        return value[:MAX_STRING_CHARS]
    if depth >= MAX_NESTING_DEPTH:
        return _DROP
    if isinstance(value, Mapping):
        output: dict[str, object] = {}
        for raw_key in sorted(value, key=lambda item: str(item))[: MAX_NESTED_FIELDS * 2]:
            key = _safe_key(raw_key)
            if key is None or key in output:
                continue
            cleaned = _safe_value(value[raw_key], depth=depth + 1)
            if cleaned is _DROP:
                continue
            output[key] = cleaned
            if len(output) >= MAX_NESTED_FIELDS:
                break
        return output
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, memoryview)):
        output = []
        for item in value[:MAX_LIST_ITEMS]:
            cleaned = _safe_value(item, depth=depth + 1)
            if cleaned is not _DROP:
                output.append(cleaned)
        return output
    return _DROP


def sanitize_processing_event_payload(payload: Mapping[str, object] | None) -> dict[str, Any]:
    """Return deterministic bounded JSON while dropping sensitive/unbounded fields."""
    if not isinstance(payload, Mapping):
        return {}

    cleaned: dict[str, Any] = {}
    for raw_key in sorted(payload, key=lambda item: str(item)):
        key = _safe_key(raw_key)
        if key is None or key in cleaned:
            continue
        value = _safe_value(payload[raw_key], depth=0)
        if value is _DROP:
            continue
        candidate = {**cleaned, key: value}
        encoded = encode_json_text(candidate) or "{}"
        if len(encoded.encode("utf-8")) > MAX_EVENT_PAYLOAD_BYTES:
            cleaned["_payload_truncated"] = True
            break
        cleaned[key] = value
        if len(cleaned) >= MAX_PAYLOAD_FIELDS:
            cleaned["_payload_truncated"] = True
            break
    return cleaned


def _valid_identity(value: object, *, max_chars: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > max_chars:
        return None
    return normalized


def record_processing_event(
    *,
    processing_run_id: object,
    event_name: object,
    document_id: object | None = None,
    severity: str = "info",
    page_number: object | None = None,
    payload: Mapping[str, object] | None = None,
    session_factory=SessionLocal,
) -> bool:
    """Append one sanitized event in Staging; fail open on every persistence error."""
    if not staging_processing_events_enabled():
        return False

    run_id = _valid_identity(processing_run_id, max_chars=255)
    name = _valid_identity(event_name, max_chars=128)
    if run_id is None or name is None or _EVENT_NAME_RE.fullmatch(name) is None:
        return False
    if severity not in {"info", "warning", "error"}:
        return False
    resolved_page: int | None = None
    if isinstance(page_number, int) and not isinstance(page_number, bool) and page_number > 0:
        resolved_page = page_number

    db = None
    try:
        db = session_factory()
        resolved_document = _valid_identity(document_id, max_chars=255)
        if resolved_document is None:
            run = db.execute(
                select(ProcessingRun).where(ProcessingRun.processing_run_id == run_id)
            ).scalar_one_or_none()
            if run is None:
                return False
            resolved_document = run.document_id
        if db.get(Document, resolved_document) is None:
            return False

        row = ProcessingEvent(
            processing_run_id=run_id,
            document_id=resolved_document,
            schema_version=PROCESSING_EVENT_SCHEMA_VERSION,
            event_name=name,
            severity=severity,
            page_number=resolved_page,
            payload_json=encode_json_text(sanitize_processing_event_payload(payload)) or "{}",
        )
        db.add(row)
        db.commit()
        return True
    except Exception:
        if db is not None:
            try:
                db.rollback()
            except Exception:
                pass
        return False
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass


def _decode_payload(value: str) -> dict[str, Any]:
    try:
        payload = decode_json_text(value)
    except Exception:
        return {"_persisted_payload_invalid": True}
    return payload if isinstance(payload, dict) else {"_persisted_payload_invalid": True}


def list_processing_events(
    session,
    *,
    processing_run_id: str | None = None,
    document_id: str | None = None,
    event_name: str | None = None,
    limit: int = 200,
) -> tuple[ProcessingEventRecord, ...]:
    """Return the latest bounded event window in chronological order."""
    run_id = _valid_identity(processing_run_id, max_chars=255) if processing_run_id is not None else None
    doc_id = _valid_identity(document_id, max_chars=255) if document_id is not None else None
    if run_id is None and doc_id is None:
        raise ValueError("processing_run_id or document_id is required")
    if event_name is not None:
        normalized_event = _valid_identity(event_name, max_chars=128)
        if normalized_event is None or _EVENT_NAME_RE.fullmatch(normalized_event) is None:
            raise ValueError("event_name is invalid")
    else:
        normalized_event = None
    bounded_limit = max(1, min(int(limit), MAX_QUERY_LIMIT))

    statement = select(ProcessingEvent)
    if run_id is not None:
        statement = statement.where(ProcessingEvent.processing_run_id == run_id)
    if doc_id is not None:
        statement = statement.where(ProcessingEvent.document_id == doc_id)
    if normalized_event is not None:
        statement = statement.where(ProcessingEvent.event_name == normalized_event)
    rows = session.execute(
        statement.order_by(ProcessingEvent.created_at.desc(), ProcessingEvent.id.desc()).limit(bounded_limit)
    ).scalars().all()
    rows.reverse()
    return tuple(
        ProcessingEventRecord(
            event_id=row.id,
            processing_run_id=row.processing_run_id,
            document_id=row.document_id,
            schema_version=row.schema_version,
            event_name=row.event_name,
            severity=row.severity,
            page_number=row.page_number,
            payload=_decode_payload(row.payload_json),
            created_at=row.created_at,
        )
        for row in rows
    )


__all__ = [
    "MAX_EVENT_PAYLOAD_BYTES",
    "MAX_QUERY_LIMIT",
    "PROCESSING_EVENT_SCHEMA_VERSION",
    "ProcessingEventRecord",
    "list_processing_events",
    "record_processing_event",
    "sanitize_processing_event_payload",
    "staging_processing_events_enabled",
]
