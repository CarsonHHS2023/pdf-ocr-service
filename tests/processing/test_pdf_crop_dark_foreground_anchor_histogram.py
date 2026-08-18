from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app.processing import pdf_crop_dark_foreground_anchor_compat as anchor
from app.processing import pdf_crop_dark_foreground_anchor_diagnostics_compat as diagnostics
from app.processing import pdf_crop_dark_foreground_anchor_peak_diagnostics_compat as peak_diagnostics
from app.processing import pdf_opencv_modal_bridge as bridge


def _gray_table_with_large_white_margin() -> np.ndarray:
    # Reproduce the important histogram shape of a gray scanned table crop that
    # also contains substantial saturated-white caption/margin pixels. The white
    # mode may be taller than the gray-paper mode but must not become bg_peak.
    height, width = 500, 900
    image = np.full((height, width, 3), 255, dtype=np.uint8)
    table_top = 210
    image[table_top:, :] = 240

    # Two meaningful dark modes. V2 deliberately chooses the darkest qualified
    # local peak (~153), not the taller/lightest foreground mode (~169).
    for y in (235, 290, 345, 400, 455):
        cv2.line(image, (25, y), (875, y), (169, 169, 169), 2, cv2.LINE_8)
    for row in range(4):
        for col in range(8):
            x0 = 70 + col * 100
            y0 = 255 + row * 55
            cv2.rectangle(image, (x0, y0), (x0 + 30, y0 + 7), (169, 169, 169), -1)
            cv2.rectangle(image, (x0 + 35, y0), (x0 + 44, y0 + 7), (153, 153, 153), -1)
    return image


def test_saturated_white_margin_does_not_hide_gray_paper_foreground_peak() -> None:
    image = _gray_table_with_large_white_margin()
    result = anchor._histogram_anchor_thresholds(image)
    assert result["eligible"] is True
    assert result["background_peak_gray"] == 240
    assert 150 <= result["foreground_peak_gray"] <= 156
    assert result["hard_threshold_gray"] == result["foreground_peak_gray"]
    assert result["soft_threshold_gray"] <= result["foreground_peak_gray"] + 12
    assert result["hard_anchor_ratio"] < 0.10
    assert result["soft_anchor_ratio"] < 0.12
    assert result["thresholds"]["background_search_max_gray"] == 247
    assert result["histogram_source_stage"] == "baseline_before_opencv_background_cleanup"
    assert result["foreground_selection"] == "darkest_qualified_local_peak"
    assert result["valley_gate_role"] == "diagnostic_only"
    assert result["selected_foreground_peak_support_ratio"] >= anchor._MIN_LOCAL_PEAK_SUPPORT_RATIO
    assert result["selected_foreground_peak_prominence_ratio"] >= anchor._MIN_LOCAL_PEAK_PROMINENCE_RATIO
    assert isinstance(result["valley_gray"], int)


def test_saturated_white_is_never_selected_as_anchor_background_peak() -> None:
    image = _gray_table_with_large_white_margin()
    result = anchor._histogram_anchor_thresholds(image)
    assert result["background_peak_gray"] <= anchor._BACKGROUND_SEARCH_MAX_GRAY
    assert result["background_peak_gray"] != 255


def test_histogram_diagnostic_keeps_full_bins_and_marks_algorithm_choices(monkeypatch) -> None:
    image = _gray_table_with_large_white_margin()
    peak_diagnostics._INSTALLED = False
    peak_diagnostics.install_pdf_crop_dark_foreground_anchor_peak_diagnostics_compat()
    seen_labels: list[str] = []
    real_put_text = diagnostics.cv2.putText

    def recording_put_text(*args, **kwargs):
        if len(args) > 1 and isinstance(args[1], str):
            seen_labels.append(args[1])
        return real_put_text(*args, **kwargs)

    monkeypatch.setattr(diagnostics.cv2, "putText", recording_put_text)
    pending: dict[str, dict[str, bytes]] = {}
    token = diagnostics._CURRENT_DIAGNOSTICS.set(pending)
    try:
        result = anchor._histogram_anchor_thresholds(image)
    finally:
        diagnostics._CURRENT_DIAGNOSTICS.reset(token)

    public = result["histogram_diagnostic"]
    assert public["status"] == "captured"
    assert public["raw_bin_count"] == 256
    assert public["smoothed_bin_count"] == 256
    diagnostic_id = public["diagnostic_id"]
    assert diagnostic_id in pending

    record = pending[diagnostic_id]
    assert record["plot_png"].startswith(b"\x89PNG\r\n\x1a\n")
    decoded = cv2.imdecode(np.frombuffer(record["plot_png"], dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None
    assert decoded.shape[:2] == (diagnostics._PLOT_HEIGHT, diagnostics._PLOT_WIDTH)

    payload = json.loads(record["data_json"].decode("utf-8"))
    assert payload["source_stage"] == "baseline_before_opencv_background_cleanup"
    assert len(payload["histogram_raw_counts"]) == 256
    assert len(payload["histogram_smoothed_counts"]) == 256
    assert sum(payload["histogram_raw_counts"]) == image.shape[0] * image.shape[1]
    selection = payload["algorithm_selection"]
    assert selection["background_peak_gray"] == result["background_peak_gray"]
    assert selection["foreground_peak_gray"] == result["foreground_peak_gray"]
    assert selection["valley_gray"] == result["valley_gray"]
    assert selection["hard_threshold_gray"] == result["hard_threshold_gray"]
    assert selection["soft_threshold_gray"] == result["soft_threshold_gray"]
    assert selection["eligible"] is result["eligible"]
    assert selection["reason"] == result["reason"]
    assert selection["foreground_selection"] == "darkest_qualified_local_peak"
    assert selection["valley_gate_role"] == "diagnostic_only"
    assert selection["foreground_peak_candidates"] == result["foreground_peak_candidates"]
    assert selection["selected_foreground_peak_support_ratio"] == result[
        "selected_foreground_peak_support_ratio"
    ]
    assert selection["selected_foreground_peak_prominence_ratio"] == result[
        "selected_foreground_peak_prominence_ratio"
    ]

    assert any(label.startswith("BG 240") for label in seen_labels)
    assert any(label.startswith("FG/HARD ") for label in seen_labels)
    assert any(label.startswith("VALLEY ") for label in seen_labels)
    assert any(label.startswith("SOFT ") for label in seen_labels)
    assert any("eligible=true" in label for label in seen_labels)
    assert any(label.startswith("LOCAL PEAKS") for label in seen_labels)


def test_histogram_diagnostic_generation_failure_does_not_change_selection(monkeypatch) -> None:
    image = _gray_table_with_large_white_margin()
    baseline = anchor._histogram_anchor_thresholds(image)

    def explode(*args, **kwargs):
        raise RuntimeError("synthetic histogram plot failure")

    monkeypatch.setattr(diagnostics, "_render_plot", explode)
    result = anchor._histogram_anchor_thresholds(image)

    for key in (
        "eligible",
        "reason",
        "background_peak_gray",
        "foreground_peak_gray",
        "valley_gray",
        "hard_threshold_gray",
        "soft_threshold_gray",
        "analysis_hard_anchor_ratio",
        "analysis_soft_anchor_ratio",
    ):
        assert result[key] == baseline[key]
    assert result["histogram_diagnostic"]["status"] == "generation_failed"
    assert result["histogram_diagnostic"]["error_type"] == "RuntimeError"
    assert "synthetic histogram plot failure" not in str(result["histogram_diagnostic"])


def test_histogram_capture_helper_exception_is_bounded_by_anchor(monkeypatch) -> None:
    image = _gray_table_with_large_white_margin()
    baseline = anchor._histogram_anchor_thresholds(image)

    def explode(*args, **kwargs):
        raise RuntimeError("synthetic capture helper failure")

    monkeypatch.setattr(diagnostics, "capture_histogram_diagnostic", explode)
    result = anchor._histogram_anchor_thresholds(image)
    assert result["eligible"] is baseline["eligible"]
    assert result["background_peak_gray"] == baseline["background_peak_gray"]
    assert result["foreground_peak_gray"] == baseline["foreground_peak_gray"]
    assert result["histogram_diagnostic"] == {
        "status": "generation_failed",
        "source_stage": "baseline_before_opencv_background_cleanup",
        "error_type": "RuntimeError",
    }


def test_histogram_artifacts_persist_as_non_reader_diagnostics(monkeypatch) -> None:
    stored: dict[str, bytes] = {}

    class Storage:
        def put(self, data, reference, *, expected_size, expected_sha256):
            assert expected_size == len(data)
            assert expected_sha256 == hashlib.sha256(data).hexdigest()
            stored[str(reference)] = data
            return SimpleNamespace(checksum_sha256=expected_sha256)

    monkeypatch.setattr(
        diagnostics,
        "_reference",
        lambda kind, checksum: f"diagnostic://{kind}/{checksum}",
    )
    public = diagnostics._persist_record(
        diagnostic_id="darkanchorhist:test",
        record={
            "plot_png": b"\x89PNG\r\n\x1a\nplot",
            "data_json": b'{"histogram":true}',
        },
        storage=Storage(),
    )
    assert public["status"] == "available"
    assert public["selected_for_reader"] is False
    assert public["plot"]["status"] == "available"
    assert public["plot"]["media_type"] == "image/png"
    assert public["data"]["status"] == "available"
    assert public["data"]["media_type"] == "application/json"
    assert len(stored) == 2


def test_malformed_histogram_record_fails_open_without_throwing() -> None:
    public = diagnostics._persist_record(
        diagnostic_id="darkanchorhist:malformed",
        record={"plot_png": object(), "data_json": b"{}"},  # type: ignore[dict-item]
        storage=object(),
    )
    assert public["status"] == "persistence_failed"
    assert public["selected_for_reader"] is False
    assert public["error_type"] == "TypeError"
    assert "diagnostic bytes are invalid" not in str(public)


def test_non_captured_histogram_is_not_persisted_from_pending_crop() -> None:
    selected_png = bridge._encode_png(_gray_table_with_large_white_margin())
    pending_crops = [
        {
            "source_unit_id": "pdf-page:000001",
            "selected_sha256": hashlib.sha256(selected_png).hexdigest(),
            "metadata": {
                "background": {
                    "dark_foreground_anchor_lock": {
                        "histogram_diagnostic": {
                            "status": "retention_skipped_capacity",
                            "diagnostic_id": "darkanchorhist:not-captured",
                        }
                    }
                }
            },
        }
    ]
    token = bridge._PENDING_CROPS.set(pending_crops)
    try:
        found = diagnostics._pending_diagnostic_id(
            {
                "png": selected_png,
                "anchor": SimpleNamespace(source_unit_id="pdf-page:000001"),
            }
        )
    finally:
        bridge._PENDING_CROPS.reset(token)
    assert found is None


def test_histogram_runtime_install_does_not_register_http_routes(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(diagnostics, "_INSTALLED", False)
    monkeypatch.setattr(diagnostics, "_install_context", lambda: calls.append("context"))
    monkeypatch.setattr(diagnostics, "_install_persistence", lambda: calls.append("persistence"))

    def forbidden_routes() -> None:
        raise AssertionError("dynamic histogram routes must stay inactive")

    monkeypatch.setattr(diagnostics, "_install_routes", forbidden_routes)
    anchor._install_histogram_diagnostics_without_routes()

    assert calls == ["context", "persistence"]
    assert diagnostics._INSTALLED is True


def test_histogram_download_routes_live_on_isolated_router() -> None:
    # The broad Modal-bridge validation intentionally runs without FastAPI; the
    # focused anchor workflow installs FastAPI and exercises this route contract.
    pytest.importorskip("fastapi")
    from app.routers import dark_anchor_diagnostics

    plot_path = (
        "/api/reader/v2/documents/{document_ref}/assets/{asset_id}/diagnostics/"
        "dark-anchor-histogram/plot"
    )
    data_path = (
        "/api/reader/v2/documents/{document_ref}/assets/{asset_id}/diagnostics/"
        "dark-anchor-histogram/data"
    )
    paths = [getattr(route, "path", None) for route in dark_anchor_diagnostics.router.routes]
    assert paths.count(plot_path) == 1
    assert paths.count(data_path) == 1
