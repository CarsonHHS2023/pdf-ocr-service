"""Inactive, dependency-free v1 contract for future TXT worker timing evidence.

No producer, database access, clock sampling or baseline mapping is installed.
The future adapter must supply a verified relational context and bounded rows.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import uuid

VERSION = "atlas.s0.txt-worker-wall.v1"
METHOD = "same_worker_perf_counter_ns_v1"
SCOPE = "txt_worker_configuration_to_canonical_commit_v1"
METRIC_KEY = "txt_ingestion_worker_wall_seconds"
PREFIX = "S0_TXT_WORKER_"
START = PREFIX + "STARTED"
TERMINAL = PREFIX + "TERMINAL"
INVALIDATED = PREFIX + "INVALIDATED"
EVENT_NAMES = frozenset((START, TERMINAL, INVALIDATED))
SCHEMA = "atlas.processing.event.v1"
MAX_BYTES = 2048
MAX_NS = 2**53 - 1
MAX_ATTEMPT = 2**31 - 1
COMMON = frozenset(("contract_version", "method", "measurement_scope", "worker_scope_id",
    "source_scope_id", "dispatch_scope_id", "dispatch_attempt", "backend_revision"))
ENVELOPE = frozenset(("id", "processing_run_id", "document_id", "schema_version",
    "event_name", "severity", "page_number", "payload_json"))
FAILURES = frozenset(("configuration_error", "canonicalization_error", "unexpected_error", "worker_interrupted"))
INVALID_REASONS = frozenset(("clock_unavailable", "invalid_clock", "candidate_mismatch"))
INVALIDATIONS = frozenset(("duplicate_worker", "conflicting_terminal", "revision_changed"))


def integer(value, low=0, high=MAX_NS):
    return type(value) is int and low <= value <= high


def matches(value, pattern):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def opaque_scope(kind, identity):
    if kind not in ("source", "dispatch", "candidate") or not matches(identity, r"[A-Za-z0-9_-]{1,255}"):
        return None
    return kind + "_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def slot_id(run_id, ordinal):
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"{VERSION}:{run_id}:{ordinal}"))


def decode_payload(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def reject_constant(_value):
        raise ValueError("nonfinite")

    try:
        if not isinstance(raw, (str, bytes)) or len(raw) > MAX_BYTES:
            return {}, False
        data = raw.encode("utf-8") if isinstance(raw, str) else raw
        if len(data) > MAX_BYTES:
            return {}, False
        payload = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=reject_constant)
        return (payload, True) if isinstance(payload, dict) else ({}, False)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return {}, False


def valid_payload(name, payload):
    if not isinstance(name, str) or name not in EVENT_NAMES or not isinstance(payload, dict):
        return False
    ordinal, extra = {
        START: (0, frozenset()),
        TERMINAL: (1, frozenset(("outcome", "duration_ns", "candidate_scope_id", "reason"))),
        INVALIDATED: (2, frozenset(("reason",))),
    }[name]
    if (set(payload) != COMMON | {"ordinal"} | extra
            or type(payload["ordinal"]) is not int or payload["ordinal"] != ordinal
            or payload["contract_version"] != VERSION or payload["method"] != METHOD
            or payload["measurement_scope"] != SCOPE
            or not integer(payload["dispatch_attempt"], 1, MAX_ATTEMPT)
            or not matches(payload["worker_scope_id"], r"txtw_[0-9a-f]{32}")
            or not matches(payload["source_scope_id"], r"source_[0-9a-f]{64}")
            or not matches(payload["dispatch_scope_id"], r"dispatch_[0-9a-f]{64}")
            or not matches(payload["backend_revision"], r"[0-9a-f]{40}")):
        return False
    if name == START:
        return True
    reason = payload["reason"]
    if not isinstance(reason, str):
        return False
    if name == INVALIDATED:
        return reason in INVALIDATIONS
    outcome = payload["outcome"]
    if outcome == "completed":
        return (reason == "none" and integer(payload["duration_ns"])
            and matches(payload["candidate_scope_id"], r"candidate_[0-9a-f]{64}"))
    if outcome not in ("failed", "invalid"):
        return False
    return (payload["duration_ns"] is None and payload["candidate_scope_id"] is None
        and reason in (FAILURES if outcome == "failed" else INVALID_REASONS))


@dataclass(frozen=True)
class AdmissionContext:
    """Trusted, read-only relational projection; constructing it is not a DB join.

    The future adapter must verify run/source/document/candidate/dispatch links
    in one consistent snapshot before calling evaluate(). Never accept this
    context from browser input or infer it from the event payload alone.
    """

    run_id: str
    document_id: str
    source_id: str
    candidate_id: str
    dispatch_id: str
    dispatch_attempt: int
    backend_revision: str
    source_bytes: int
    source_type: str
    run_status: str
    document_status: str
    dispatch_status: str


@dataclass(frozen=True)
class Reading:
    status: str
    value: float | None
    reason: str


def _context_valid(context):
    return (type(context) is AdmissionContext
        and matches(context.run_id, r"txt-ingest-[0-9a-f]{32}")
        and all(matches(getattr(context, k), r"[A-Za-z0-9_-]{1,255}")
            for k in ("document_id", "source_id", "candidate_id", "dispatch_id"))
        and matches(context.backend_revision, r"[0-9a-f]{40}")
        and integer(context.dispatch_attempt, 1, MAX_ATTEMPT)
        and integer(context.source_bytes, 1)
        and context.source_type == "txt" and context.run_status == "succeeded"
        and context.document_status == "completed" and context.dispatch_status == "succeeded")


def evaluate(rows, context, *, evidence_incomplete=False):
    """Admit one worker from at most three already SQL-bounded family envelopes.

    This evaluates evidence only. It does not emit an S0 baseline metric and it
    cannot establish the completeness or relational provenance of its inputs.
    """
    def missing(reason):
        return Reading("not_available", None, reason)

    if evidence_incomplete is not False or not _context_valid(context):
        return missing("incomplete_or_ineligible_context")
    if not isinstance(rows, (list, tuple)) or not 1 <= len(rows) <= 3:
        return missing("invalid_event_count")
    decoded = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != ENVELOPE:
            return missing("invalid_envelope")
        name = row["event_name"]
        payload, valid = decode_payload(row["payload_json"])
        if not valid or not valid_payload(name, payload):
            return missing("invalid_payload")
        ordinal = payload["ordinal"]
        if (ordinal in decoded or row["id"] != slot_id(context.run_id, ordinal)
                or row["processing_run_id"] != context.run_id or row["document_id"] != context.document_id
                or row["schema_version"] != SCHEMA or row["page_number"] is not None
                or row["severity"] != ("warning" if name == INVALIDATED else
                    "error" if name == TERMINAL and payload["outcome"] == "failed" else "info")):
            return missing("conflicting_envelope")
        decoded[ordinal] = payload
    if set(decoded) != {0, 1}:
        return missing("missing_or_invalidated_worker")
    start, terminal = decoded[0], decoded[1]
    if any(start[k] != terminal[k] for k in COMMON):
        return missing("conflicting_worker_identity")
    expected = {
        "source_scope_id": opaque_scope("source", context.source_id),
        "dispatch_scope_id": opaque_scope("dispatch", context.dispatch_id),
        "dispatch_attempt": context.dispatch_attempt,
        "backend_revision": context.backend_revision,
    }
    if any(start[k] != value for k, value in expected.items()):
        return missing("context_identity_mismatch")
    if terminal["outcome"] != "completed":
        return missing("worker_not_measured_success")
    if terminal["candidate_scope_id"] != opaque_scope("candidate", context.candidate_id):
        return missing("candidate_identity_mismatch")
    return Reading("observed", terminal["duration_ns"] / 1_000_000_000, "measured_canonical_worker_only")
