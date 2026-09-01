"""S0.3.4 complete Provider OCR/batch, raw-shard and sampled GPU evidence.

Producers fail open; collectors never infer missing compute measurements from
Provider wall time, aggregate result size, or source bytes.
"""
from __future__ import annotations

import math
import re

from app.s0_provider_source_download_observability import _enabled, provider_scope_id

BATCH_EVENT = "S0_PROVIDER_OCR_BATCH_MEASURED"
TERMINAL_EVENT = "S0_PROVIDER_OCR_SCOPE_TERMINAL"
DOCUMENT_SCOPE = "provider_ocr_document_v1"
GPU_SCOPE = "nvml_device_utilization_samples_v1"
RAW_SCOPE = "sanitized_raw_page_list_json_utf8_v1"
MAX_BATCHES = 128
_SCOPE_RE = re.compile(r"^provider_[0-9a-f]{16}$")
_GPU_REASONS = {"sampler_unavailable", "sampler_timeout", "nvml_unavailable", "sample_limit", "insufficient_samples"}


def _integer(value, minimum=0, maximum=2**63 - 1):
    return isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum


def _duration(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and 0 <= value <= 86400 and math.isfinite(value)


def _gpu(value):
    # Invalid/missing GPU evidence cannot invalidate independent OCR/raw sizes.
    missing = {"measurement_scope": GPU_SCOPE, "status": "not_available", "reason": "sampler_unavailable"}
    if not isinstance(value, dict) or value.get("measurement_scope") != GPU_SCOPE:
        return missing
    if value.get("status") != "observed":
        reason = value.get("reason")
        return {**missing, "reason": reason if isinstance(reason, str) and reason in _GPU_REASONS else "sampler_unavailable"}
    count, active, total = (value.get(k) for k in ("sample_count", "active_sample_count", "utilization_sum_percent"))
    if (not _integer(count, 2, 4096) or not _integer(active, 0, count)
            or not _integer(total, active, active * 100)
            or isinstance(value.get("sample_interval_seconds"), bool)
            or value.get("sample_interval_seconds") != 1.0):
        return missing
    return {"measurement_scope": GPU_SCOPE, "status": "observed", "sample_count": count,
            "active_sample_count": active, "utilization_sum_percent": total, "sample_interval_seconds": 1.0}


def _contract(value):
    if not isinstance(value, dict) or value.get("measurement_scope") != DOCUMENT_SCOPE or value.get("succeeded") is not True:
        return None
    pages, count, size = (value.get(k) for k in ("page_count", "batch_count", "raw_result_json_bytes"))
    batches = value.get("batches")
    if (not _integer(pages, 1) or not _integer(count, 1, MAX_BATCHES) or not _integer(size, 1)
            or value.get("raw_result_scope") != RAW_SCOPE or not isinstance(batches, list) or len(batches) != count):
        return None
    rows = []
    next_page = 1
    for ordinal, row in enumerate(batches, 1):
        if not isinstance(row, dict):
            return None
        start, end, duration = (row.get(k) for k in ("page_start", "page_end", "predict_seconds"))
        if (not _integer(row.get("ordinal"), 1, count) or row["ordinal"] != ordinal
                or not _integer(start, 1, pages) or start != next_page
                or not _integer(end, start, pages) or not _duration(duration)):
            return None
        rows.append({"ordinal": ordinal, "page_start": start, "page_end": end,
                     "predict_seconds": round(float(duration), 6), "gpu": _gpu(row.get("gpu"))})
        next_page = end + 1
    if next_page != pages + 1:
        return None
    return {"measurement_scope": DOCUMENT_SCOPE, "succeeded": True, "page_count": pages,
            "batch_count": count, "raw_result_scope": RAW_SCOPE, "raw_result_json_bytes": size, "batches": rows}


def record_provider_compute_from_result(request, result):
    """Persist allowlisted batches followed by terminal proof, never partial proof."""
    if not _enabled():
        return False
    try:
        scope = provider_scope_id(request.provider_job_id)
        run_id, doc_id = request.processing_attempt_id, request.document_id
        if scope is None or not run_id or not doc_id:
            return False
        docs = result.raw_provider_payload.get("documents")
        if not isinstance(docs, list):
            return False
        matching = [d for d in docs if isinstance(d, dict) and d.get("document_id") == doc_id]
        if len(matching) != 1 or matching[0].get("status") != "completed":
            return False
        value = _contract(matching[0].get("ocr_compute"))
        if value is None or matching[0].get("pages_completed") != value["page_count"]:
            return False
        from app.processing.processing_events import record_processing_event
        common = {"succeeded": True, "measurement_scope": DOCUMENT_SCOPE, "provider_scope_id": scope}
        for batch in value["batches"]:
            if not record_processing_event(processing_run_id=run_id, document_id=doc_id,
                    event_name=BATCH_EVENT, severity="info", payload={**common, **batch}):
                return False
        return bool(record_processing_event(processing_run_id=run_id, document_id=doc_id,
            event_name=TERMINAL_EVENT, severity="info", payload={**common,
                **{k: value[k] for k in ("page_count", "batch_count", "raw_result_scope", "raw_result_json_bytes")}}))
    except Exception:
        return False


def measure_provider_compute(decoded_events, *, download_breakdown, evidence_incomplete, uninspectable_event_names):
    """Reconcile each closed compute scope with validated consumer download scopes."""
    def missing(note):
        return {"status": "not_available", "note": note, "ocr_seconds": None, "raw_bytes": None,
                "gpu_status": "not_available", "gpu": None, "breakdown": None}

    required_names = {BATCH_EVENT, TERMINAL_EVENT, "PDF_PROVIDER_TRANSPORT_SHARDING_DECISION"}
    if required_names & uninspectable_event_names:
        return missing("At least one required compute/coverage event is malformed or oversized.")
    if not isinstance(download_breakdown, dict) or not isinstance(download_breakdown.get("downloads"), list):
        return missing("Validated Provider download scopes are required to close compute evidence.")
    expected = [d.get("provider_scope_id") for d in download_breakdown["downloads"] if isinstance(d, dict)]
    if not expected or len(expected) != len(set(expected)) or any(not isinstance(s, str) or not _SCOPE_RE.fullmatch(s) for s in expected):
        return missing("Provider download scope evidence is invalid.")
    decisions = [e.payload for e in decoded_events if e.event_name == "PDF_PROVIDER_TRANSPORT_SHARDING_DECISION"]
    if len(decisions) != 1 or not _integer(decisions[0].get("provider_input_page_count"), 1):
        return missing("Exactly one Provider-selected input page count is required for compute coverage.")
    terminals, batches = {}, {}
    for event in decoded_events:
        if event.event_name not in {BATCH_EVENT, TERMINAL_EVENT}:
            continue
        payload = event.payload
        scope = payload.get("provider_scope_id")
        if scope not in expected or payload.get("succeeded") is not True or payload.get("measurement_scope") != DOCUMENT_SCOPE:
            return missing("Compute event scope or measurement contract is invalid.")
        if event.event_name == TERMINAL_EVENT:
            if scope in terminals:
                return missing("Duplicate compute terminal scope is ambiguous.")
            terminals[scope] = payload
        else:
            rows = batches.setdefault(scope, {})
            ordinal = payload.get("ordinal")
            if not _integer(ordinal, 1, MAX_BATCHES) or ordinal in rows:
                return missing("Duplicate or invalid compute batch ordinal.")
            rows[ordinal] = payload
    if set(terminals) != set(expected) or set(batches) != set(expected):
        return missing("Every Provider scope requires batches and exactly one terminal proof.")
    shards = []
    for scope in sorted(expected):
        batch_rows = [batches[scope][i] for i in sorted(batches[scope])]
        value = _contract({**terminals[scope], "batches": batch_rows})
        if value is None:
            return missing("Batch ordinals, page coverage, durations or raw-shard size are incomplete/invalid.")
        shards.append({"provider_scope_id": scope, **{k: value[k] for k in ("page_count", "batch_count", "raw_result_json_bytes", "batches")}})
    if sum(s["page_count"] for s in shards) != decisions[0]["provider_input_page_count"]:
        return missing("Compute page coverage does not equal the Provider-selected input page count.")
    all_batches = [b for s in shards for b in s["batches"]]
    seconds = round(sum(b["predict_seconds"] for b in all_batches), 6)
    size = sum(s["raw_result_json_bytes"] for s in shards)
    status = "partial" if evidence_incomplete else "observed"
    gpu = None
    if all(b["gpu"]["status"] == "observed" for b in all_batches):
        count = sum(b["gpu"]["sample_count"] for b in all_batches)
        active = sum(b["gpu"]["active_sample_count"] for b in all_batches)
        total = sum(b["gpu"]["utilization_sum_percent"] for b in all_batches)
        gpu = {"measurement_scope": GPU_SCOPE, "sample_count": count,
               "mean_utilization_percent": round(total / count, 6),
               "active_sample_fraction": round(active / count, 6), "sample_interval_seconds": 1.0}
    return {"status": status, "note": "Bounded event evidence is incomplete." if evidence_incomplete else None,
            "ocr_seconds": seconds, "raw_bytes": size, "gpu_status": status if gpu is not None else "not_available", "gpu": gpu,
            "breakdown": {"measurement_scope": DOCUMENT_SCOPE, "raw_result_scope": RAW_SCOPE, "shards": shards}}
