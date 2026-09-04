"""Staging-only durable timing for final PDF visual candidate enrichment."""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
import math
import re
from threading import Lock
import time
import uuid

from app import s0_visual_asset_generation_metrics as contract


_ROOT = ContextVar("s0_visual_asset_generation_root", default=None)


def _safe(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except Exception:
        return None


def _revision() -> str | None:
    from app.processing import processing_events

    try:
        value = processing_events._STAGING_REVISION_FILE.read_text(
            encoding="utf-8"
        ).strip()
    except Exception:
        return None
    return value if re.fullmatch(r"[0-9a-f]{40}", value) else None


def _clock_read() -> int:
    return time.perf_counter_ns()


def _clock_resolution_ns() -> int | None:
    resolution = time.get_clock_info("perf_counter").resolution
    if (
        type(resolution) not in (int, float)
        or not math.isfinite(resolution)
        or not 0 < resolution <= 1
    ):
        return None
    value = math.ceil(resolution * 1e9)
    return value if contract.integer(value, 1, 1_000_000_000) else None


def _item_ids(candidate: object, collection: str, identifier: str) -> set[str] | None:
    values = getattr(candidate, collection, None)
    if not isinstance(values, (tuple, list)) or len(values) > contract.MAX_COUNT:
        return None
    result = set()
    for item in values:
        value = getattr(item, identifier, None)
        if not isinstance(value, str) or not value or value in result:
            return None
        result.add(value)
    return result


def _completed_terminal(
    *,
    start: object,
    end: object,
    resolution: object,
    before_assets: set[str] | None,
    before_renditions: set[str] | None,
    result: object,
) -> dict:
    after_assets = _item_ids(result, "assets", "asset_id")
    after_renditions = _item_ids(result, "renditions", "rendition_id")
    if (
        before_assets is None
        or before_renditions is None
        or after_assets is None
        or after_renditions is None
        or not before_assets.issubset(after_assets)
        or not before_renditions.issubset(after_renditions)
    ):
        return {
            "operation_outcome": "invalid",
            "clock_status": "unavailable",
            "duration_ns": None,
            "generated_asset_count": None,
            "generated_rendition_count": None,
            "reason": "invalid_result_counts",
        }
    counts = (len(after_assets - before_assets), len(after_renditions - before_renditions))
    if not all(contract.integer(value, 0, contract.MAX_COUNT) for value in counts):
        return {
            "operation_outcome": "invalid",
            "clock_status": "unavailable",
            "duration_ns": None,
            "generated_asset_count": None,
            "generated_rendition_count": None,
            "reason": "invalid_result_counts",
        }
    clock_status, duration, reason = _clock_terminal(start, end, resolution)
    return {
        "operation_outcome": "completed",
        "clock_status": clock_status,
        "duration_ns": duration,
        "generated_asset_count": counts[0],
        "generated_rendition_count": counts[1],
        "reason": reason,
    }


def _clock_terminal(start: object, end: object, resolution: object):
    if start is None or end is None or resolution is None:
        return "unavailable", None, "clock_unavailable"
    if (
        type(start) is not int
        or start < 0
        or type(end) is not int
        or end < 0
        or end < start
        or not contract.integer(resolution, 1, 1_000_000_000)
        or not contract.integer(end - start)
    ):
        return "unavailable", None, "invalid_clock"
    return "measured", end - start, "none"


@dataclass
class Root:
    run_id: str
    document_id: str
    source_id: str
    revision: str
    observation_id: str = field(default_factory=lambda: "vasset_" + uuid.uuid4().hex)
    lock: object = field(default_factory=Lock)
    calls: int = 0
    terminal: dict | None = None

    def common(self) -> dict:
        return {
            "contract_version": contract.VERSION,
            "measurement_scope": contract.MEASUREMENT_SCOPE,
            "method": contract.METHOD,
            "observation_id": self.observation_id,
            "source_scope_id": contract.source_scope_id(self.source_id),
            "backend_revision": self.revision,
        }

    def begin(self) -> bool:
        with self.lock:
            self.calls += 1
            if self.calls == 1:
                return True
            self.terminal = {
                "operation_outcome": "invalid",
                "clock_status": "unavailable",
                "duration_ns": None,
                "generated_asset_count": None,
                "generated_rendition_count": None,
                "reason": "multiple_visual_enrichment_calls",
            }
            return False

    def settle(self, terminal: dict) -> None:
        with self.lock:
            if self.calls == 1 and self.terminal is None:
                self.terminal = dict(terminal)

    def records(self):
        with self.lock:
            terminal = self.terminal
            if terminal is None:
                terminal = {
                    "operation_outcome": "not_required",
                    "clock_status": "not_started",
                    "duration_ns": None,
                    "generated_asset_count": None,
                    "generated_rendition_count": None,
                    "reason": "no_visual_enrichment_call",
                }
            return [
                (contract.START, {**self.common(), "ordinal": 0}),
                (contract.TERMINAL, {**self.common(), "ordinal": 1, **terminal}),
            ]


def _persist(root: Root, records, *, session_factory=None) -> bool:
    """Persist one exact two-row batch after canonicalization settles."""
    try:
        if _revision() != root.revision or len(records) != 2:
            return False
        if any(
            not isinstance(value, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,255}", value) is None
            for value in (root.run_id, root.document_id, root.source_id)
        ):
            return False

        from sqlalchemy import select

        from app.database import SessionLocal
        from app.models import ProcessingRun, SourceFile, encode_json_text
        from app.processing.processing_event_model import ProcessingEvent
        from app.processing.processing_events import (
            PROCESSING_EVENT_SCHEMA_VERSION,
            sanitize_processing_event_payload,
        )

        rows = []
        for name, payload in records:
            if (
                not contract.valid_payload(name, payload)
                or any(payload[key] != value for key, value in root.common().items())
                or sanitize_processing_event_payload(payload) != payload
            ):
                return False
            encoded = encode_json_text(payload)
            if not isinstance(encoded, str) or len(encoded.encode("utf-8")) > 8192:
                return False
            event_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_OID,
                    f"{contract.VERSION}:{root.observation_id}:{payload['ordinal']}",
                )
            )
            rows.append(
                ProcessingEvent(
                    id=event_id,
                    processing_run_id=root.run_id,
                    document_id=root.document_id,
                    schema_version=PROCESSING_EVENT_SCHEMA_VERSION,
                    event_name=name,
                    severity="info",
                    page_number=None,
                    payload_json=encoded,
                )
            )

        with (session_factory or SessionLocal)() as database:
            with database.begin():
                source_document = database.execute(
                    select(SourceFile.document_id).where(SourceFile.id == root.source_id)
                ).scalar_one_or_none()
                run = database.execute(
                    select(ProcessingRun.document_id, ProcessingRun.source_file_id).where(
                        ProcessingRun.processing_run_id == root.run_id
                    )
                ).one_or_none()
                if source_document != root.document_id or run is None or tuple(run) != (
                    root.document_id,
                    root.source_id,
                ):
                    return False
                database.add_all(rows)
        return True
    except Exception:
        return False


def measure_visual_asset_generation(delegate, candidate, *args, **kwargs):
    root = _ROOT.get()
    if root is None or not root.begin():
        return delegate(candidate, *args, **kwargs)

    before_assets = _item_ids(candidate, "assets", "asset_id")
    before_renditions = _item_ids(candidate, "renditions", "rendition_id")
    resolution = _safe(_clock_resolution_ns)
    start = _safe(_clock_read)
    try:
        result = delegate(candidate, *args, **kwargs)
    except BaseException:
        end = _safe(_clock_read)
        clock_status, duration, reason = _clock_terminal(start, end, resolution)
        root.settle(
            {
                "operation_outcome": "failed",
                "clock_status": clock_status,
                "duration_ns": duration,
                "generated_asset_count": None,
                "generated_rendition_count": None,
                "reason": "delegate_failed" if clock_status == "measured" else reason,
            }
        )
        raise
    end = _safe(_clock_read)
    root.settle(
        _completed_terminal(
            start=start,
            end=end,
            resolution=resolution,
            before_assets=before_assets,
            before_renditions=before_renditions,
            result=result,
        )
    )
    return result


def observe_canonicalization(delegate, instance, envelope):
    revision = _safe(_revision)
    identity = getattr(envelope, "identity", None)
    values = (
        getattr(identity, "atlas_attempt_id", None),
        getattr(identity, "document_id", None),
        getattr(identity, "source_file_id", None),
    )
    if revision is None or not all(isinstance(value, str) and value for value in values):
        return delegate(instance, envelope)

    root = Root(values[0], values[1], values[2], revision)
    token = _ROOT.set(root)
    try:
        return delegate(instance, envelope)
    finally:
        _ROOT.reset(token)
        _safe(_persist, root, root.records())


def install_visual_asset_generation_observability() -> None:
    """Wrap the final composed canonicalization/visual-enrichment chain once."""
    from app.processing import pdf_canonicalization as canonicalization

    original_canonicalize = canonicalization.PdfCanonicalizationService.canonicalize
    original_enrich = canonicalization.enrich_candidate_with_pdf_visual_assets
    flags = [
        getattr(function, "_s0_visual_asset_generation_installed", False)
        for function in (original_canonicalize, original_enrich)
    ]
    if all(flags):
        return
    if any(flags):
        raise RuntimeError("Visual-asset generation runtime partially installed")

    @wraps(original_canonicalize)
    def observed(instance, envelope):
        return observe_canonicalization(original_canonicalize, instance, envelope)

    @wraps(original_enrich)
    def measured(candidate, *args, **kwargs):
        return measure_visual_asset_generation(
            original_enrich,
            candidate,
            *args,
            **kwargs,
        )

    observed._s0_visual_asset_generation_installed = True
    measured._s0_visual_asset_generation_installed = True
    canonicalization.PdfCanonicalizationService.canonicalize = observed
    canonicalization.enrich_candidate_with_pdf_visual_assets = measured


__all__ = [
    "Root",
    "install_visual_asset_generation_observability",
    "measure_visual_asset_generation",
    "observe_canonicalization",
]
