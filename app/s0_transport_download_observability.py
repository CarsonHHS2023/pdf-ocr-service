"""Staging-only S0 Provider source-transport boundary observability.

Measures only facts Atlas owns: the allowlisted source-delivery route selected
for one Provider grant and exact source-body bytes successfully emitted through
ASGI for Atlas fallback GETs. Consumer-side Provider/compute download bytes and
elapsed time are deliberately not inferred here.
"""
from __future__ import annotations

from functools import lru_cache
import re
from typing import Any

SOURCE_ROUTE_EVENT = "S0_PROVIDER_SOURCE_ROUTE_SELECTED"
BACKEND_BODY_EVENT = "S0_BACKEND_SOURCE_BODY_TRANSMITTED"
TRANSPORT_MEASUREMENT_SCOPE = "provider_source_transport_v1"
ROUTE_FALLBACK = "atlas_source_transport_fallback"
ROUTE_PRESIGNED = "presigned_object_get"
SOURCE_ROUTES = frozenset({ROUTE_FALLBACK, ROUTE_PRESIGNED})
TRANSPORT_STAGE = "provider_source_transport"
_SCOPE_ID_RE = re.compile(r"^transport_[0-9a-f]{16}$")


def _enabled() -> bool:
    try:
        from app.s0_object_store_io_observability import staging_storage_io_observability_enabled
        return bool(staging_storage_io_observability_enabled())
    except Exception:
        return False


def _scope_id(grant: object) -> str | None:
    try:
        from app.s0_transport_scope_terminal_observability import transport_scope_id
        value = transport_scope_id(getattr(grant, "grant_id", None))
    except Exception:
        return None
    if not isinstance(value, str) or _SCOPE_ID_RE.fullmatch(value) is None:
        return None
    return value


def _identity(grant: object) -> tuple[str, str, str] | None:
    processing_run_id = str(getattr(grant, "atlas_attempt_id", "") or "").strip()
    document_id = str(getattr(grant, "document_id", "") or "").strip()
    scope_id = _scope_id(grant)
    if not processing_run_id or not document_id or scope_id is None:
        return None
    return processing_run_id, document_id, scope_id


def _safe_positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def record_provider_source_route_selected(grant: object, route: str) -> bool:
    """Persist one privacy-safe route decision for a Provider transport scope."""
    if not _enabled() or route not in SOURCE_ROUTES:
        return False
    identity = _identity(grant)
    source_size = _safe_positive_int(getattr(grant, "source_byte_size", None))
    if identity is None or source_size is None:
        return False
    processing_run_id, document_id, scope_id = identity
    try:
        from app.processing.processing_events import record_processing_event
        return bool(record_processing_event(
            processing_run_id=processing_run_id,
            document_id=document_id,
            event_name=SOURCE_ROUTE_EVENT,
            severity="info",
            payload={
                "succeeded": True,
                "measurement_scope": TRANSPORT_MEASUREMENT_SCOPE,
                "stage": TRANSPORT_STAGE,
                "scope_id": scope_id,
                "route": route,
                "source_object_size_bytes": source_size,
            },
        ))
    except Exception:
        return False


def record_backend_source_body_transmitted(
    grant: object,
    retrieval_ordinal: int,
    *,
    body_bytes: int,
    body_messages: int,
) -> bool:
    """Persist one completed Atlas fallback ASGI source-body transmission."""
    if not _enabled():
        return False
    identity = _identity(grant)
    ordinal = _safe_positive_int(retrieval_ordinal)
    byte_count = _safe_positive_int(body_bytes)
    message_count = _safe_positive_int(body_messages)
    if identity is None or ordinal is None or byte_count is None or message_count is None:
        return False
    processing_run_id, document_id, scope_id = identity
    try:
        from app.processing.processing_events import record_processing_event
        return bool(record_processing_event(
            processing_run_id=processing_run_id,
            document_id=document_id,
            event_name=BACKEND_BODY_EVENT,
            severity="info",
            payload={
                "succeeded": True,
                "measurement_scope": TRANSPORT_MEASUREMENT_SCOPE,
                "stage": TRANSPORT_STAGE,
                "scope_id": scope_id,
                "scope_ordinal": ordinal,
                "route": ROUTE_FALLBACK,
                "body_bytes": byte_count,
                "body_messages": message_count,
            },
        ))
    except Exception:
        return False


@lru_cache(maxsize=None)
def _observed_response_type(base_response_type: type) -> type:
    """Create a Response subclass lazily without importing FastAPI/Starlette here."""
    class S0ObservedSourceTransportResponse(base_response_type):  # type: ignore[misc,valid-type]
        async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
            sent_body_bytes = 0
            sent_body_messages = 0
            completed = False

            async def observed_send(message: dict[str, Any]) -> None:
                nonlocal sent_body_bytes, sent_body_messages, completed
                await send(message)
                if message.get("type") != "http.response.body":
                    return
                body = message.get("body", b"")
                if isinstance(body, (bytes, bytearray, memoryview)):
                    sent_body_bytes += len(body)
                sent_body_messages += 1
                if not bool(message.get("more_body", False)):
                    completed = True

            await super().__call__(scope, receive, observed_send)
            binding = getattr(self, "_atlas_s0_transport_binding", None)
            if completed and binding is not None:
                grant, retrieval_ordinal = binding
                record_backend_source_body_transmitted(
                    grant,
                    retrieval_ordinal,
                    body_bytes=sent_body_bytes,
                    body_messages=sent_body_messages,
                )

    S0ObservedSourceTransportResponse.__name__ = f"S0Observed{getattr(base_response_type, '__name__', 'Response')}"
    return S0ObservedSourceTransportResponse


def build_source_transport_response(base_response_type: type, *args: Any, **kwargs: Any) -> object:
    return _observed_response_type(base_response_type)(*args, **kwargs)


def bind_source_transport_response(response: object, grant: object, retrieval_ordinal: int) -> bool:
    if _identity(grant) is None or _safe_positive_int(retrieval_ordinal) is None:
        return False
    try:
        setattr(response, "_atlas_s0_transport_binding", (grant, retrieval_ordinal))
    except Exception:
        return False
    return True


def measure_backend_source_transport(
    decoded_events: Any,
    *,
    evidence_incomplete: bool,
    uninspectable_event_names: frozenset[str],
) -> tuple[int | None, object | None, int | None, str, str | None]:
    """Validate route/send/terminal evidence and return Backend source-body bytes."""
    terminal_event_name = "S0_OBJECT_STORE_TRANSPORT_SCOPE_TERMINAL"
    sharding_decision_name = "PDF_PROVIDER_TRANSPORT_SHARDING_DECISION"
    sharding_terminal_name = "PDF_PROVIDER_TRANSPORT_SHARDING_TERMINAL"
    provider_measurement_name = "PDF_S0_PROVIDER_INTEGRATION_MEASURED"
    relevant = {
        SOURCE_ROUTE_EVENT,
        BACKEND_BODY_EVENT,
        terminal_event_name,
        sharding_decision_name,
        sharding_terminal_name,
        provider_measurement_name,
    }
    if relevant.intersection(uninspectable_event_names):
        return None, None, None, "not_available", "At least one Provider source-transport contract event could not be inspected."

    events = tuple(decoded_events)
    provider_events = [e for e in events if e.event_name == provider_measurement_name]
    successful_provider = [e for e in provider_events if e.payload.get("succeeded") is True]
    if len(provider_events) != 1 or len(successful_provider) != 1:
        return None, None, None, "not_available", "Exactly one successful Provider integration measurement is required to close source transport."

    decisions = [e for e in events if e.event_name == sharding_decision_name]
    if len(decisions) != 1:
        return None, None, None, "not_available", "Exactly one Provider sharding decision is required to prove the expected transport scope count."
    decision = decisions[0].payload
    sharding_required = decision.get("sharding_required")
    selected = decision.get("provider_input_size_bytes")
    if not isinstance(sharding_required, bool):
        return None, None, None, "not_available", "Provider sharding_required evidence is invalid."
    if isinstance(selected, bool) or not isinstance(selected, int) or selected <= 0:
        return None, None, None, "not_available", "Provider-selected payload size evidence is invalid."

    shard_terminals = [e for e in events if e.event_name == sharding_terminal_name]
    successful_shard_terminals = [e for e in shard_terminals if e.payload.get("succeeded") is True]
    if len(shard_terminals) > 1 or (shard_terminals and len(successful_shard_terminals) != 1):
        return None, None, None, "not_available", "Provider sharding terminal evidence is ambiguous."
    if sharding_required:
        if len(successful_shard_terminals) != 1:
            return None, None, None, "not_available", "Provider sharding was required but no successful terminal shard-count proof is retained."
        shard_count = successful_shard_terminals[0].payload.get("shard_count")
        if isinstance(shard_count, bool) or not isinstance(shard_count, int) or shard_count < 1:
            return None, None, None, "not_available", "Provider terminal shard count is invalid."
        expected_scope_count = shard_count
    else:
        if successful_shard_terminals:
            return None, None, None, "not_available", "Provider sharding decision and terminal evidence disagree."
        expected_scope_count = 1

    terminal_counts: dict[str, int] = {}
    for event in (e for e in events if e.event_name == terminal_event_name):
        payload = event.payload
        scope_id = payload.get("scope_id")
        count = payload.get("terminal_retrieval_count")
        if (
            payload.get("succeeded") is not True
            or payload.get("stage") != TRANSPORT_STAGE
            or not isinstance(scope_id, str)
            or _SCOPE_ID_RE.fullmatch(scope_id) is None
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
        ):
            return None, None, None, "not_available", "Transport terminal proof is invalid."
        if scope_id in terminal_counts:
            return None, None, None, "not_available", "Duplicate transport terminal scope is ambiguous."
        terminal_counts[scope_id] = count
    if len(terminal_counts) != expected_scope_count:
        return None, None, None, "not_available", "Terminal proof is not retained for every expected Provider transport scope."

    routes: dict[str, tuple[str, int]] = {}
    for event in (e for e in events if e.event_name == SOURCE_ROUTE_EVENT):
        payload = event.payload
        scope_id = payload.get("scope_id")
        route = payload.get("route")
        source_size = payload.get("source_object_size_bytes")
        if (
            payload.get("succeeded") is not True
            or payload.get("measurement_scope") != TRANSPORT_MEASUREMENT_SCOPE
            or payload.get("stage") != TRANSPORT_STAGE
            or not isinstance(scope_id, str)
            or _SCOPE_ID_RE.fullmatch(scope_id) is None
            or route not in SOURCE_ROUTES
            or isinstance(source_size, bool)
            or not isinstance(source_size, int)
            or source_size <= 0
        ):
            return None, None, None, "not_available", "Provider source-route evidence is invalid."
        if scope_id in routes:
            return None, None, None, "not_available", "Duplicate Provider source-route evidence is ambiguous."
        routes[scope_id] = (route, source_size)
    if set(routes) != set(terminal_counts):
        return None, None, None, "not_available", "A unique route decision is not retained for every terminal Provider transport scope."

    body_events: dict[str, dict[int, tuple[int, int]]] = {}
    for event in (e for e in events if e.event_name == BACKEND_BODY_EVENT):
        payload = event.payload
        scope_id = payload.get("scope_id")
        ordinal = payload.get("scope_ordinal")
        body_bytes = payload.get("body_bytes")
        body_messages = payload.get("body_messages")
        if (
            payload.get("succeeded") is not True
            or payload.get("measurement_scope") != TRANSPORT_MEASUREMENT_SCOPE
            or payload.get("stage") != TRANSPORT_STAGE
            or payload.get("route") != ROUTE_FALLBACK
            or not isinstance(scope_id, str)
            or _SCOPE_ID_RE.fullmatch(scope_id) is None
            or isinstance(ordinal, bool)
            or not isinstance(ordinal, int)
            or ordinal < 1
            or isinstance(body_bytes, bool)
            or not isinstance(body_bytes, int)
            or body_bytes <= 0
            or isinstance(body_messages, bool)
            or not isinstance(body_messages, int)
            or body_messages < 1
        ):
            return None, None, None, "not_available", "Backend ASGI source-body evidence is invalid."
        by_ordinal = body_events.setdefault(scope_id, {})
        if ordinal in by_ordinal:
            return None, None, None, "not_available", "Duplicate Backend source-body ordinal is ambiguous."
        by_ordinal[ordinal] = (body_bytes, body_messages)

    total_backend_body_bytes = 0
    scope_rows: list[dict[str, object]] = []
    for scope_id in sorted(terminal_counts):
        terminal_count = terminal_counts[scope_id]
        route, source_size = routes[scope_id]
        sent = body_events.get(scope_id, {})
        if route == ROUTE_PRESIGNED:
            if terminal_count != 0 or sent:
                return None, None, None, "not_available", "Presigned Provider source access conflicts with Backend fallback retrieval/transmission evidence."
            scope_body_bytes = 0
        else:
            expected_ordinals = set(range(1, terminal_count + 1))
            if set(sent) != expected_ordinals:
                return None, None, None, "not_available", "Backend source-body transmission evidence does not match the post-revoke retrieval count."
            scope_body_bytes = 0
            for ordinal in sorted(sent):
                body_bytes, _body_messages = sent[ordinal]
                if body_bytes != source_size:
                    return None, None, None, "not_available", "A completed Backend fallback source body does not match its selected source object size."
                scope_body_bytes += body_bytes
        total_backend_body_bytes += scope_body_bytes
        scope_rows.append({
            "scope_id": scope_id,
            "route": route,
            "source_object_size_bytes": source_size,
            "terminal_retrieval_count": terminal_count,
            "backend_source_body_bytes": scope_body_bytes,
        })

    if set(body_events) - set(terminal_counts):
        return None, None, None, "not_available", "Backend source-body evidence has an unknown transport scope."

    breakdown = {
        "measurement_scope": TRANSPORT_MEASUREMENT_SCOPE,
        "provider_selected_payload_bytes": selected,
        "source_object_total_bytes": sum(int(row["source_object_size_bytes"]) for row in scope_rows),
        "backend_source_body_bytes": total_backend_body_bytes,
        "scopes": scope_rows,
    }
    status = "partial" if evidence_incomplete else "observed"
    note = "The bounded event/payload evidence for this snapshot is incomplete." if evidence_incomplete else None
    return total_backend_body_bytes, breakdown, selected, status, note


__all__ = [
    "BACKEND_BODY_EVENT",
    "ROUTE_FALLBACK",
    "ROUTE_PRESIGNED",
    "SOURCE_ROUTE_EVENT",
    "SOURCE_ROUTES",
    "TRANSPORT_MEASUREMENT_SCOPE",
    "TRANSPORT_STAGE",
    "bind_source_transport_response",
    "build_source_transport_response",
    "measure_backend_source_transport",
    "record_backend_source_body_transmitted",
    "record_provider_source_route_selected",
]
