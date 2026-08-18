"""Fail-open visual-crop lifecycle diagnostics for deployed PDF crop processing.

The visual-asset runtime intentionally fails open when PDF crop rendering or
rendition persistence fails. That safety behavior can leave a rebuildable asset on
a table/figure node without ``opencv_crop_preprocessing`` metadata, which makes a
real-image test ambiguous: the crop may not have run, persistence may have failed,
or the deployed Space may simply be on an older revision.

This compatibility layer is diagnostics-only. It wraps the already-installed
visual crop hooks, records bounded render/persist lifecycle state in ContextVars,
and annotates final visual nodes after enrichment. It never changes image bytes,
selection policy, provider calls, thresholds, assets, or failure behavior.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import replace
from pathlib import Path
import re
import threading
from typing import Mapping

from app.processing import pdf_opencv_modal_bridge as opencv_bridge
from app.source_units import SpatialAnchor

_INSTALL_LOCK = threading.Lock()
_INSTALLED = False

_CURRENT_RENDER_EVENTS: ContextVar[dict[tuple[object, ...], dict[str, object]] | None] = ContextVar(
    "pdf_visual_crop_render_lifecycle", default=None
)
_CURRENT_PERSIST_EVENTS: ContextVar[dict[str, dict[str, object]] | None] = ContextVar(
    "pdf_visual_crop_persist_lifecycle", default=None
)

_DEPLOYMENTS_ROOT = Path(__file__).resolve().parents[2] / "deployments"
# Production is authoritative on the production branch. The test revision remains
# a bounded fallback so the same diagnostics module can still be exercised in a
# test-style deployment or focused regression environment.
_REVISION_FILE = _DEPLOYMENTS_ROOT / "production-revision.txt"
_FALLBACK_REVISION_FILE = _DEPLOYMENTS_ROOT / "ocrmypdf-test-revision.txt"
_REVISION_RE = re.compile(r"^Application source commit:\s*([0-9a-fA-F]{40})\s*$", re.MULTILINE)
_VISUAL_TYPES = frozenset({"figure", "table"})
_LIFECYCLE_SCHEMA_VERSION = 1


def _deployment_revision() -> str | None:
    """Return the exact recorded GitHub revision for the active deployment."""
    for path in (_REVISION_FILE, _FALLBACK_REVISION_FILE):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        match = _REVISION_RE.search(text)
        if match:
            return match.group(1).lower()
    return None


def _anchor_key(anchor: object) -> tuple[object, ...] | None:
    if not isinstance(anchor, SpatialAnchor):
        return None
    return (
        anchor.source_unit_id,
        round(float(anchor.left), 8),
        round(float(anchor.top), 8),
        round(float(anchor.right), 8),
        round(float(anchor.bottom), 8),
    )


def _node_anchor_key(node: object) -> tuple[object, ...] | None:
    anchors = getattr(node, "source_anchors", ()) or ()
    for anchor in anchors:
        key = _anchor_key(anchor)
        if key is not None:
            return key
    return None


def _node_type_value(node: object) -> str | None:
    value = getattr(getattr(node, "node_type", None), "value", None)
    return value if isinstance(value, str) else None


def _bounded_event(event: Mapping[str, object] | None) -> dict[str, object]:
    if not isinstance(event, Mapping):
        return {"status": "not_observed"}
    allowed = {
        "status",
        "stage",
        "error_type",
        "output_size_bytes",
        "rendition_count",
        "opencv_crop_recorded",
    }
    return {key: event[key] for key in allowed if key in event}


def _asset_summary(candidate: object, node: object) -> tuple[int, int, tuple[str, ...]]:
    node_asset_ids = tuple(getattr(node, "asset_ids", ()) or ())
    assets = tuple(getattr(candidate, "assets", ()) or ())
    matching = [asset for asset in assets if getattr(asset, "asset_id", None) in node_asset_ids]
    rendition_ids = tuple(
        dict.fromkeys(
            rendition_id
            for asset in matching
            for rendition_id in tuple(getattr(asset, "rendition_ids", ()) or ())
        )
    )
    states: list[str] = []
    for asset in matching:
        state = getattr(getattr(asset, "recovery_state", None), "value", None)
        if isinstance(state, str) and state not in states:
            states.append(state)
    return len(matching), len(rendition_ids), tuple(states)


def _lifecycle_status(
    *,
    crop_metadata_attached: bool,
    render_event: Mapping[str, object] | None,
    persist_event: Mapping[str, object] | None,
) -> tuple[str, str]:
    if crop_metadata_attached:
        return "processed", "opencv_crop_metadata_attached"
    if isinstance(persist_event, Mapping) and persist_event.get("status") == "failed":
        return "persist_failed", "visual_asset_persist_failed"
    if isinstance(render_event, Mapping) and render_event.get("status") == "failed":
        return "render_failed", "visual_crop_render_failed"
    if isinstance(persist_event, Mapping) and persist_event.get("status") == "succeeded":
        return "persisted_without_crop_metadata", "opencv_crop_record_missing_after_persistence"
    if isinstance(render_event, Mapping) and render_event.get("status") == "succeeded":
        return "render_succeeded_without_persist", "visual_asset_persistence_not_reached"
    return "not_attempted_or_skipped", "visual_crop_not_observed"


def _attach_lifecycle(candidate: object) -> object:
    render_events = _CURRENT_RENDER_EVENTS.get() or {}
    persist_events = _CURRENT_PERSIST_EVENTS.get() or {}
    revision = _deployment_revision()
    nodes = []

    for node in tuple(getattr(candidate, "nodes", ()) or ()):
        if _node_type_value(node) not in _VISUAL_TYPES:
            nodes.append(node)
            continue

        metadata = dict(getattr(node, "metadata", None) or {})
        crop_metadata_attached = isinstance(metadata.get("opencv_crop_preprocessing"), Mapping)
        render_event = render_events.get(_node_anchor_key(node))
        node_id = getattr(node, "node_id", None)
        persist_event = persist_events.get(node_id) if isinstance(node_id, str) else None
        asset_count, rendition_count, recovery_states = _asset_summary(candidate, node)
        status, reason = _lifecycle_status(
            crop_metadata_attached=crop_metadata_attached,
            render_event=render_event,
            persist_event=persist_event,
        )

        lifecycle: dict[str, object] = {
            "schema_version": _LIFECYCLE_SCHEMA_VERSION,
            "status": status,
            "reason": reason,
            "crop_metadata_attached": crop_metadata_attached,
            "render": _bounded_event(render_event),
            "persist": _bounded_event(persist_event),
            "asset_count": asset_count,
            "rendition_count": rendition_count,
            "asset_recovery_states": list(recovery_states),
            "application_source_commit": revision,
            "deployment_revision_available": revision is not None,
        }
        metadata["visual_crop_lifecycle"] = lifecycle
        nodes.append(replace(node, metadata=metadata))

    return replace(candidate, nodes=tuple(nodes))


def _install_canonicalization_context() -> None:
    from app.processing import pdf_canonicalization as canonicalization

    original = canonicalization.PdfCanonicalizationService.canonicalize
    if getattr(original, "_pdf_visual_crop_lifecycle_context", False):
        return

    def canonicalize_with_visual_crop_lifecycle(self, envelope):
        render_token = _CURRENT_RENDER_EVENTS.set({})
        persist_token = _CURRENT_PERSIST_EVENTS.set({})
        try:
            return original(self, envelope)
        finally:
            _CURRENT_PERSIST_EVENTS.reset(persist_token)
            _CURRENT_RENDER_EVENTS.reset(render_token)

    canonicalize_with_visual_crop_lifecycle._pdf_visual_crop_lifecycle_context = True  # type: ignore[attr-defined]
    canonicalization.PdfCanonicalizationService.canonicalize = canonicalize_with_visual_crop_lifecycle


def _install_render_probe() -> None:
    from app.processing import pdf_visual_assets as visual_assets

    original = visual_assets._render_crop
    if getattr(original, "_pdf_visual_crop_lifecycle_probe", False):
        return

    def render_with_visual_crop_lifecycle(page, anchor):
        events = _CURRENT_RENDER_EVENTS.get()
        key = _anchor_key(anchor)
        if events is not None and key is not None:
            events[key] = {"stage": "render", "status": "attempted"}
        try:
            output = original(page, anchor)
        except Exception as exc:
            if events is not None and key is not None:
                events[key] = {
                    "stage": "render",
                    "status": "failed",
                    "error_type": type(exc).__name__,
                }
            raise
        if events is not None and key is not None:
            event: dict[str, object] = {"stage": "render", "status": "succeeded"}
            if isinstance(output, bytes):
                event["output_size_bytes"] = len(output)
            events[key] = event
        return output

    render_with_visual_crop_lifecycle._pdf_visual_crop_lifecycle_probe = True  # type: ignore[attr-defined]
    visual_assets._render_crop = render_with_visual_crop_lifecycle


def _install_persist_probe() -> None:
    from app.processing import pdf_visual_assets as visual_assets

    original = visual_assets._persist_visual_asset_renditions
    if getattr(original, "_pdf_visual_crop_lifecycle_probe", False):
        return

    def persist_with_visual_crop_lifecycle(**kwargs):
        node = kwargs.get("node")
        node_id = getattr(node, "node_id", None)
        events = _CURRENT_PERSIST_EVENTS.get()
        if events is not None and isinstance(node_id, str):
            events[node_id] = {"stage": "persist", "status": "attempted"}
        try:
            result = original(**kwargs)
        except Exception as exc:
            if events is not None and isinstance(node_id, str):
                events[node_id] = {
                    "stage": "persist",
                    "status": "failed",
                    "error_type": type(exc).__name__,
                }
            raise

        if events is not None and isinstance(node_id, str):
            crop_records = opencv_bridge._CURRENT_CROPS.get() or {}
            rendition_count = 0
            if isinstance(result, tuple) and len(result) >= 2:
                try:
                    rendition_count = len(result[1])
                except Exception:
                    rendition_count = 0
            events[node_id] = {
                "stage": "persist",
                "status": "succeeded",
                "rendition_count": rendition_count,
                "opencv_crop_recorded": node_id in crop_records,
            }
        return result

    persist_with_visual_crop_lifecycle._pdf_visual_crop_lifecycle_probe = True  # type: ignore[attr-defined]
    visual_assets._persist_visual_asset_renditions = persist_with_visual_crop_lifecycle


def _install_enrichment_annotation() -> None:
    from app.processing import pdf_canonicalization as canonicalization

    original = canonicalization.enrich_candidate_with_pdf_visual_assets
    if getattr(original, "_pdf_visual_crop_lifecycle_annotation", False):
        return

    def enrich_with_visual_crop_lifecycle(*args, **kwargs):
        enriched = original(*args, **kwargs)
        try:
            return _attach_lifecycle(enriched)
        except Exception:
            # Diagnostics must never make canonicalization fail.
            return enriched

    enrich_with_visual_crop_lifecycle._pdf_visual_crop_lifecycle_annotation = True  # type: ignore[attr-defined]
    canonicalization.enrich_candidate_with_pdf_visual_assets = enrich_with_visual_crop_lifecycle


def install_pdf_visual_crop_lifecycle_compat() -> None:
    """Install bounded diagnostics after the V4/Semantic crop wrappers."""
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _install_canonicalization_context()
        _install_render_probe()
        _install_persist_probe()
        _install_enrichment_annotation()
        _INSTALLED = True


__all__ = ["install_pdf_visual_crop_lifecycle_compat"]
