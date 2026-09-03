"""Strict worker-thread CPU auxiliary contract; never complete-stage CPU."""
import hashlib
import json
import re

PREFIX = "S0_PREPROCESS_CPU_"
START = PREFIX + "RUN_STARTED"
REGISTER = PREFIX + "SCOPE_REGISTERED"
SCOPE_END = PREFIX + "SCOPE_TERMINAL"
END = PREFIX + "RUN_TERMINAL"
INVALID = PREFIX + "RUN_INVALIDATED"
EVENT_NAMES = frozenset((START, REGISTER, SCOPE_END, END, INVALID))
VERSION = "atlas.s0.preprocessing-worker-cpu.v1"
METHOD = "sync_preprocessing_worker_thread_cpu_v1"
MAX_SCOPES = 8
MAX_NS = 2**53 - 1
COMMON = frozenset(("contract_version", "measurement_scope", "method", "run_scope_id",
                    "source_scope_id", "backend_revision"))
ISSUES = frozenset(("none", "scope_overflow", "persistence_loss", "identity_mismatch",
                    "protocol_violation", "logical_terminal_unknown"))
OUTCOMES = frozenset(("completed", "failed", "cancelled", "unknown"))
_PATTERNS = {"run_scope_id": r"cpu_[0-9a-f]{32}", "scope_id": r"pcpu_[0-9a-f]{32}",
             "source_scope_id": r"source_[0-9a-f]{64}", "backend_revision": r"[0-9a-f]{40}"}


def integer(value, low=0, high=MAX_NS):
    return type(value) is int and low <= value <= high


def source_scope_id(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 255:
        return None
    return "source_" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def decode_worker_cpu_payload(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result
    def invalid_constant(_):
        raise ValueError("non-finite JSON constant")
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)
        return (value, True) if isinstance(value, dict) else ({}, False)
    except (ValueError, TypeError, RecursionError):
        return {}, False


def valid_payload(name, p):
    extra = {
        START: {"ordinal"}, REGISTER: {"ordinal", "scope_index", "scope_id"},
        SCOPE_END: {"ordinal", "scope_index", "scope_id", "operation_outcome", "clock_status",
                    "cpu_delta_ns", "clock_resolution_ns", "reason"},
        END: {"ordinal", "scope_count", "complete", "logical_outcome", "issue"},
        INVALID: {"ordinal", "issue"},
    }
    if name not in extra or not isinstance(p, dict) or set(p) != COMMON | extra[name]:
        return False
    if (p["contract_version"] != VERSION or p["method"] != METHOD
            or p["measurement_scope"] != "worker_thread_only"):
        return False
    for key, pattern in _PATTERNS.items():
        if key in p and (not isinstance(p[key], str) or re.fullmatch(pattern, p[key]) is None):
            return False
    if not integer(p["ordinal"], 0, 18):
        return False
    if name == START:
        return p["ordinal"] == 0
    if name == INVALID:
        return (p["ordinal"] == 18 and isinstance(p["issue"], str)
                and p["issue"] in {"protocol_violation", "persistence_loss"})
    if name == END:
        return (integer(p["scope_count"], 0, MAX_SCOPES)
                and p["ordinal"] == 2 * p["scope_count"] + 1
                and type(p["complete"]) is bool and isinstance(p["logical_outcome"], str)
                and p["logical_outcome"] in OUTCOMES and isinstance(p["issue"], str)
                and p["issue"] in ISSUES
                and (not p["complete"] or (p["issue"] == "none" and p["logical_outcome"] != "unknown")))
    if (not integer(p["scope_index"], 1, MAX_SCOPES)
            or p["ordinal"] != 2 * p["scope_index"] - (name == REGISTER)):
        return False
    if name == REGISTER:
        return True
    outcome, status, reason = p["operation_outcome"], p["clock_status"], p["reason"]
    if not all(isinstance(v, str) for v in (outcome, status, reason)):
        return False
    if outcome == "not_started":
        return (status == "not_started" and p["cpu_delta_ns"] is None
                and p["clock_resolution_ns"] is None and reason in {
                    "admission_rejected", "submit_failed", "pre_delegate_failure", "cancelled_before_entry"})
    if outcome not in {"completed", "failed"}:
        return False
    if status == "measured":
        return (reason == "none" and integer(p["cpu_delta_ns"])
                and integer(p["clock_resolution_ns"], 1, 1_000_000_000))
    return (status == "unavailable" and reason in {"invalid_clock", "clock_unavailable"}
            and p["cpu_delta_ns"] is None and p["clock_resolution_ns"] is None)


def measure_preprocessing_worker_cpu(events, *, expected_source_scope, run_status,
                                     evidence_incomplete=False, uninspectable_event_names=frozenset()):
    def result(status, note, value=None, breakdown=None):
        return {"status": status, "value": value, "breakdown": breakdown, "note": note}

    def missing(note):
        return result("not_available", note)

    if evidence_incomplete or any(n.startswith(PREFIX) for n in uninspectable_event_names):
        return missing("Worker CPU evidence window/payloads are incomplete or uninspectable.")
    rows = [e for e in events if e.event_name.startswith(PREFIX)]
    if not rows:
        return result("not_instrumented", "No worker-thread CPU producer evidence.")
    if len(rows) > 19:
        return missing("Worker CPU evidence exceeds the bounded event count.")
    slots, identity = {}, None
    for row in rows:
        p = row.payload
        if not valid_payload(row.event_name, p) or row.event_name == INVALID:
            return missing("Worker CPU payload is invalid or its root was invalidated.")
        current = tuple(p[k] for k in sorted(COMMON))
        if identity is not None and identity != current:
            return missing("Worker CPU roots/revisions/identities are mixed.")
        identity = current
        if p["source_scope_id"] != expected_source_scope or p["ordinal"] in slots:
            return missing("Worker CPU source mismatch or duplicate logical ordinal.")
        slots[p["ordinal"]] = row
    ends = [e for e in rows if e.event_name == END]
    if len(ends) != 1 or 0 not in slots or slots[0].event_name != START:
        return missing("Worker CPU requires exactly one start and terminal.")
    end = ends[0].payload
    count = end["scope_count"]
    if (not end["complete"] or end["logical_outcome"] != "completed" or run_status != "succeeded"
            or count == 0 or sorted(slots) != list(range(2 * count + 2))):
        return missing("Worker CPU has no complete successful entered-operation coverage.")
    scopes, seen, total = [], set(), 0
    for index in range(1, count + 1):
        start, terminal = slots[2 * index - 1], slots[2 * index]
        p = terminal.payload
        if (start.event_name != REGISTER or terminal.event_name != SCOPE_END
                or start.payload["scope_id"] != p["scope_id"] or p["scope_id"] in seen
                or p["operation_outcome"] != "completed" or p["clock_status"] != "measured"):
            return missing("Worker CPU scope set is duplicated, unentered, failed or unmeasured.")
        seen.add(p["scope_id"])
        total += p["cpu_delta_ns"]
        scopes.append(p)
    if total > MAX_NS:
        return missing("Worker CPU sum exceeds the exact-integer contract.")
    return result("observed", "Current-worker thread CPU only; excludes native helpers and other processes. "
                  "Not the required complete preprocessing CPU metric.", total / 1e9,
                  {"method": METHOD, "measurement_scope": "worker_thread_only", "scopes": scopes,
                   "backend_revision": end["backend_revision"]})
