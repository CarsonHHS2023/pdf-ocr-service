"""Fail-open structured observability helpers for S0 Phase 0 profiling."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from time import perf_counter
from typing import Mapping


PROFILE_SCHEMA_VERSION = "atlas.s0.profile.v1"
_logger = logging.getLogger("uvicorn.error")


def now() -> float:
    return perf_counter()


def elapsed_ms(started_at: float) -> float:
    return round(max(0.0, (perf_counter() - float(started_at)) * 1000.0), 3)


def resource_snapshot() -> dict[str, float | None]:
    """Read current and high-water process RSS without adding dependencies."""
    rss_kib: int | None = None
    peak_kib: int | None = None
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                rss_kib = int(line.split(":", 1)[1].strip().split()[0])
            elif line.startswith("VmHWM:"):
                peak_kib = int(line.split(":", 1)[1].strip().split()[0])
    except Exception:
        pass
    return {
        "rss_mb": round(rss_kib / 1024.0, 1) if rss_kib is not None else None,
        "peak_rss_mb": round(peak_kib / 1024.0, 1) if peak_kib is not None else None,
    }


def active_identity() -> dict[str, object]:
    """Return active S0 run identity when the heartbeat context is installed."""
    try:
        from app.processing import s0_pdf_resource_heartbeat as heartbeat

        state = heartbeat._active_state()
        if not isinstance(state, dict):
            return {}
        lock = state.get("lock")
        if hasattr(lock, "__enter__"):
            with lock:
                return {
                    "processing_run_id": state.get("processing_run_id"),
                    "document_id": state.get("document_id"),
                    "page_number": state.get("current_page_number"),
                    "page_count": state.get("page_count"),
                    "work_phase": state.get("work_phase"),
                    "current_stage": state.get("current_stage"),
                }
        return {
            "processing_run_id": state.get("processing_run_id"),
            "document_id": state.get("document_id"),
            "page_number": state.get("current_page_number"),
            "page_count": state.get("page_count"),
            "work_phase": state.get("work_phase"),
            "current_stage": state.get("current_stage"),
        }
    except Exception:
        return {}


def emit_profile(event: str, **fields: object) -> None:
    """Emit one bounded JSON profile line; never affect processing on failure."""
    try:
        payload = {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "event": str(event)[:96],
            **active_identity(),
            **resource_snapshot(),
            **fields,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        )
        _logger.info("PDF_S0_PROFILE %s", encoded)
    except Exception:
        _logger.exception("S0 profile emission failed open")


def merge_stage_ms(
    target: dict[str, float],
    source: Mapping[str, object],
) -> None:
    for key, value in source.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            target[str(key)] = round(target.get(str(key), 0.0) + float(value), 3)


__all__ = [
    "PROFILE_SCHEMA_VERSION",
    "active_identity",
    "elapsed_ms",
    "emit_profile",
    "merge_stage_ms",
    "now",
    "resource_snapshot",
]
