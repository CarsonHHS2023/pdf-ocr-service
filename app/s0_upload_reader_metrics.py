"""Strict, dependency-light upload/Reader wire and durable evidence contract."""
from __future__ import annotations

import hashlib
import json
import math
import re

from app.s0_reader_open_metrics import REQUEST_EVENT, TERMINAL_EVENT, measure_reader_open

VERSION = "s0_upload_reader_v1"
SCOPE = "canonical_single_upload_to_initial_semantic_render_v1"
METHOD = "browser_same_context_elapsed_v1"
ACCEPTED = "S0_UPLOAD_READER_ACCEPTED"
TERMINAL = "S0_UPLOAD_READER_TERMINAL"
INVALIDATED = "S0_UPLOAD_READER_INVALIDATED"
EVENT_NAMES = frozenset({ACCEPTED, TERMINAL, INVALIDATED})
COMMON = frozenset({"protocol_version", "measurement_scope", "measurement_method",
    "upload_scope_id", "source_scope_id", "frontend_revision", "backend_revision", "ordinal", "succeeded"})
REQUEST_FIELDS = frozenset({"protocol_version", "measurement_scope", "measurement_method",
    "upload_scope_id", "open_scope_id", "candidate_id", "frontend_revision", "backend_revision", "duration_seconds"})
PATTERNS = {"upload_scope_id": r"upr_[0-9a-f]{32}", "open_scope_id": r"reader_[0-9a-f]{32}",
    "source_scope_id": r"source_[0-9a-f]{64}", "candidate_scope_id": r"candidate_[0-9a-f]{16}",
    "frontend_revision": r"[0-9a-f]{40}", "backend_revision": r"[0-9a-f]{40}",
    "candidate_id": r"[A-Za-z0-9_-]{1,255}"}


def valid_id(key, value):
    return isinstance(value, str) and re.fullmatch(PATTERNS[key], value) is not None


def source_scope_id(value):
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,255}", value) is None:
        return None
    return "source_" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def candidate_scope_id(value):
    return "candidate_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def duration(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 3600
    except OverflowError:
        return False


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def decode_payload(raw, limit=8192):
    try:
        data = raw.encode("utf-8") if isinstance(raw, str) else raw
        if not isinstance(data, bytes) or len(data) > limit:
            return {}, False
        result = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        return (result, True) if isinstance(result, dict) else ({}, False)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return {}, False


def _constants(p):
    return (p.get("protocol_version") == VERSION and p.get("measurement_scope") == SCOPE
        and p.get("measurement_method") == METHOD)


def valid_request(p):
    return (isinstance(p, dict) and set(p) == REQUEST_FIELDS and _constants(p)
        and all(valid_id(k, p[k]) for k in ("upload_scope_id", "open_scope_id", "candidate_id",
            "frontend_revision", "backend_revision")) and duration(p["duration_seconds"]))


def valid_payload(name, p):
    if name not in EVENT_NAMES or not isinstance(p, dict):
        return False
    ordinal, extra = {ACCEPTED: (0, {"upload_route"}),
        TERMINAL: (1, {"open_scope_id", "candidate_scope_id", "duration_seconds"}),
        INVALIDATED: (2, {"reason"})}[name]
    if (set(p) != COMMON | extra or not _constants(p) or type(p["ordinal"]) is not int
            or p["ordinal"] != ordinal or p["succeeded"] is not (name != INVALIDATED)
            or not all(valid_id(k, p[k]) for k in ("upload_scope_id", "source_scope_id",
                "frontend_revision", "backend_revision"))):
        return False
    if name == ACCEPTED:
        return p["upload_route"] == "POST /api/v1/upload"
    if name == INVALIDATED:
        return p["reason"] in ("conflicting_acceptance", "conflicting_terminal")
    return (valid_id("open_scope_id", p["open_scope_id"])
        and valid_id("candidate_scope_id", p["candidate_scope_id"]) and duration(p["duration_seconds"]))


def common(root, source, frontend, backend):
    return dict(protocol_version=VERSION, measurement_scope=SCOPE, measurement_method=METHOD,
        upload_scope_id=root, source_scope_id=source_scope_id(source), frontend_revision=frontend,
        backend_revision=backend)


def measure_upload_reader(events, *, expected_source_scope, run_status,
                          evidence_incomplete=False, uninspectable_event_names=frozenset()):
    def missing(note):
        return dict(status="not_available", value=None, breakdown=None, note=note)
    if (evidence_incomplete or run_status != "succeeded" or expected_source_scope is None
            or (EVENT_NAMES | {REQUEST_EVENT, TERMINAL_EVENT}) & uninspectable_event_names):
        return missing("Incomplete, malformed or nonterminal upload/Reader evidence.")
    rows = [e for e in events if e.event_name.startswith("S0_UPLOAD_READER_")]
    if len(rows) != 2 or {e.event_name for e in rows} != {ACCEPTED, TERMINAL}:
        return missing("Expected one acceptance and terminal; invalidations and duplicates reject admission.")
    if any(not valid_payload(e.event_name, e.payload) for e in rows):
        return missing("Invalid upload/Reader payload contract.")
    a = next(e.payload for e in rows if e.event_name == ACCEPTED)
    t = next(e.payload for e in rows if e.event_name == TERMINAL)
    if any(a[k] != t[k] for k in COMMON - {"ordinal", "succeeded"}) or a["source_scope_id"] != expected_source_scope:
        return missing("Upload source, root or revisions differ.")
    selected = [e for e in events if e.event_name in {REQUEST_EVENT, TERMINAL_EVENT}
        and isinstance(e.payload, dict) and e.payload.get("open_scope_id") == t["open_scope_id"]]
    reader = measure_reader_open(selected, evidence_incomplete=False, uninspectable_event_names=frozenset())
    if reader["status"] != "observed" or len(reader["breakdown"]) != 1:
        return missing("Exact Reader open is incomplete or invalid.")
    proof = reader["breakdown"][0]
    if (proof["mode"] != "first_open" or proof["request_count"] != 3
            or any(proof[k] != t[k] for k in ("frontend_revision", "backend_revision"))
            or any(e.payload["candidate_scope_id"] != t["candidate_scope_id"] for e in selected)):
        return missing("Reader open is not the accepted first-open candidate/revision.")
    return dict(status="observed", value=t["duration_seconds"],
        breakdown={**{k: t[k] for k in COMMON - {"ordinal", "succeeded"}},
            "open_scope_id": t["open_scope_id"], "candidate_scope_id": t["candidate_scope_id"],
            "client_reported": True},
        note="Client-reported same-page upload dispatch to initial semantic render; excludes binary completion and paint.")
