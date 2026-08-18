"""Best-effort diagnostics for crop dark-foreground anchor histogram analysis.

This test-only layer stores the full 256-bin raw and smoothed baseline histogram
plus a fixed-size annotated PNG showing the exact positions selected by the dark
foreground anchor algorithm. The diagnostics are independent storage artifacts,
never Reader renditions, and every generation/persistence failure is fail-open.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import replace
import hashlib
import json
import threading
from typing import Mapping

import cv2
import numpy as np

from app.processing import pdf_opencv_modal_bridge as opencv_bridge

_SCHEMA_VERSION = 1
_SOURCE_STAGE = "baseline_before_opencv_background_cleanup"
_METADATA_KEY = "diagnostic_dark_foreground_anchor_histogram"
_PLOT_STORAGE_KIND = "visual-dark-anchor-histogram"
_DATA_STORAGE_KIND = "visual-dark-anchor-histogram-data"
_MAX_PENDING = 64

_PLOT_WIDTH = 1400
_PLOT_HEIGHT = 760
_PLOT_LEFT = 88
_PLOT_RIGHT = 1360
_PLOT_TOP = 205
_PLOT_BOTTOM = 650

_CURRENT_DIAGNOSTICS: ContextVar[dict[str, dict[str, bytes]] | None] = ContextVar(
    "pdf_crop_dark_foreground_histogram_diagnostics", default=None
)
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False


def _plot_x(gray: int) -> int:
    gray = max(0, min(255, int(gray)))
    return int(round(_PLOT_LEFT + (_PLOT_RIGHT - _PLOT_LEFT) * gray / 255.0))


def _threshold(diagnostics: Mapping[str, object], key: str, default: object) -> object:
    thresholds = diagnostics.get("thresholds")
    if isinstance(thresholds, Mapping):
        return thresholds.get(key, default)
    return default


def _render_plot(
    histogram: np.ndarray,
    smoothed: np.ndarray,
    diagnostics: Mapping[str, object],
) -> bytes:
    canvas = np.full((_PLOT_HEIGHT, _PLOT_WIDTH, 3), 255, dtype=np.uint8)
    font = cv2.FONT_HERSHEY_SIMPLEX

    eligible = diagnostics.get("eligible") is True
    reason = str(diagnostics.get("reason") or "unknown")
    bg_min = int(_threshold(diagnostics, "background_search_min_gray", 128))
    bg_max = int(_threshold(diagnostics, "background_search_max_gray", 247))
    max_valley = float(
        _threshold(diagnostics, "maximum_valley_to_foreground_peak_ratio", 0.80)
    )
    max_hard = float(_threshold(diagnostics, "maximum_hard_anchor_ratio", 0.18))
    max_soft = float(_threshold(diagnostics, "maximum_soft_anchor_ratio", 0.25))

    cv2.putText(
        canvas,
        "Dark Foreground Anchor histogram (baseline before OpenCV background cleanup)",
        (40, 38),
        font,
        0.72,
        (20, 20, 20),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        canvas,
        (
            f"eligible={str(eligible).lower()}  reason={reason}  "
            f"bg={diagnostics.get('background_peak_gray', '-')}  "
            f"fg={diagnostics.get('foreground_peak_gray', '-')}  "
            f"valley={diagnostics.get('valley_gray', '-')}  "
            f"hard={diagnostics.get('hard_threshold_gray', '-')}  "
            f"soft={diagnostics.get('soft_threshold_gray', '-')}"
        ),
        (40, 72),
        font,
        0.56,
        (20, 20, 20),
        1,
        cv2.LINE_AA,
    )
    cv2.putText(
        canvas,
        (
            f"valley/fg={diagnostics.get('valley_to_foreground_peak_ratio', '-')} "
            f"(limit <= {max_valley:.2f})  "
            f"hard_ratio={diagnostics.get('analysis_hard_anchor_ratio', '-')} "
            f"(cap <= {max_hard:.2f})  "
            f"soft_ratio={diagnostics.get('analysis_soft_anchor_ratio', '-')} "
            f"(cap <= {max_soft:.2f})"
        ),
        (40, 102),
        font,
        0.50,
        (45, 45, 45),
        1,
        cv2.LINE_AA,
    )
    cv2.putText(
        canvas,
        "Y scale: log10(count + 1). Raw = light gray; Gaussian-smoothed = black.",
        (40, 132),
        font,
        0.48,
        (75, 75, 75),
        1,
        cv2.LINE_AA,
    )
    cv2.putText(
        canvas,
        f"Gray {bg_max + 1}..255 stays visible but is excluded from BG search [{bg_min},{bg_max}].",
        (40, 158),
        font,
        0.48,
        (75, 75, 75),
        1,
        cv2.LINE_AA,
    )

    cv2.rectangle(
        canvas,
        (_PLOT_LEFT, _PLOT_TOP),
        (_PLOT_RIGHT, _PLOT_BOTTOM),
        (150, 150, 150),
        1,
    )
    for gray in range(0, 256, 32):
        x = _plot_x(gray)
        cv2.line(
            canvas,
            (x, _PLOT_BOTTOM),
            (x, _PLOT_BOTTOM + 6),
            (100, 100, 100),
            1,
        )
        cv2.putText(
            canvas,
            str(gray),
            (x - 10, _PLOT_BOTTOM + 25),
            font,
            0.40,
            (80, 80, 80),
            1,
            cv2.LINE_AA,
        )
    cv2.putText(
        canvas,
        "gray level",
        (_PLOT_RIGHT - 80, _PLOT_BOTTOM + 48),
        font,
        0.46,
        (70, 70, 70),
        1,
        cv2.LINE_AA,
    )

    raw_log = np.log10(np.asarray(histogram, dtype=np.float64) + 1.0)
    smooth_log = np.log10(np.asarray(smoothed, dtype=np.float64) + 1.0)
    max_log = max(1.0, float(np.max(raw_log)), float(np.max(smooth_log)))
    plot_height = _PLOT_BOTTOM - _PLOT_TOP

    def y_for(value: float) -> int:
        bounded = max(0.0, min(max_log, float(value)))
        return int(round(_PLOT_BOTTOM - plot_height * bounded / max_log))

    raw_points = np.array(
        [[_plot_x(gray), y_for(raw_log[gray])] for gray in range(256)],
        dtype=np.int32,
    ).reshape((-1, 1, 2))
    smooth_points = np.array(
        [[_plot_x(gray), y_for(smooth_log[gray])] for gray in range(256)],
        dtype=np.int32,
    ).reshape((-1, 1, 2))
    cv2.polylines(canvas, [raw_points], False, (185, 185, 185), 1, cv2.LINE_AA)
    cv2.polylines(canvas, [smooth_points], False, (20, 20, 20), 2, cv2.LINE_AA)

    bg_start_x = _plot_x(bg_min)
    bg_end_x = _plot_x(bg_max)
    cv2.rectangle(
        canvas,
        (bg_start_x, _PLOT_TOP + 4),
        (bg_end_x, _PLOT_BOTTOM - 4),
        (205, 205, 205),
        1,
    )
    cv2.putText(
        canvas,
        f"BG SEARCH [{bg_min},{bg_max}]",
        (bg_start_x + 4, _PLOT_TOP + 20),
        font,
        0.42,
        (110, 110, 110),
        1,
        cv2.LINE_AA,
    )

    background_peak = diagnostics.get("background_peak_gray")
    foreground_peak = diagnostics.get("foreground_peak_gray")
    hard_threshold = diagnostics.get("hard_threshold_gray")
    valley_gray = diagnostics.get("valley_gray")
    soft_threshold = diagnostics.get("soft_threshold_gray")
    markers: list[tuple[int, str, tuple[int, int, int], int]] = []
    if isinstance(background_peak, int) and not isinstance(background_peak, bool):
        markers.append((background_peak, f"BG {background_peak}", (0, 0, 220), 184))
    if isinstance(foreground_peak, int) and not isinstance(foreground_peak, bool):
        label = (
            f"FG/HARD {foreground_peak}"
            if hard_threshold == foreground_peak
            else f"FG {foreground_peak}"
        )
        markers.append((foreground_peak, label, (220, 70, 0), 208))
    if isinstance(valley_gray, int) and not isinstance(valley_gray, bool):
        markers.append((valley_gray, f"VALLEY {valley_gray}", (0, 145, 255), 232))
    if (
        isinstance(hard_threshold, int)
        and not isinstance(hard_threshold, bool)
        and hard_threshold != foreground_peak
    ):
        markers.append((hard_threshold, f"HARD {hard_threshold}", (180, 0, 180), 256))
    if isinstance(soft_threshold, int) and not isinstance(soft_threshold, bool):
        markers.append((soft_threshold, f"SOFT {soft_threshold}", (0, 150, 0), 280))

    for gray, label, color, label_y in markers:
        x = _plot_x(gray)
        cv2.line(
            canvas,
            (x, _PLOT_TOP),
            (x, _PLOT_BOTTOM),
            color,
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            canvas,
            label,
            (min(x + 4, _PLOT_RIGHT - 150), label_y),
            font,
            0.46,
            color,
            1,
            cv2.LINE_AA,
        )

    ok, encoded = cv2.imencode(".png", canvas)
    if not ok:
        raise RuntimeError("dark foreground histogram diagnostic plot could not be encoded")
    return encoded.tobytes()


def _json_bytes(
    histogram: np.ndarray,
    smoothed: np.ndarray,
    diagnostics: Mapping[str, object],
) -> bytes:
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "policy_version": diagnostics.get("policy_version"),
        "source_stage": _SOURCE_STAGE,
        "analysis_dimensions": list(diagnostics.get("analysis_dimensions") or []),
        "histogram_raw_counts": [int(value) for value in histogram.tolist()],
        "histogram_smoothed_counts": [
            round(float(value), 6) for value in smoothed.tolist()
        ],
        "algorithm_selection": {
            "background_search_range": [
                _threshold(diagnostics, "background_search_min_gray", 128),
                _threshold(diagnostics, "background_search_max_gray", 247),
            ],
            "foreground_search_end_gray": diagnostics.get("foreground_search_end_gray"),
            "background_peak_gray": diagnostics.get("background_peak_gray"),
            "foreground_peak_gray": diagnostics.get("foreground_peak_gray"),
            "valley_gray": diagnostics.get("valley_gray"),
            "hard_threshold_gray": diagnostics.get("hard_threshold_gray"),
            "soft_threshold_gray": diagnostics.get("soft_threshold_gray"),
            "eligible": diagnostics.get("eligible") is True,
            "reason": diagnostics.get("reason"),
            "valley_to_foreground_peak_ratio": diagnostics.get(
                "valley_to_foreground_peak_ratio"
            ),
            "analysis_hard_anchor_ratio": diagnostics.get("analysis_hard_anchor_ratio"),
            "analysis_soft_anchor_ratio": diagnostics.get("analysis_soft_anchor_ratio"),
        },
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def capture_histogram_diagnostic(
    histogram: np.ndarray,
    smoothed: np.ndarray,
    diagnostics: Mapping[str, object],
) -> dict[str, object]:
    """Generate/store bounded diagnostics; never raise into anchor selection."""
    try:
        plot_png = _render_plot(histogram, smoothed, diagnostics)
        data_json = _json_bytes(histogram, smoothed, diagnostics)
        plot_sha = hashlib.sha256(plot_png).hexdigest()
        data_sha = hashlib.sha256(data_json).hexdigest()
        diagnostic_id = f"darkanchorhist:{plot_sha[:16]}:{data_sha[:16]}"
        pending = _CURRENT_DIAGNOSTICS.get()
        status = "not_retained_no_context"
        if pending is not None:
            if len(pending) >= _MAX_PENDING:
                status = "retention_skipped_capacity"
            else:
                base_id = diagnostic_id
                suffix = 1
                while diagnostic_id in pending:
                    suffix += 1
                    diagnostic_id = f"{base_id}:{suffix}"
                pending[diagnostic_id] = {
                    "plot_png": plot_png,
                    "data_json": data_json,
                }
                status = "captured"
        return {
            "status": status,
            "diagnostic_id": diagnostic_id,
            "source_stage": _SOURCE_STAGE,
            "plot_sha256": plot_sha,
            "data_sha256": data_sha,
            "plot_media_type": "image/png",
            "data_media_type": "application/json",
            "plot_y_scale": "log10(count_plus_1)",
            "raw_bin_count": 256,
            "smoothed_bin_count": 256,
        }
    except Exception as exc:
        return {
            "status": "generation_failed",
            "source_stage": _SOURCE_STAGE,
            "error_type": type(exc).__name__,
        }


def _install_context() -> None:
    from app.processing import pdf_canonicalization as canonicalization

    original = canonicalization.PdfCanonicalizationService.canonicalize
    if getattr(original, "_pdf_crop_dark_anchor_histogram_context", False):
        return

    def canonicalize_with_dark_anchor_histograms(self, envelope):
        token = _CURRENT_DIAGNOSTICS.set({})
        try:
            return original(self, envelope)
        finally:
            _CURRENT_DIAGNOSTICS.reset(token)

    canonicalize_with_dark_anchor_histograms._pdf_crop_dark_anchor_histogram_context = True  # type: ignore[attr-defined]
    canonicalization.PdfCanonicalizationService.canonicalize = (
        canonicalize_with_dark_anchor_histograms
    )


def _pending_diagnostic_id(kwargs: Mapping[str, object]) -> str | None:
    selected_png = kwargs.get("png")
    anchor = kwargs.get("anchor")
    source_unit_id = getattr(anchor, "source_unit_id", None)
    if not isinstance(selected_png, bytes) or not isinstance(source_unit_id, str):
        return None
    selected_sha = hashlib.sha256(selected_png).hexdigest()
    for item in opencv_bridge._PENDING_CROPS.get() or []:
        if not isinstance(item, Mapping):
            continue
        if (
            item.get("source_unit_id") != source_unit_id
            or item.get("selected_sha256") != selected_sha
        ):
            continue
        metadata = item.get("metadata")
        background = metadata.get("background") if isinstance(metadata, Mapping) else None
        anchor_metadata = (
            background.get("dark_foreground_anchor_lock")
            if isinstance(background, Mapping)
            else None
        )
        diagnostic = (
            anchor_metadata.get("histogram_diagnostic")
            if isinstance(anchor_metadata, Mapping)
            else None
        )
        if not isinstance(diagnostic, Mapping) or diagnostic.get("status") != "captured":
            return None
        diagnostic_id = diagnostic.get("diagnostic_id")
        if isinstance(diagnostic_id, str) and diagnostic_id.strip():
            return diagnostic_id
    return None


def _reference(kind: str, checksum: str):
    from app.processing import pdf_visual_assets as visual_assets

    storage_kind = _PLOT_STORAGE_KIND if kind == "plot" else _DATA_STORAGE_KIND
    return visual_assets._rendition_reference(storage_kind, checksum)


def _persist_one(
    *,
    kind: str,
    data: bytes,
    storage,
    diagnostic_id: str,
) -> dict[str, object]:
    checksum = hashlib.sha256(data).hexdigest()
    media_type = "image/png" if kind == "plot" else "application/json"
    public: dict[str, object] = {
        "status": "persistence_failed",
        "checksum": checksum,
        "diagnostic_id": f"{diagnostic_id}:{kind}",
        "media_type": media_type,
    }
    try:
        put = storage.put(
            data,
            _reference(kind, checksum),
            expected_size=len(data),
            expected_sha256=checksum,
        )
        if put.checksum_sha256 != checksum:
            raise RuntimeError("dark foreground histogram diagnostic checksum mismatch")
    except Exception as exc:
        public["error_type"] = type(exc).__name__
        return public
    public["status"] = "available"
    return public


def _persist_record(
    *,
    diagnostic_id: str,
    record: Mapping[str, bytes] | None,
    storage,
) -> dict[str, object]:
    if record is None:
        return {
            "status": "capture_missing_at_persistence",
            "diagnostic_id": diagnostic_id,
            "selected_for_reader": False,
            "source_stage": _SOURCE_STAGE,
        }
    try:
        plot_png = record["plot_png"]
        data_json = record["data_json"]
        if not isinstance(plot_png, bytes) or not isinstance(data_json, bytes):
            raise TypeError("dark foreground histogram diagnostic bytes are invalid")
        plot = _persist_one(
            kind="plot",
            data=plot_png,
            storage=storage,
            diagnostic_id=diagnostic_id,
        )
        data = _persist_one(
            kind="data",
            data=data_json,
            storage=storage,
            diagnostic_id=diagnostic_id,
        )
    except Exception as exc:
        return {
            "status": "persistence_failed",
            "diagnostic_id": diagnostic_id,
            "selected_for_reader": False,
            "source_stage": _SOURCE_STAGE,
            "error_type": type(exc).__name__,
        }
    statuses = {plot.get("status"), data.get("status")}
    status = (
        "available"
        if statuses == {"available"}
        else "partial"
        if "available" in statuses
        else "persistence_failed"
    )
    return {
        "status": status,
        "diagnostic_id": diagnostic_id,
        "selected_for_reader": False,
        "source_stage": _SOURCE_STAGE,
        "plot": plot,
        "data": data,
    }


def _attach_to_crop_metadata(
    crop_metadata: Mapping[str, object],
    public: Mapping[str, object],
) -> dict[str, object]:
    updated = dict(crop_metadata)
    background = updated.get("background")
    if not isinstance(background, Mapping):
        return updated
    updated_background = dict(background)
    lock = updated_background.get("dark_foreground_anchor_lock")
    if not isinstance(lock, Mapping):
        return updated
    updated_lock = dict(lock)
    updated_lock["histogram_diagnostic"] = dict(public)
    updated_background["dark_foreground_anchor_lock"] = updated_lock
    updated["background"] = updated_background
    return updated


def _install_persistence() -> None:
    from app.processing import pdf_visual_assets as visual_assets

    original = visual_assets._persist_visual_asset_renditions
    if getattr(original, "_pdf_crop_dark_anchor_histogram_persistence", False):
        return

    def persist_with_dark_anchor_histogram(**kwargs):
        diagnostic_id = None
        pending = _CURRENT_DIAGNOSTICS.get()
        public = None
        try:
            diagnostic_id = _pending_diagnostic_id(kwargs)
            record = (
                pending.get(diagnostic_id)
                if pending is not None and diagnostic_id
                else None
            )
            if diagnostic_id is not None:
                public = _persist_record(
                    diagnostic_id=diagnostic_id,
                    record=record,
                    storage=kwargs.get("storage"),
                )
        except Exception as exc:
            # Diagnostic lookup/persistence must never affect Reader persistence.
            if diagnostic_id is not None:
                public = {
                    "status": "persistence_failed",
                    "diagnostic_id": diagnostic_id,
                    "selected_for_reader": False,
                    "source_stage": _SOURCE_STAGE,
                    "error_type": type(exc).__name__,
                }
        try:
            asset, renditions = original(**kwargs)
        finally:
            try:
                if isinstance(pending, dict) and diagnostic_id is not None:
                    pending.pop(diagnostic_id, None)
            except Exception:
                pass
        if public is None:
            return asset, renditions

        try:
            asset_metadata = dict(asset.metadata or {})
            asset_metadata[_METADATA_KEY] = dict(public)
            crop_metadata = asset_metadata.get("opencv_crop_preprocessing")
            if isinstance(crop_metadata, Mapping):
                asset_metadata["opencv_crop_preprocessing"] = _attach_to_crop_metadata(
                    crop_metadata,
                    public,
                )
            updated_asset = replace(asset, metadata=asset_metadata)

            crop_records = opencv_bridge._CURRENT_CROPS.get()
            node_id = getattr(kwargs.get("node"), "node_id", None)
            if crop_records is not None and isinstance(node_id, str):
                current = crop_records.get(node_id)
                if isinstance(current, Mapping):
                    crop_records[node_id] = _attach_to_crop_metadata(current, public)
        except Exception:
            # Public diagnostic enrichment is optional after Reader persistence.
            return asset, renditions
        return updated_asset, renditions

    persist_with_dark_anchor_histogram._pdf_crop_dark_anchor_histogram_persistence = True  # type: ignore[attr-defined]
    visual_assets._persist_visual_asset_renditions = persist_with_dark_anchor_histogram


def _build_delivery(
    *,
    session,
    document_ref: str,
    candidate_id: str,
    asset_id: str,
    kind: str,
):
    from app.reader_v2 import assets as reader_assets

    candidate, asset = reader_assets._selected_candidate_and_asset(
        session=session,
        document_ref=document_ref,
        candidate_id=candidate_id,
        asset_id=asset_id,
    )
    metadata = asset.metadata if isinstance(asset.metadata, Mapping) else {}
    diagnostic = metadata.get(_METADATA_KEY)
    artifact = diagnostic.get(kind) if isinstance(diagnostic, Mapping) else None
    if not isinstance(artifact, Mapping) or artifact.get("status") != "available":
        raise reader_assets.ReaderV2AssetNotFound(
            f"dark foreground histogram {kind} is not available for asset: {asset_id}"
        )
    checksum = artifact.get("checksum")
    if not isinstance(checksum, str) or len(checksum) != 64:
        raise reader_assets.ReaderV2AssetNotFound(
            f"dark foreground histogram {kind} checksum is invalid for asset: {asset_id}"
        )
    media_type = "image/png" if kind == "plot" else "application/json"
    return reader_assets.ReaderV2AssetDelivery(
        document_ref=candidate.document_ref,
        candidate_id=candidate.candidate_id,
        candidate_schema_id=candidate.schema_id,
        candidate_schema_version=candidate.schema_version,
        asset_id=asset.asset_id,
        role=asset.role.value,
        recovery_state=asset.recovery_state.value,
        source_unit_ids=asset.source_unit_ids,
        source_anchors=asset.source_anchors,
        caption=asset.caption,
        alt_text=asset.alt_text,
        delivery_state="available",
        rendition_id=str(
            artifact.get("diagnostic_id") or f"dark-anchor-histogram:{kind}"
        ),
        rendition_role="diagnostic",
        rendition_media_type=media_type,
        rendition_recovery_state="available",
        storage_ref=str(_reference(kind, checksum)),
    )


def _install_routes() -> None:
    from fastapi import Depends, Query, Response

    from app.database import get_db
    from app.routers import reader_v2 as router_module

    plot_path = (
        "/documents/{document_ref}/assets/{asset_id}/diagnostics/"
        "dark-anchor-histogram/plot"
    )
    data_path = (
        "/documents/{document_ref}/assets/{asset_id}/diagnostics/"
        "dark-anchor-histogram/data"
    )
    full_plot_path = f"{router_module.router.prefix}{plot_path}"
    full_data_path = f"{router_module.router.prefix}{data_path}"
    existing_paths = {
        getattr(route, "path", None) for route in router_module.router.routes
    }

    if full_plot_path not in existing_paths:

        def download_dark_anchor_histogram_plot(
            document_ref: str,
            asset_id: str,
            candidate_id: str = Query(..., min_length=1),
            db=Depends(get_db),
        ) -> Response:
            try:
                delivery = _build_delivery(
                    session=db,
                    document_ref=document_ref,
                    candidate_id=candidate_id,
                    asset_id=asset_id,
                    kind="plot",
                )
            except Exception as exc:
                router_module._map_asset_build_error(exc)
            return router_module._deliver_asset_bytes(
                delivery,
                attachment_filename="dark-anchor-histogram.png",
            )

        router_module.router.add_api_route(
            plot_path,
            download_dark_anchor_histogram_plot,
            methods=["GET"],
            response_class=Response,
            name="download_reader_v2_dark_anchor_histogram_plot",
        )

    if full_data_path not in existing_paths:

        def download_dark_anchor_histogram_data(
            document_ref: str,
            asset_id: str,
            candidate_id: str = Query(..., min_length=1),
            db=Depends(get_db),
        ) -> Response:
            try:
                delivery = _build_delivery(
                    session=db,
                    document_ref=document_ref,
                    candidate_id=candidate_id,
                    asset_id=asset_id,
                    kind="data",
                )
            except Exception as exc:
                router_module._map_asset_build_error(exc)
            return router_module._deliver_asset_bytes(
                delivery,
                attachment_filename="dark-anchor-histogram.json",
            )

        router_module.router.add_api_route(
            data_path,
            download_dark_anchor_histogram_data,
            methods=["GET"],
            response_class=Response,
            name="download_reader_v2_dark_anchor_histogram_data",
        )


def install_pdf_crop_dark_foreground_anchor_histogram_diagnostics_compat() -> None:
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _install_context()
        _install_persistence()
        _install_routes()
        _INSTALLED = True


__all__ = [
    "capture_histogram_diagnostic",
    "install_pdf_crop_dark_foreground_anchor_histogram_diagnostics_compat",
]
