"""Staging-only S0 Provider/compute source-download observability.

Consumes the bounded Provider result contract emitted by paddle-vl-api and
persists only privacy-safe bytes/duration evidence. The collector intentionally
correlates Provider download sizes with Atlas transport-scope object sizes as a
multiset; it never substitutes Provider-selected payload bytes, Backend ASGI
body bytes, or Provider integration wall time for this consumer boundary.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import math
import re
from typing import Any

PROVIDER_DOWNLOAD_EVENT = "S0_PROVIDER_SOURCE_DOWNLOAD_MEASURED"
PROVIDER_DOWNLOAD_MEASUREMENT_SCOPE = "provider_source_download_v1"
_PROVIDER_SCOPE_RE = re.compile(r"^provider_[0-9a-f]{16}$")


def _enabled() -> bool:
    try:
        from app.s0_object_store_io_observability import staging_storage_io_observability_enabled
        return bool(staging_storage_io_observability_enabled())
    except Exception:
        return False


def provider_scope_id(provider_job_id: object) -> str | None:
    if not isinstance(provider_job_id, str) or not provider_job_id.strip():
        return None
    digest = hashlib.sha256(provider_job_id.encode("utf-8")).hexdigest()[:16]
    return f"provider_{digest}"


def _measurement_from_result(request: object, result: object) -> tuple[str, int, float] | None:
    scope_id = provider_scope_id(getattr(request, "provider_job_id", None))
    document_id = getattr(request, "document_id", None)
    payload = getattr(result, "raw_provider_payload", None)
    if scope_id is None or not isinstance(document_id, str) or not document_id.strip() or not isinstance(payload, dict):
        return None
    documents = payload.get("documents")
    if not isinstance(documents, list):
        return None
    matching = [
        item for item in documents
        if isinstance(item, dict) and item.get("document_id") == document_id
    ]
    if len(matching) != 1:
        return None
    measurement = matching[0].get("source_download")
    if not isinstance(measurement, dict):
        return None
    byte_count = measurement.get("bytes")
    duration = measurement.get("duration_seconds")
    if (
        measurement.get("succeeded") is not True
        or measurement.get("measurement_scope") != PROVIDER_DOWNLOAD_MEASUREMENT_SCOPE
        or isinstance(byte_count, bool)
        or not isinstance(byte_count, int)
        or byte_count <= 0
        or isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(float(duration))
        or float(duration) < 0
    ):
        return None
    return scope_id, byte_count, round(float(duration), 6)


def record_provider_source_download_from_result(request: object, result: object) -> bool:
    """Persist one bounded Provider consumer-download measurement, fail-open."""
    if not _enabled():
        return False
    measured = _measurement_from_result(request, result)
    if measured is None:
        return False
    scope_id, byte_count, duration = measured
    processing_run_id = str(getattr(request, "processing_attempt_id", "") or "").strip()
    document_id = str(getattr(request, "document_id", "") or "").strip()
    if not processing_run_id or not document_id:
        return False
    try:
        from app.processing.processing_events import record_processing_event
        return bool(record_processing_event(
            processing_run_id=processing_run_id,
            document_id=document_id,
            event_name=PROVIDER_DOWNLOAD_EVENT,
            severity="info",
            payload={
                "succeeded": True,
                "measurement_scope": PROVIDER_DOWNLOAD_MEASUREMENT_SCOPE,
                "provider_scope_id": scope_id,
                "download_bytes": byte_count,
                "download_duration_seconds": duration,
            },
        ))
    except Exception:
        return False


def measure_provider_source_download(
    decoded_events: Any,
    *,
    transport_breakdown: object | None,
    evidence_incomplete: bool,
    uninspectable_event_names: frozenset[str],
) -> tuple[int | None, float | None, object | None, str, str | None]:
    """Validate all expected compute downloads and return bytes/duration aggregates."""
    if PROVIDER_DOWNLOAD_EVENT in uninspectable_event_names:
        return None, None, None, "not_available", "At least one Provider source-download event could not be inspected."
    if not isinstance(transport_breakdown, dict):
        return None, None, None, "not_available", "Validated Atlas Provider transport-scope evidence is required before compute download evidence can be closed."
    scopes = transport_breakdown.get("scopes")
    if not isinstance(scopes, list) or not scopes:
        return None, None, None, "not_available", "Validated Atlas Provider transport scopes are missing."

    expected_sizes: list[int] = []
    for row in scopes:
        if not isinstance(row, dict):
            return None, None, None, "not_available", "Atlas transport-scope breakdown is malformed."
        size = row.get("source_object_size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            return None, None, None, "not_available", "Atlas transport-scope object-size evidence is invalid."
        expected_sizes.append(size)

    matching = [event for event in tuple(decoded_events) if event.event_name == PROVIDER_DOWNLOAD_EVENT]
    if len(matching) != len(expected_sizes):
        return None, None, None, "not_available", "Exactly one Provider source-download measurement is required for every expected Provider transport scope."

    rows: list[dict[str, object]] = []
    seen_scopes: set[str] = set()
    measured_sizes: list[int] = []
    total_seconds = 0.0
    for event in matching:
        payload = event.payload
        scope_id = payload.get("provider_scope_id")
        byte_count = payload.get("download_bytes")
        duration = payload.get("download_duration_seconds")
        if (
            payload.get("succeeded") is not True
            or payload.get("measurement_scope") != PROVIDER_DOWNLOAD_MEASUREMENT_SCOPE
            or not isinstance(scope_id, str)
            or _PROVIDER_SCOPE_RE.fullmatch(scope_id) is None
            or isinstance(byte_count, bool)
            or not isinstance(byte_count, int)
            or byte_count <= 0
            or isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(float(duration))
            or float(duration) < 0
        ):
            return None, None, None, "not_available", "Provider source-download evidence is invalid."
        if scope_id in seen_scopes:
            return None, None, None, "not_available", "Duplicate Provider source-download scope is ambiguous."
        seen_scopes.add(scope_id)
        measured_sizes.append(byte_count)
        duration_value = round(float(duration), 6)
        total_seconds += duration_value
        rows.append({
            "provider_scope_id": scope_id,
            "download_bytes": byte_count,
            "download_duration_seconds": duration_value,
        })

    if Counter(measured_sizes) != Counter(expected_sizes):
        return None, None, None, "not_available", "Provider consumer-download byte evidence does not match the Atlas transport-scope source-object byte multiset."

    total_bytes = sum(measured_sizes)
    total_seconds = round(total_seconds, 6)
    breakdown = {
        "measurement_scope": PROVIDER_DOWNLOAD_MEASUREMENT_SCOPE,
        "download_total_bytes": total_bytes,
        "download_operation_seconds_sum": total_seconds,
        "downloads": sorted(rows, key=lambda row: str(row["provider_scope_id"])),
    }
    status = "partial" if evidence_incomplete else "observed"
    note = "The bounded event/payload evidence for this snapshot is incomplete." if evidence_incomplete else None
    return total_bytes, total_seconds, breakdown, status, note


__all__ = [
    "PROVIDER_DOWNLOAD_EVENT",
    "PROVIDER_DOWNLOAD_MEASUREMENT_SCOPE",
    "measure_provider_source_download",
    "provider_scope_id",
    "record_provider_source_download_from_result",
]
