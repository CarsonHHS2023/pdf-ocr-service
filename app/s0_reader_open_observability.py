"""Staging-only Reader core-open evidence. Never retain SQL, content or URLs."""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
from time import perf_counter
from urllib.parse import parse_qs

from fastapi import Request, Response
from sqlalchemy import event, select

REQUEST_EVENT = "S0_READER_OPEN_REQUEST_MEASURED"
TERMINAL_EVENT = "S0_READER_OPEN_TERMINAL"
MEASUREMENT_SCOPE = "reader_v2_core_open_v1"
MAX_REQUESTS = 4
MAX_OPENS = 32
_REVISION_FILE = Path(__file__).resolve().parents[1] / "staging-revision.txt"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_OPEN = re.compile(r"^reader_[0-9a-f]{32}$")
_CANDIDATE = re.compile(r"^candidate_[0-9a-f]{16}$")
_PATH = re.compile(r"^/api/reader/v2/documents/([^/]{1,255})(/navigation|/content)?$")


def revision():
    try:
        value = _REVISION_FILE.read_text().strip()
        return value if _SHA.fullmatch(value) else None
    except OSError:
        return None


def _integer(value, low=0, high=100000):
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _duration(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value) and 0 <= value <= 3600
    except OverflowError:
        return False


def _candidate_scope(candidate):
    return "candidate_" + hashlib.sha256(candidate.encode()).hexdigest()[:16]


@dataclass
class Observation:
    document: str
    candidate: str | None = None
    queries: int = 0
    active: bool = True


_CURRENT: ContextVar[Observation | None] = ContextVar("s0_reader_request", default=None)


def _before_execute(*args):
    observation = _CURRENT.get()
    if observation is not None and observation.active:
        observation.queries = min(100001, observation.queries + 1)


def observe_reader_view(view):
    observation = _CURRENT.get()
    if observation is not None and observation.document == view.document_ref:
        observation.candidate = view.candidate_id
    return view


def _persist(document, candidate, name, payload, session_factory=None):
    """Resolve immutable candidate's exact run; worker owns its entire session."""
    if revision() is None:
        return False
    from app.database import SessionLocal
    from app.models import ProcessingRun, encode_json_text
    from app.models_v2 import StructuredContentCandidateV2Record as Candidate
    from app.processing.processing_event_model import ProcessingEvent
    from app.processing.processing_events import PROCESSING_EVENT_SCHEMA_VERSION, staging_processing_events_enabled
    if not staging_processing_events_enabled():
        return False
    try:
        with (session_factory or SessionLocal)() as db:
            with db.begin():
                run_id = db.execute(select(ProcessingRun.processing_run_id).join(
                    Candidate, Candidate.processing_run_ref == ProcessingRun.processing_run_id,
                ).where(Candidate.document_id == document, Candidate.candidate_id == candidate,
                        ProcessingRun.document_id == document, ProcessingRun.status == "succeeded")).scalar_one_or_none()
                if run_id is None:
                    return False
                db.add(ProcessingEvent(processing_run_id=run_id, document_id=document,
                    schema_version=PROCESSING_EVENT_SCHEMA_VERSION, event_name=name, severity="info",
                    payload_json=encode_json_text({**payload, "candidate_scope_id": _candidate_scope(candidate)})))
        return True
    except Exception:
        return False


class ReaderOpenMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        backend_revision = revision()
        match = _PATH.fullmatch(scope.get("path", ""))
        headers = scope.get("headers", [])
        ids = [v.decode("ascii", errors="replace") for k, v in headers if k.lower() == b"x-atlas-s0-open"]
        ordinals = [v.decode("ascii", errors="replace") for k, v in headers if k.lower() == b"x-atlas-s0-ordinal"]
        if (scope.get("type") != "http" or scope.get("method") != "GET" or backend_revision is None
                or match is None or len(ids) != 1 or not _OPEN.fullmatch(ids[0]) or len(ordinals) != 1
                or ordinals[0] not in {"1", "2", "3", "4"}):
            return await self.app(scope, receive, send)
        route = {None: "metadata", "/navigation": "navigation", "/content": "content"}[match[2]]
        window_start = 0
        if route == "content":
            query = parse_qs(scope.get("query_string", b"").decode("ascii", errors="replace"))
            starts = query.get("start_node_order", ["0"])
            if query.get("limit") != ["150"] or len(starts) != 1 or not re.fullmatch(r"[0-9]{1,9}", starts[0]):
                return await self.app(scope, receive, send)
            window_start = int(starts[0])
            if window_start % 150:
                return await self.app(scope, receive, send)
        observation = Observation(match[1])
        token = _CURRENT.set(observation)
        started = perf_counter()
        completed, code, duration = False, 0, None

        async def measured_send(message):
            nonlocal completed, code, duration
            if message["type"] == "http.response.start":
                code = message["status"]
                response_headers = list(message.get("headers", []))
                response_headers.append((b"x-atlas-s0-revision", backend_revision.encode()))
                exposed = [v for k, v in response_headers if k.lower() == b"access-control-expose-headers"]
                response_headers = [(k, v) for k, v in response_headers if k.lower() != b"access-control-expose-headers"]
                response_headers.append((b"access-control-expose-headers", b", ".join(exposed + [b"X-Atlas-S0-Revision"])))
                message = {**message, "headers": response_headers}
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                duration = perf_counter() - started
                completed = True
                observation.active = False

        try:
            await self.app(scope, receive, measured_send)
        finally:
            observation.active = False
            _CURRENT.reset(token)
            if completed and code == 200 and observation.candidate and _duration(duration) and _integer(observation.queries):
                payload = {"measurement_scope": MEASUREMENT_SCOPE, "open_scope_id": ids[0],
                    "ordinal": int(ordinals[0]), "route": route, "succeeded": True,
                    "backend_revision": backend_revision, "server_seconds": round(duration, 6),
                    "query_count": observation.queries, "node_limit": 150 if route == "content" else 0,
                    "window_start": window_start}
                try:
                    await asyncio.to_thread(_persist, observation.document, observation.candidate, REQUEST_EVENT, payload)
                except Exception:
                    pass  # Evidence failure must not alter the delivered Reader response.


async def terminal(request: Request, document_ref: str):
    current_revision = revision()
    if current_revision is None:
        return Response(status_code=404)
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > 2048:
            return Response(status_code=413)
        data.extend(chunk)
    try:
        body = json.loads(data)
        fields = {"open_scope_id", "candidate_id", "frontend_revision", "backend_revision", "mode", "request_count", "duration_seconds"}
        valid = (isinstance(body, dict) and set(body) == fields
            and isinstance(body["open_scope_id"], str) and _OPEN.fullmatch(body["open_scope_id"])
            and isinstance(body["candidate_id"], str) and 1 <= len(body["candidate_id"]) <= 255
            and isinstance(body["frontend_revision"], str) and _SHA.fullmatch(body["frontend_revision"])
            and body["backend_revision"] == current_revision
            and body["mode"] in ("first_open", "reopen")
            and _integer(body["request_count"], 3, MAX_REQUESTS) and _duration(body["duration_seconds"]))
        if not valid:
            return Response(status_code=422)
    except (ValueError, TypeError, KeyError):
        return Response(status_code=422)
    payload = {key: body[key] for key in fields - {"candidate_id"}}
    payload.update(measurement_scope=MEASUREMENT_SCOPE, succeeded=True)
    try:
        persisted = await asyncio.to_thread(_persist, document_ref, body["candidate_id"], TERMINAL_EVENT, payload)
    except Exception:
        persisted = False
    return Response(status_code=204 if persisted else 503)


def install(app):
    if revision() is None or getattr(app.state, "s0_reader_open_installed", False):
        return
    from app.database import engine
    if not event.contains(engine, "before_cursor_execute", _before_execute):
        event.listen(engine, "before_cursor_execute", _before_execute)
    app.add_middleware(ReaderOpenMiddleware)
    app.add_api_route("/api/reader/v2/documents/{document_ref}/s0-open", terminal, methods=["POST"], include_in_schema=False)
    app.state.s0_reader_open_installed = True


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
