"""Strict S0 visual-asset generation wall-time contract and collector."""
from __future__ import annotations

import hashlib
import json
import re


PREFIX = "S0_VISUAL_ASSET_GENERATION_"
START = PREFIX + "RUN_STARTED"
TERMINAL = PREFIX + "RUN_TERMINAL"
EVENT_NAMES = frozenset((START, TERMINAL))

VERSION = "atlas.s0.visual-asset-generation.v1"
METHOD = "pdf_canonicalization_visual_enrichment_wall_v1"
MEASUREMENT_SCOPE = "candidate_visual_enrichment"
MAX_NS = 2**53 - 1
MAX_COUNT = 1_000_000

_COMMON = frozenset(
    (
        "contract_version",
        "measurement_scope",
        "method",
        "observation_id",
        "source_scope_id",
        "backend_revision",
    )
)
_PATTERNS = {
    "observation_id": r"vasset_[0-9a-f]{32}",
    "source_scope_id": r"source_[0-9a-f]{64}",
    "backend_revision": r"[0-9a-f]{40}",
}
_OUTCOMES = frozenset(("completed", "failed", "not_required", "invalid"))
_CLOCK_STATUSES = frozenset(("measured", "unavailable", "not_started"))
_REASONS = frozenset(
    (
        "none",
        "delegate_failed",
        "no_visual_enrichment_call",
        "multiple_visual_enrichment_calls",
        "clock_unavailable",
        "invalid_clock",
        "invalid_result_counts",
    )
)


def integer(value: object, low: int = 0, high: int = MAX_NS) -> bool:
    return type(value) is int and low <= value <= high


def source_scope_id(value: object) -> str | None:
    if not isinstance(value, str) or not 1 <= len(value) <= 255:
        return None
    return "source_" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def decode_visual_asset_generation_payload(raw: object) -> tuple[dict, bool]:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError("non-finite JSON constant")

    try:
        value = json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=invalid_constant,
        )
    except (TypeError, ValueError, RecursionError):
        return {}, False
    return (value, True) if isinstance(value, dict) else ({}, False)


def valid_payload(name: object, payload: object) -> bool:
    extras = {
        START: {"ordinal"},
        TERMINAL: {
            "ordinal",
            "operation_outcome",
            "clock_status",
            "duration_ns",
            "generated_asset_count",
            "generated_rendition_count",
            "reason",
        },
    }
    if name not in extras or not isinstance(payload, dict):
        return False
    if set(payload) != _COMMON | extras[name]:
        return False
    if (
        payload["contract_version"] != VERSION
        or payload["method"] != METHOD
        or payload["measurement_scope"] != MEASUREMENT_SCOPE
    ):
        return False
    for key, pattern in _PATTERNS.items():
        value = payload.get(key)
        if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
            return False
    if name == START:
        return payload["ordinal"] == 0

    if payload["ordinal"] != 1:
        return False
    outcome = payload["operation_outcome"]
    clock_status = payload["clock_status"]
    reason = payload["reason"]
    if (
        not isinstance(outcome, str)
        or outcome not in _OUTCOMES
        or not isinstance(clock_status, str)
        or clock_status not in _CLOCK_STATUSES
        or not isinstance(reason, str)
        or reason not in _REASONS
    ):
        return False

    duration = payload["duration_ns"]
    assets = payload["generated_asset_count"]
    renditions = payload["generated_rendition_count"]
    if outcome == "not_required":
        return (
            clock_status == "not_started"
            and duration is None
            and assets is None
            and renditions is None
            and reason == "no_visual_enrichment_call"
        )
    if outcome == "invalid":
        return (
            clock_status == "unavailable"
            and duration is None
            and assets is None
            and renditions is None
            and reason
            in {"multiple_visual_enrichment_calls", "invalid_result_counts"}
        )
    if outcome == "failed":
        return (
            clock_status in {"measured", "unavailable"}
            and (integer(duration) if clock_status == "measured" else duration is None)
            and assets is None
            and renditions is None
            and reason
            in ({"delegate_failed"} if clock_status == "measured" else {"clock_unavailable", "invalid_clock"})
        )

    if not integer(assets, 0, MAX_COUNT) or not integer(renditions, 0, MAX_COUNT):
        return False
    if clock_status == "measured":
        return integer(duration) and reason == "none"
    return (
        clock_status == "unavailable"
        and duration is None
        and reason in {"clock_unavailable", "invalid_clock", "invalid_result_counts"}
    )


def measure_visual_asset_generation(
    events,
    *,
    expected_source_scope: str | None,
    run_status: str,
    evidence_incomplete: bool = False,
    uninspectable_event_names=frozenset(),
):
    def result(status, note, value=None, breakdown=None):
        return {
            "status": status,
            "value": value,
            "breakdown": breakdown,
            "note": note,
        }

    def unavailable(note):
        return result("not_available", note)

    if evidence_incomplete or any(
        isinstance(name, str) and name.startswith(PREFIX)
        for name in uninspectable_event_names
    ):
        return unavailable(
            "Visual-asset generation evidence is incomplete or uninspectable."
        )

    rows = [row for row in events if row.event_name.startswith(PREFIX)]
    if not rows:
        return result(
            "not_instrumented",
            "No visual-asset generation producer evidence.",
        )
    if len(rows) != 2:
        return unavailable(
            "Visual-asset generation requires exactly one start and one terminal."
        )

    slots = {}
    identity = None
    for row in rows:
        payload = row.payload
        if not valid_payload(row.event_name, payload):
            return unavailable("Visual-asset generation payload is invalid.")
        current = tuple(payload[key] for key in sorted(_COMMON))
        if identity is not None and identity != current:
            return unavailable(
                "Visual-asset generation roots, revisions or identities are mixed."
            )
        identity = current
        if payload["source_scope_id"] != expected_source_scope:
            return unavailable("Visual-asset generation source identity does not match.")
        ordinal = payload["ordinal"]
        if ordinal in slots:
            return unavailable("Visual-asset generation has a duplicate logical ordinal.")
        slots[ordinal] = row

    if (
        sorted(slots) != [0, 1]
        or slots[0].event_name != START
        or slots[1].event_name != TERMINAL
    ):
        return unavailable(
            "Visual-asset generation event order or terminal coverage is invalid."
        )

    terminal = slots[1].payload
    if terminal["operation_outcome"] == "not_required":
        return unavailable(
            "This run did not execute the visual-enrichment operation."
        )
    if (
        run_status != "succeeded"
        or terminal["operation_outcome"] != "completed"
        or terminal["clock_status"] != "measured"
    ):
        return unavailable(
            "Visual-asset generation lacks a measured successful operation on a succeeded run."
        )
    if (
        terminal["generated_asset_count"] < 1
        or terminal["generated_rendition_count"] < 1
    ):
        return unavailable(
            "Visual enrichment completed without both a generated asset and a durable rendition."
        )

    breakdown = {
        "method": METHOD,
        "measurement_scope": MEASUREMENT_SCOPE,
        "generated_asset_count": terminal["generated_asset_count"],
        "generated_rendition_count": terminal["generated_rendition_count"],
        "backend_revision": terminal["backend_revision"],
    }
    return result(
        "observed",
        "Exact wall time of the final PDF candidate visual-enrichment call; includes crop/render, configured visual transforms and rendition persistence, but excludes source-PDF read, structure refinement, SPR persistence and candidate database commit.",
        terminal["duration_ns"] / 1e9,
        breakdown,
    )


__all__ = [
    "EVENT_NAMES",
    "MAX_COUNT",
    "MAX_NS",
    "METHOD",
    "PREFIX",
    "START",
    "TERMINAL",
    "VERSION",
    "decode_visual_asset_generation_payload",
    "integer",
    "measure_visual_asset_generation",
    "source_scope_id",
    "valid_payload",
]
