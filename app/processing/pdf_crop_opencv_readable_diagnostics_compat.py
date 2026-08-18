"""Best-effort human-readable crop diagnostics on the test Space storage mount.

The durable Reader-independent diagnostic artifacts remain authoritative. This
layer additionally mirrors each analyzed crop into a browsable test-only folder
under /data/output/opencv-crop-diagnostics/<asset-id>/ so operators can compare
baseline, raw OpenCV, anchor-restored semantic candidate, histogram plot, and
histogram JSON side-by-side in the HF storage browser.

Every capture/write failure is swallowed. This layer never changes Reader
selection, semantic gating, persistence success, or output pixels.
"""
from __future__ import annotations

from contextvars import ContextVar
import hashlib
import json
from pathlib import Path
import re
import threading
from typing import Mapping

from app.processing import pdf_crop_dark_foreground_anchor_diagnostics_compat as histdiag
from app.processing import pdf_crop_opencv_candidate_persistence_compat as candidate_persistence
from app.processing import pdf_opencv_modal_bridge as bridge
from app.processing import pdf_opencv_quality_pipeline as v4

_ROOT = Path("/data/output/opencv-crop-diagnostics")
_CURRENT_RECORDS: ContextVar[list[dict[str, bytes]] | None] = ContextVar(
    "pdf_crop_readable_opencv_diagnostics", default=None
)
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False


def _safe_component(value: object) -> str:
    text = str(value or "unknown")
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._")
    return text[:160] or "unknown"


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def _install_context() -> None:
    from app.processing import pdf_canonicalization as canonicalization

    original = canonicalization.PdfCanonicalizationService.canonicalize
    if getattr(original, "_pdf_crop_readable_diagnostics_context", False):
        return

    def canonicalize_with_readable_diagnostics(self, envelope):
        token = _CURRENT_RECORDS.set([])
        try:
            return original(self, envelope)
        finally:
            _CURRENT_RECORDS.reset(token)

    canonicalize_with_readable_diagnostics._pdf_crop_readable_diagnostics_context = True  # type: ignore[attr-defined]
    canonicalization.PdfCanonicalizationService.canonicalize = canonicalize_with_readable_diagnostics


def _install_capture() -> None:
    original = v4._normalize_background
    if getattr(original, "_pdf_crop_readable_diagnostics_capture", False):
        return

    def normalize_with_readable_capture(image):
        raw_pending = candidate_persistence._CURRENT_CANDIDATES.get()
        before_count = len(raw_pending) if isinstance(raw_pending, list) else 0
        output = original(image)
        records = _CURRENT_RECORDS.get()
        if records is None:
            return output
        try:
            raw_pending_after = candidate_persistence._CURRENT_CANDIDATES.get()
            raw_png = None
            if (
                isinstance(raw_pending_after, list)
                and len(raw_pending_after) > before_count
                and isinstance(raw_pending_after[-1], bytes)
            ):
                raw_png = raw_pending_after[-1]
            if raw_png is None:
                return output
            records.append(
                {
                    "before_png": bridge._encode_png(image),
                    "raw_opencv_png": raw_png,
                    "semantic_candidate_png": bridge._encode_png(output),
                }
            )
        except Exception:
            pass
        return output

    normalize_with_readable_capture._pdf_crop_readable_diagnostics_capture = True  # type: ignore[attr-defined]
    v4._normalize_background = normalize_with_readable_capture


def _histogram_record(kwargs: Mapping[str, object]) -> dict[str, bytes] | None:
    pending = histdiag._CURRENT_DIAGNOSTICS.get()
    if not isinstance(pending, dict):
        return None
    try:
        diagnostic_id = histdiag._pending_diagnostic_id(kwargs)
    except Exception:
        return None
    if not diagnostic_id:
        return None
    record = pending.get(diagnostic_id)
    return record if isinstance(record, dict) else None


def _write_record(
    *,
    asset_id: object,
    node_id: object,
    record: Mapping[str, bytes],
    histogram: Mapping[str, bytes] | None,
) -> None:
    folder = _ROOT / _safe_component(asset_id)
    before = record.get("before_png")
    raw = record.get("raw_opencv_png")
    semantic = record.get("semantic_candidate_png")
    if not all(isinstance(value, bytes) for value in (before, raw, semantic)):
        return

    files: dict[str, bytes] = {
        "crop-before.png": before,
        "crop-opencv-raw.png": raw,
        "crop-anchor-restored.png": semantic,
    }
    if isinstance(histogram, Mapping):
        plot = histogram.get("plot_png")
        data = histogram.get("data_json")
        if isinstance(plot, bytes):
            files["crop-histogram.png"] = plot
        if isinstance(data, bytes):
            files["crop-histogram.json"] = data

    manifest = {
        "schema_version": 1,
        "asset_id": str(asset_id),
        "node_id": str(node_id) if node_id is not None else None,
        "stages": {
            "crop-before.png": "baseline_before_opencv_background_cleanup",
            "crop-opencv-raw.png": "raw_opencv_before_dark_anchor",
            "crop-anchor-restored.png": "semantic_candidate_after_dark_anchor",
            "crop-histogram.png": "annotated_baseline_histogram",
            "crop-histogram.json": "baseline_histogram_data",
        },
        "checksums": {
            name: hashlib.sha256(data).hexdigest()
            for name, data in files.items()
        },
    }
    files["manifest.json"] = json.dumps(
        manifest,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        indent=2,
    ).encode("utf-8")

    for name, data in files.items():
        _atomic_write(folder / name, data)


def _install_persistence() -> None:
    from app.processing import pdf_visual_assets as visual_assets

    original = visual_assets._persist_visual_asset_renditions
    if getattr(original, "_pdf_crop_readable_diagnostics_persistence", False):
        return

    def persist_with_readable_diagnostics(**kwargs):
        records = _CURRENT_RECORDS.get()
        record = records.pop(0) if records else None
        histogram = None
        if record is not None:
            try:
                histogram = _histogram_record(kwargs)
                node = kwargs.get("node")
                _write_record(
                    asset_id=kwargs.get("asset_id"),
                    node_id=getattr(node, "node_id", None),
                    record=record,
                    histogram=histogram,
                )
            except Exception:
                pass
        return original(**kwargs)

    persist_with_readable_diagnostics._pdf_crop_readable_diagnostics_persistence = True  # type: ignore[attr-defined]
    visual_assets._persist_visual_asset_renditions = persist_with_readable_diagnostics


def install_pdf_crop_opencv_readable_diagnostics_compat() -> None:
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        try:
            _install_context()
            _install_capture()
            _install_persistence()
        except Exception:
            # Optional observability must never block runtime installation.
            return
        _INSTALLED = True


__all__ = ["install_pdf_crop_opencv_readable_diagnostics_compat"]
