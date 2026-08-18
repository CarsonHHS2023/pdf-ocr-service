"""S0-only durable PDF resource observability.

This module records bounded resource checkpoints for long-running PDF ingestion
without changing processing policy, OCR quality, provider batching, or queue
semantics. ProcessingRun remains provenance/observability state, not queue truth.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import shutil
import sys
import threading
from typing import Any, Iterator

from app.database import SessionLocal
from app.models import (
    Document,
    ProcessingRun,
    decode_json_text,
    encode_json_text,
)

logger = logging.getLogger("uvicorn.error")

PAGE_HEARTBEAT_INTERVAL = 10
LIVENESS_HEARTBEAT_SECONDS = 60.0
MAX_DURABLE_CHECKPOINTS = 256
_CONTEXT = threading.local()
_PROBE_INSTALL_LOCK = threading.Lock()
_PERSIST_LOCK = threading.Lock()
_PROBE_INSTALLED = False


def _utcnow_naive() -> datetime:
    return datetime.utcnow()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_proc_status_kib() -> tuple[int | None, int | None]:
    """Return current RSS and process high-water RSS from Linux /proc."""
    try:
        values: dict[str, int] = {}
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith(("VmRSS:", "VmHWM:")):
                name, raw = line.split(":", 1)
                values[name] = int(raw.strip().split()[0])
        return values.get("VmRSS"), values.get("VmHWM")
    except Exception:
        return None, None


def resource_snapshot() -> dict[str, int | float | None]:
    """Return bounded process/disk resource metrics safe for diagnostics."""
    rss_kib, peak_kib = _read_proc_status_kib()
    disk_path = Path("/data") if Path("/data").exists() else Path("/")
    try:
        disk = shutil.disk_usage(disk_path)
        disk_free_mb: float | None = round(disk.free / (1024 * 1024), 1)
    except Exception:
        disk_free_mb = None
    return {
        "pid": os.getpid(),
        "rss_mb": round(rss_kib / 1024, 1) if rss_kib is not None else None,
        "peak_rss_mb": round(peak_kib / 1024, 1) if peak_kib is not None else None,
        "disk_free_mb": disk_free_mb,
    }


def _decode_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        decoded = decode_json_text(value)
    except Exception:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _bounded_extra(extra: dict[str, object]) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, value in extra.items():
        if not isinstance(key, str) or len(key) > 64:
            continue
        if value is None or isinstance(value, (bool, int, float)):
            safe[key] = value
        elif isinstance(value, str) and len(value) <= 128:
            safe[key] = value
    return safe


def start_pdf_processing_run(
    *,
    processing_run_id: str,
    document_id: str,
    source_file_id: str,
) -> None:
    """Create or resume the durable observability row for one PDF attempt."""
    db = SessionLocal()
    try:
        run = (
            db.query(ProcessingRun)
            .filter(ProcessingRun.processing_run_id == processing_run_id)
            .one_or_none()
        )
        if run is None:
            run = ProcessingRun(
                processing_run_id=processing_run_id,
                document_id=document_id,
                source_file_id=source_file_id,
                status="running",
                provider_ref="paddle-vl",
                processing_policy_ref="pdf-ingestion-s0-observability",
                started_at=_utcnow_naive(),
                extensions_json=encode_json_text(
                    {
                        "s0_resource_heartbeat": {
                            "version": "atlas-s0-pdf-resource-v2",
                            "latest": None,
                            "checkpoints": [],
                        }
                    }
                ),
            )
            db.add(run)
        elif run.status in {"created", "running"}:
            run.status = "running"
            if run.started_at is None:
                run.started_at = _utcnow_naive()
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "Could not initialize S0 PDF ProcessingRun processing_run_id=%s document_id=%s",
            processing_run_id,
            document_id,
        )
    finally:
        db.close()


def record_pdf_processing_heartbeat(
    *,
    processing_run_id: str,
    document_id: str,
    phase: str,
    page_number: int | None = None,
    page_count: int | None = None,
    **extra: object,
) -> dict[str, int | float | None]:
    """Persist one bounded resource checkpoint and also emit it to stderr."""
    snapshot = resource_snapshot()
    safe_extra = _bounded_extra(extra)
    checkpoint: dict[str, object] = {
        "at": _utcnow_iso(),
        "phase": phase,
        "page_number": page_number,
        "page_count": page_count,
        **snapshot,
        **safe_extra,
    }

    message = " ".join(
        f"{key}={value}"
        for key, value in {
            "processing_run_id": processing_run_id,
            "document_id": document_id,
            "phase": phase,
            "page_number": page_number,
            "page_count": page_count,
            **snapshot,
            **safe_extra,
        }.items()
    )
    logger.info("PDF_S0_RESOURCE_HEARTBEAT %s", message)
    print(f"PDF_S0_RESOURCE_HEARTBEAT {message}", file=sys.stderr, flush=True)

    with _PERSIST_LOCK:
        db = SessionLocal()
        try:
            run = (
                db.query(ProcessingRun)
                .filter(ProcessingRun.processing_run_id == processing_run_id)
                .one_or_none()
            )
            if run is None:
                return snapshot

            extensions = _decode_object(run.extensions_json)
            heartbeat = extensions.get("s0_resource_heartbeat")
            if not isinstance(heartbeat, dict):
                heartbeat = {}
            checkpoints = heartbeat.get("checkpoints")
            if not isinstance(checkpoints, list):
                checkpoints = []
            checkpoints.append(checkpoint)
            heartbeat.update(
                {
                    "version": "atlas-s0-pdf-resource-v2",
                    "latest": checkpoint,
                    "checkpoints": checkpoints[-MAX_DURABLE_CHECKPOINTS:],
                }
            )
            extensions["s0_resource_heartbeat"] = heartbeat

            metrics = _decode_object(run.metrics_json)
            resource_metrics = metrics.get("s0_resource")
            if not isinstance(resource_metrics, dict):
                resource_metrics = {}
            rss = snapshot.get("rss_mb")
            disk_free = snapshot.get("disk_free_mb")
            previous_max = resource_metrics.get("max_observed_rss_mb")
            previous_min_disk = resource_metrics.get("min_observed_disk_free_mb")
            resource_metrics.update(
                {
                    "latest_rss_mb": rss,
                    "latest_peak_rss_mb": snapshot.get("peak_rss_mb"),
                    "latest_disk_free_mb": disk_free,
                    "last_phase": phase,
                    "last_page_number": page_number,
                    "last_page_count": page_count,
                    "last_heartbeat_at": checkpoint["at"],
                }
            )
            if "current_stage" in safe_extra:
                resource_metrics["last_opencv_stage"] = safe_extra["current_stage"]
            if "last_completed_page" in safe_extra:
                resource_metrics["last_completed_page"] = safe_extra["last_completed_page"]
            if isinstance(rss, (int, float)):
                resource_metrics["max_observed_rss_mb"] = max(
                    float(previous_max)
                    if isinstance(previous_max, (int, float))
                    else float(rss),
                    float(rss),
                )
            if isinstance(disk_free, (int, float)):
                resource_metrics["min_observed_disk_free_mb"] = min(
                    float(previous_min_disk)
                    if isinstance(previous_min_disk, (int, float))
                    else float(disk_free),
                    float(disk_free),
                )
            metrics["s0_resource"] = resource_metrics

            if run.status == "created":
                run.status = "running"
            if run.started_at is None:
                run.started_at = _utcnow_naive()
            run.extensions_json = encode_json_text(extensions)
            run.metrics_json = encode_json_text(metrics)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception(
                "Could not persist S0 PDF resource heartbeat processing_run_id=%s phase=%s",
                processing_run_id,
                phase,
            )
        finally:
            db.close()
    return snapshot


def sync_pdf_processing_run_terminal(
    *,
    processing_run_id: str,
    document_id: str,
) -> None:
    """Mirror a normal Document terminal state into ProcessingRun provenance."""
    db = SessionLocal()
    try:
        run = (
            db.query(ProcessingRun)
            .filter(ProcessingRun.processing_run_id == processing_run_id)
            .one_or_none()
        )
        document = db.get(Document, document_id)
        if run is None or document is None:
            return
        now = _utcnow_naive()
        if document.status == "completed":
            run.status = "succeeded"
            run.completed_at = run.completed_at or now
        elif document.status == "failed":
            run.status = "failed"
            run.failed_at = run.failed_at or now
            if document.error_message:
                run.safe_error_summary = document.error_message
        else:
            return
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "Could not synchronize S0 PDF ProcessingRun terminal state processing_run_id=%s",
            processing_run_id,
        )
    finally:
        db.close()


def _should_record_page(page_number: int, page_count: int) -> bool:
    return bool(
        page_number == 1
        or page_number == page_count
        or page_number % PAGE_HEARTBEAT_INTERVAL == 0
    )


def _new_observation_state(
    *,
    processing_run_id: str,
    document_id: str,
    page_count: int,
) -> dict[str, object]:
    return {
        "processing_run_id": processing_run_id,
        "document_id": document_id,
        "page_count": int(page_count),
        "current_page_number": None,
        "current_stage": "opencv_context_started",
        "last_completed_page": 0,
        "stage_updated_at": _utcnow_iso(),
        "lock": threading.Lock(),
        "stop_event": threading.Event(),
    }


def _state_snapshot(state: dict[str, object]) -> dict[str, object]:
    lock = state.get("lock")
    if not hasattr(lock, "__enter__"):
        return {
            "current_page_number": state.get("current_page_number"),
            "current_stage": state.get("current_stage"),
            "last_completed_page": state.get("last_completed_page"),
            "stage_updated_at": state.get("stage_updated_at"),
        }
    with lock:
        return {
            "current_page_number": state.get("current_page_number"),
            "current_stage": state.get("current_stage"),
            "last_completed_page": state.get("last_completed_page"),
            "stage_updated_at": state.get("stage_updated_at"),
        }


def _active_state() -> dict[str, object] | None:
    state = getattr(_CONTEXT, "value", None)
    return state if isinstance(state, dict) else None


def _set_opencv_stage(
    stage: str,
    *,
    page_number: int | None = None,
    durable_first_page: bool = True,
) -> None:
    """Update current OpenCV stage and persist detailed transitions for page 1."""
    state = _active_state()
    if state is None:
        return
    lock = state.get("lock")
    if not hasattr(lock, "__enter__"):
        return
    with lock:
        if page_number is not None and page_number > 0:
            state["current_page_number"] = int(page_number)
        state["current_stage"] = stage[:128]
        state["stage_updated_at"] = _utcnow_iso()
        current_page = state.get("current_page_number")
        last_completed = state.get("last_completed_page")
        page_count = int(state["page_count"])
        processing_run_id = str(state["processing_run_id"])
        document_id = str(state["document_id"])
    if durable_first_page and current_page == 1:
        record_pdf_processing_heartbeat(
            processing_run_id=processing_run_id,
            document_id=document_id,
            phase="opencv_stage",
            page_number=1,
            page_count=page_count,
            current_stage=stage[:128],
            last_completed_page=last_completed if isinstance(last_completed, int) else 0,
        )


def _record_liveness_heartbeat(state: dict[str, object]) -> None:
    snapshot = _state_snapshot(state)
    current_page = snapshot.get("current_page_number")
    last_completed = snapshot.get("last_completed_page")
    record_pdf_processing_heartbeat(
        processing_run_id=str(state["processing_run_id"]),
        document_id=str(state["document_id"]),
        phase="opencv_liveness",
        page_number=int(current_page) if isinstance(current_page, int) else None,
        page_count=int(state["page_count"]),
        current_stage=str(snapshot.get("current_stage") or "unknown")[:128],
        last_completed_page=int(last_completed) if isinstance(last_completed, int) else 0,
        stage_updated_at=str(snapshot.get("stage_updated_at") or "")[:128],
    )


def _liveness_worker(state: dict[str, object]) -> None:
    stop_event = state.get("stop_event")
    if not hasattr(stop_event, "wait"):
        return
    interval = max(1.0, float(LIVENESS_HEARTBEAT_SECONDS))
    while not stop_event.wait(interval):
        try:
            _record_liveness_heartbeat(state)
        except Exception:
            logger.exception("S0 OpenCV liveness heartbeat failed open")


def _handle_page_decision(decision: dict[str, object]) -> None:
    state = _active_state()
    if state is None:
        return
    try:
        page_number = int(decision.get("page_number") or 0)
        page_count = int(state["page_count"])
        if page_number <= 0:
            return
        lock = state.get("lock")
        if not hasattr(lock, "__enter__"):
            return
        with lock:
            state["current_page_number"] = page_number
            state["current_stage"] = "page_completed"
            state["last_completed_page"] = page_number
            state["stage_updated_at"] = _utcnow_iso()
        if not _should_record_page(page_number, page_count):
            return
        record_pdf_processing_heartbeat(
            processing_run_id=str(state["processing_run_id"]),
            document_id=str(state["document_id"]),
            phase="opencv_page_completed",
            page_number=page_number,
            page_count=page_count,
            route=str(decision.get("route") or "unknown")[:128],
            current_stage="page_completed",
            last_completed_page=page_number,
        )
    except Exception:
        logger.exception("S0 OpenCV page completion probe failed open")


@contextmanager
def pdf_resource_observation_context(
    *,
    processing_run_id: str,
    document_id: str,
    page_count: int,
) -> Iterator[None]:
    """Associate OpenCV processing with durable progress and liveness probes."""
    previous = getattr(_CONTEXT, "value", None)
    state = _new_observation_state(
        processing_run_id=processing_run_id,
        document_id=document_id,
        page_count=page_count,
    )
    _CONTEXT.value = state
    thread = threading.Thread(
        target=_liveness_worker,
        args=(state,),
        name=f"s0-pdf-liveness-{processing_run_id[-12:]}",
        daemon=True,
    )
    thread.start()
    try:
        yield
    finally:
        stop_event = state.get("stop_event")
        if hasattr(stop_event, "set"):
            stop_event.set()
        thread.join(timeout=2.0)
        _CONTEXT.value = previous


def _page_number_from_page(page: object) -> int | None:
    raw = getattr(page, "number", None)
    if isinstance(raw, int) and raw >= 0:
        return raw + 1
    return None


def _install_stage_wrapper(
    pipeline: object,
    name: str,
    *,
    before_stage: str,
    after_stage: str,
    page_from_first_arg: bool = False,
    render_stage_by_dpi: bool = False,
) -> None:
    original = getattr(pipeline, name)
    if getattr(original, "__atlas_s0_deep_probe__", False):
        return

    def wrapped(*args: object, **kwargs: object):
        page_number = None
        if page_from_first_arg and args:
            page_number = _page_number_from_page(args[0])
        if render_stage_by_dpi:
            dpi = kwargs.get("dpi")
            if dpi is None and len(args) > 1:
                dpi = args[1]
            if dpi == 120:
                before = "analysis_render_120dpi_start"
                after = "analysis_render_120dpi_complete"
            elif dpi == 300:
                before = "source_render_300dpi_start"
                after = "source_render_300dpi_complete"
            elif dpi == 150:
                before = "diagnostic_render_150dpi_start"
                after = "diagnostic_render_150dpi_complete"
            else:
                before = f"render_{dpi}_start"[:128]
                after = f"render_{dpi}_complete"[:128]
        else:
            before = before_stage
            after = after_stage
        _set_opencv_stage(before, page_number=page_number)
        result = original(*args, **kwargs)
        _set_opencv_stage(after, page_number=page_number)
        return result

    setattr(wrapped, "__atlas_s0_deep_probe__", True)
    setattr(pipeline, name, wrapped)


def install_opencv_page_heartbeat_probe() -> None:
    """Install page completion, deep-stage, and independent liveness probes."""
    global _PROBE_INSTALLED
    with _PROBE_INSTALL_LOCK:
        if _PROBE_INSTALLED:
            return
        from app.processing import pdf_opencv_quality_pipeline as pipeline

        _install_stage_wrapper(
            pipeline,
            "_inspect_page_structure",
            before_stage="inspect_structure_start",
            after_stage="inspect_structure_complete",
            page_from_first_arg=True,
        )
        _install_stage_wrapper(
            pipeline,
            "_render_page_bgr",
            before_stage="render_start",
            after_stage="render_complete",
            page_from_first_arg=True,
            render_stage_by_dpi=True,
        )
        _install_stage_wrapper(
            pipeline,
            "_color_features",
            before_stage="color_analysis_start",
            after_stage="color_analysis_complete",
        )
        _install_stage_wrapper(
            pipeline,
            "_build_geometry_candidate",
            before_stage="geometry_candidate_start",
            after_stage="geometry_candidate_complete",
        )
        _install_stage_wrapper(
            pipeline,
            "_gate_geometry_candidate",
            before_stage="geometry_gate_start",
            after_stage="geometry_gate_complete",
        )
        _install_stage_wrapper(
            pipeline,
            "_normalize_background",
            before_stage="background_normalization_start",
            after_stage="background_normalization_complete",
        )
        _install_stage_wrapper(
            pipeline,
            "_gate_background_candidate",
            before_stage="background_gate_start",
            after_stage="background_gate_complete",
        )
        _install_stage_wrapper(
            pipeline,
            "_insert_raster_page",
            before_stage="output_insert_start",
            after_stage="output_insert_complete",
        )

        original_log = pipeline._log_page_decision
        if not getattr(original_log, "__atlas_s0_deep_probe__", False):
            def wrapped_log(decision: dict[str, object]) -> None:
                original_log(decision)
                _handle_page_decision(decision)

            setattr(wrapped_log, "__atlas_s0_deep_probe__", True)
            pipeline._log_page_decision = wrapped_log

        _PROBE_INSTALLED = True


__all__ = [
    "LIVENESS_HEARTBEAT_SECONDS",
    "MAX_DURABLE_CHECKPOINTS",
    "PAGE_HEARTBEAT_INTERVAL",
    "install_opencv_page_heartbeat_probe",
    "pdf_resource_observation_context",
    "record_pdf_processing_heartbeat",
    "resource_snapshot",
    "start_pdf_processing_run",
    "sync_pdf_processing_run_terminal",
]
