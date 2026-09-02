"""Dependency-light Reader evidence validation for the offline baseline collector."""
import math
import re

REQUEST_EVENT = "S0_READER_OPEN_REQUEST_MEASURED"
TERMINAL_EVENT = "S0_READER_OPEN_TERMINAL"
MEASUREMENT_SCOPE = "reader_v2_core_open_v1"
MAX_REQUESTS = 4
MAX_OPENS = 32
_SHA = re.compile(r"^[0-9a-f]{40}$")
_OPEN = re.compile(r"^reader_[0-9a-f]{32}$")
_CANDIDATE = re.compile(r"^candidate_[0-9a-f]{16}$")

def _integer(value, low=0, high=100000):
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _duration(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value) and 0 <= value <= 3600
    except OverflowError:
        return False


def measure_reader_open(events, *, evidence_incomplete, uninspectable_event_names):
    """Summarize complete core opens by mode; duplicates/gaps remain unavailable."""
    def missing(reason):
        return {"status": "not_available", "latency": None, "queries": None, "breakdown": None, "note": reason}
    if {REQUEST_EVENT, TERMINAL_EVENT} & uninspectable_event_names:
        return missing("Reader evidence contains malformed or oversized events.")
    scopes = {}
    for e in events:
        if e.event_name not in {REQUEST_EVENT, TERMINAL_EVENT}:
            continue
        p = e.payload
        common = {"measurement_scope", "open_scope_id", "candidate_scope_id", "backend_revision", "succeeded"}
        fields = common | ({"ordinal", "route", "server_seconds", "query_count", "node_limit", "window_start"}
            if e.event_name == REQUEST_EVENT else {"mode", "duration_seconds", "request_count", "frontend_revision"})
        if not isinstance(p, dict) or set(p) != fields:
            return missing("Reader evidence contains unexpected or missing fields.")
        sid = p.get("open_scope_id")
        if (not isinstance(sid, str) or not _OPEN.fullmatch(sid) or p.get("measurement_scope") != MEASUREMENT_SCOPE
                or p.get("succeeded") is not True or not isinstance(p.get("candidate_scope_id"), str)
                or not _CANDIDATE.fullmatch(p["candidate_scope_id"]) or not isinstance(p.get("backend_revision"), str)
                or not _SHA.fullmatch(p["backend_revision"])):
            return missing("Invalid Reader scope or identity contract.")
        group = scopes.setdefault(sid, {"requests": {}, "terminal": None})
        if len(scopes) > MAX_OPENS:
            return missing("Reader open count exceeds bounded snapshot contract.")
        if e.event_name == TERMINAL_EVENT:
            if group["terminal"] is not None:
                return missing("Duplicate Reader terminal.")
            group["terminal"] = p
        else:
            ordinal = p.get("ordinal")
            if not _integer(ordinal, 1, MAX_REQUESTS) or ordinal in group["requests"]:
                return missing("Duplicate or invalid Reader request ordinal.")
            group["requests"][ordinal] = p
    if not scopes:
        return missing("No core Reader-open evidence for this processing run.")
    complete = []
    for sid, group in sorted(scopes.items()):
        t = group["terminal"]
        if (t is None or t.get("mode") not in ("first_open", "reopen") or not _duration(t.get("duration_seconds"))
                or not _integer(t.get("request_count"), 3, MAX_REQUESTS) or not isinstance(t.get("frontend_revision"), str)
                or not _SHA.fullmatch(t["frontend_revision"])):
            return missing("Missing or invalid Reader terminal contract.")
        count = t["request_count"]
        if sorted(group["requests"]) != list(range(1, count + 1)):
            return missing("Reader request sequence is incomplete.")
        rows = [group["requests"][i] for i in range(1, count + 1)]
        expected = ["metadata", "navigation"] + ["content"] * (count - 2)
        if t["mode"] == "first_open" and count != 3:
            return missing("First open must contain exactly one bounded content request.")
        for row, route in zip(rows, expected):
            if (row.get("route") != route or row["candidate_scope_id"] != t["candidate_scope_id"]
                    or row["backend_revision"] != t["backend_revision"] or not _duration(row.get("server_seconds"))
                    or not _integer(row.get("query_count")) or not _integer(row.get("node_limit"), 0, 150)
                    or row.get("node_limit") != (150 if route == "content" else 0)
                    or not _integer(row.get("window_start"), 0, 999999999) or row["window_start"] % 150):
                return missing("Reader request coverage, candidate or revision changed.")
        if (any(r["window_start"] != 0 for r in rows[:2])
                or (t["mode"] == "first_open" and rows[2]["window_start"] != 0)
                or (count == 4 and rows[3]["window_start"] != rows[2]["window_start"] + 150)):
            return missing("Reader content windows do not match the bounded open contract.")
        complete.append({"open_scope_id": sid, "mode": t["mode"], "frontend_revision": t["frontend_revision"],
            "backend_revision": t["backend_revision"], "duration_seconds": t["duration_seconds"],
            "query_count": sum(r["query_count"] for r in rows), "request_count": count,
            "server_request_seconds_sum": round(sum(r["server_seconds"] for r in rows), 6)})
    if len({(r["backend_revision"], r["frontend_revision"]) for r in complete}) != 1:
        return missing("Mixed revisions require separate Reader acceptance runs.")
    latency, queries = {}, {}
    for mode in ("first_open", "reopen"):
        rows = [r for r in complete if r["mode"] == mode]
        if rows:
            latency[mode] = {"sample_count": len(rows), "mean_seconds": round(sum(r["duration_seconds"] for r in rows) / len(rows), 6)}
            queries[mode] = {"sample_count": len(rows), "counts": [r["query_count"] for r in rows]}
    return {"status": "partial" if evidence_incomplete else "observed", "latency": latency, "queries": queries,
        "breakdown": complete, "note": "Only listed modes were observed. Core semantic render boundary; excludes binary assets, browser paint and later interactions. SQL statement attempts are measured, not row/byte bounds. Client timing is client-reported."}
