"""Strict, dependency-light validation of backend-owned S0.3.6 counters."""
import re

START_EVENT = "S0_FAILURE_RETRY_RUN_STARTED"
SCOPE_EVENT = "S0_FAILURE_RETRY_SCOPE_TERMINAL"
TERMINAL_EVENT = "S0_FAILURE_RETRY_RUN_TERMINAL"
EVENT_NAMES = frozenset((START_EVENT, SCOPE_EVENT, TERMINAL_EVENT))
MEASUREMENT_SCOPE = "backend_pdf_invocation_attempts_v1"
MAX_SCOPES = 128
MAX_COUNT = 100000
OPERATIONS = ("submit", "status", "result", "artifact")
COUNTERS = ("attempts", "succeeded", "failed", "cancelled", "not_ready", "retryable_failures", "retries")
OUTCOMES = ("completed", "failed", "cancelled")
PROVIDER_STATES = ("unknown", "provider_completed", "provider_partial_failed", "failed", "expired")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_SPAN = re.compile(r"^attempts_[0-9a-f]{32}$")
_SOURCE = re.compile(r"^source_[0-9a-f]{16}$")
_PROVIDER = re.compile(r"^provider_[0-9a-f]{16}$")


def integer(value, low=0, high=MAX_COUNT):
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def measure_failure_retry(events, *, source_scope_id, evidence_incomplete, uninspectable_event_names):
    """Never sum failures across layers or infer zero from absent scope evidence."""
    def missing(note):
        return {"status": "not_available", "value": None, "breakdown": None, "note": note}

    if EVENT_NAMES & uninspectable_event_names:
        return missing("Failure/retry evidence contains malformed or oversized events.")
    starts, terminals, scopes = [], [], {}
    common = {"measurement_scope", "run_scope_id", "source_scope_id", "backend_revision"}
    identity = None
    for event in events:
        if event.event_name not in EVENT_NAMES:
            continue
        p = event.payload
        fields = common | ({"ordinal", "provider_scope_id", "outcome", "provider_terminal_status", "operations"}
            if event.event_name == SCOPE_EVENT else {"scope_count", "outcome", "complete"}
            if event.event_name == TERMINAL_EVENT else set())
        if not isinstance(p, dict) or set(p) != fields:
            return missing("Failure/retry evidence has unexpected or missing fields.")
        if (p["measurement_scope"] != MEASUREMENT_SCOPE
                or not isinstance(p["run_scope_id"], str) or not _SPAN.fullmatch(p["run_scope_id"])
                or not isinstance(p["source_scope_id"], str) or not _SOURCE.fullmatch(p["source_scope_id"])
                or p["source_scope_id"] != source_scope_id
                or not isinstance(p["backend_revision"], str) or not _SHA.fullmatch(p["backend_revision"])):
            return missing("Failure/retry identity contract is invalid.")
        current = tuple(p[k] for k in sorted(common))
        if identity is not None and identity != current:
            return missing("Multiple invocation spans or mixed revisions are ambiguous.")
        identity = current
        if event.event_name == START_EVENT:
            starts.append(p)
        elif event.event_name == TERMINAL_EVENT:
            terminals.append(p)
        else:
            ordinal = p["ordinal"]
            if not integer(ordinal, 1, MAX_SCOPES) or ordinal in scopes:
                return missing("Duplicate or invalid Provider invocation ordinal.")
            scopes[ordinal] = p
    if len(starts) != 1 or len(terminals) != 1:
        return missing("Exactly one logical invocation start and terminal are required.")
    terminal = terminals[0]
    count = terminal["scope_count"]
    if (terminal["complete"] is not True or terminal["outcome"] not in OUTCOMES
            or not integer(count, 0, MAX_SCOPES) or sorted(scopes) != list(range(1, count + 1))):
        return missing("Logical invocation coverage is incomplete or exceeds bounds.")
    totals = {key: 0 for key in COUNTERS}
    outcomes = {key: 0 for key in OUTCOMES}
    provider_states = {key: 0 for key in PROVIDER_STATES}
    providers = set()
    rows = []
    for ordinal in sorted(scopes):
        p = scopes[ordinal]
        sid = p["provider_scope_id"]
        if (not isinstance(sid, str) or not _PROVIDER.fullmatch(sid) or sid in providers
                or p["outcome"] not in OUTCOMES or p["provider_terminal_status"] not in PROVIDER_STATES
                or not isinstance(p["operations"], dict) or set(p["operations"]) != set(OPERATIONS)):
            return missing("Provider invocation identity or terminal is invalid/duplicated.")
        providers.add(sid)
        for operation, values in p["operations"].items():
            if (not isinstance(values, dict) or set(values) != set(COUNTERS)
                    or not all(integer(v) for v in values.values())):
                return missing("Invalid bounded operation counters.")
            if (values["attempts"] != sum(values[k] for k in ("succeeded", "failed", "cancelled", "not_ready"))
                    or values["retryable_failures"] > values["failed"]
                    or values["retries"] > min(values["retryable_failures"], max(0, values["attempts"] - 1))
                    or (operation != "result" and values["not_ready"] != 0)
                    or (operation in ("submit", "artifact") and values["retries"] != 0)):
                return missing("Operation terminal counts or retry semantics are inconsistent.")
            for key in COUNTERS:
                totals[key] += values[key]
        outcomes[p["outcome"]] += 1
        provider_states[p["provider_terminal_status"]] += 1
        rows.append(p)
    return {
        "status": "partial" if evidence_incomplete else "observed",
        "value": {"backend_provider_calls": totals, "orchestration_invocations": outcomes,
                  "provider_terminal_observations": provider_states,
                  "logical_pdf_invocation": {"outcome": terminal["outcome"], "count": 1}},
        "breakdown": {"measurement_scope": MEASUREMENT_SCOPE, "scopes": rows,
                      "backend_revision": terminal["backend_revision"]},
        "note": "Backend-owned Provider method-call attempts only; layers are independent, not additive. "
                "Normal polls and RESULT_NOT_READY waits are not retries. Provider-internal retries, "
                "queue redelivery and other HTTP/LLM clients are outside this contract. "
                + ("Bounded snapshot evidence is incomplete." if evidence_incomplete else "Complete logical PDF invocation coverage."),
    }
