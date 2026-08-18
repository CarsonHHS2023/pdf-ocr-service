"""Overlay local-peak evidence onto dark-anchor histogram diagnostics.

The base histogram diagnostic remains the durable source of truth. This test-only
compat layer adds the v2 local-peak candidate list, support ratio, prominence
ratio, and selected foreground peak to both the PNG plot and JSON payload without
changing any anchor decision. It also makes the legacy valley-ratio reference
explicitly diagnostic-only on the plot. All failures remain fail-open to the base
diagnostic.
"""
from __future__ import annotations

import json
import threading
from typing import Mapping

import cv2
import numpy as np

from app.processing import pdf_crop_dark_foreground_anchor_diagnostics_compat as diagnostics

_INSTALL_LOCK = threading.Lock()
_INSTALLED = False


def _candidate_list(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _threshold(selection: Mapping[str, object], name: str, default: object) -> object:
    thresholds = selection.get("thresholds")
    if not isinstance(thresholds, Mapping):
        return default
    return thresholds.get(name, default)


def _overlay_plot(
    plot_png: bytes,
    smoothed: np.ndarray,
    selection: Mapping[str, object],
) -> bytes:
    encoded = np.frombuffer(plot_png, dtype=np.uint8)
    canvas = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if canvas is None:
        raise ValueError("dark-anchor diagnostic plot PNG could not be decoded")

    candidates = _candidate_list(selection.get("foreground_peak_candidates"))
    selected_gray = selection.get("foreground_peak_gray")
    font = cv2.FONT_HERSHEY_SIMPLEX

    # Replace the legacy line that looked like valley<=0.80 was still an
    # eligibility gate. The value remains visible for historical diagnosis only.
    cv2.rectangle(canvas, (35, 80), (diagnostics._PLOT_WIDTH - 35, 113), (255, 255, 255), -1)
    max_valley = float(
        _threshold(selection, "maximum_valley_to_foreground_peak_ratio", 0.80)
    )
    max_hard = float(_threshold(selection, "maximum_hard_anchor_ratio", 0.18))
    max_soft = float(_threshold(selection, "maximum_soft_anchor_ratio", 0.25))
    cv2.putText(
        canvas,
        (
            f"valley/fg={selection.get('valley_to_foreground_peak_ratio', '-')} "
            f"(diagnostic only; legacy ref <= {max_valley:.2f})  "
            f"hard_ratio={selection.get('analysis_hard_anchor_ratio', '-')} "
            f"(cap <= {max_hard:.2f})  "
            f"soft_ratio={selection.get('analysis_soft_anchor_ratio', '-')} "
            f"(cap <= {max_soft:.2f})"
        ),
        (40, 102),
        font,
        0.46,
        (45, 45, 45),
        1,
        cv2.LINE_AA,
    )

    smooth_log = np.log10(np.asarray(smoothed, dtype=np.float64) + 1.0)
    max_log = max(1.0, float(np.max(smooth_log)))
    plot_height = diagnostics._PLOT_BOTTOM - diagnostics._PLOT_TOP

    def y_for(value: float) -> int:
        bounded = max(0.0, min(max_log, float(value)))
        return int(
            round(
                diagnostics._PLOT_BOTTOM
                - plot_height * bounded / max_log
            )
        )

    # One bounded summary line keeps every retained candidate auditable even when
    # labels would overlap on the curve.
    summary_parts: list[str] = []
    for item in candidates[:8]:
        gray = item.get("gray")
        if not isinstance(gray, int) or isinstance(gray, bool):
            continue
        support = item.get("support_ratio")
        prominence = item.get("prominence_ratio")
        qualified = item.get("qualified") is True
        marker = "*" if gray == selected_gray else "+" if qualified else "x"
        summary_parts.append(f"{marker}{gray}:s={support},p={prominence}")
    if summary_parts:
        cv2.putText(
            canvas,
            "LOCAL PEAKS (* selected, + qualified, x rejected): "
            + "  ".join(summary_parts),
            (40, 186),
            font,
            0.38,
            (55, 55, 55),
            1,
            cv2.LINE_AA,
        )

    plotted_grays: set[int] = set()
    for item in candidates:
        gray = item.get("gray")
        if not isinstance(gray, int) or isinstance(gray, bool):
            continue
        if not 0 <= gray <= 255:
            continue
        plotted_grays.add(gray)
        qualified = item.get("qualified") is True
        selected = gray == selected_gray
        x = diagnostics._plot_x(gray)
        y = y_for(smooth_log[gray])
        if selected:
            color = (220, 70, 0)
            radius = 6
            thickness = 2
        elif qualified:
            color = (0, 150, 0)
            radius = 5
            thickness = 2
        else:
            color = (120, 120, 120)
            radius = 4
            thickness = 1
        cv2.circle(canvas, (x, y), radius, color, thickness, cv2.LINE_AA)

    # The candidate list is intentionally bounded in public diagnostics. Always
    # mark the selected FG even if an unusually noisy histogram pushes it beyond
    # that bounded list.
    if (
        isinstance(selected_gray, int)
        and not isinstance(selected_gray, bool)
        and 0 <= selected_gray <= 255
        and selected_gray not in plotted_grays
    ):
        cv2.circle(
            canvas,
            (diagnostics._plot_x(selected_gray), y_for(smooth_log[selected_gray])),
            6,
            (220, 70, 0),
            2,
            cv2.LINE_AA,
        )

    ok, output = cv2.imencode(".png", canvas)
    if not ok:
        raise RuntimeError("dark-anchor local-peak overlay could not be encoded")
    return output.tobytes()


def _install_plot_overlay() -> None:
    original = diagnostics._render_plot
    if getattr(original, "_dark_anchor_local_peak_overlay", False):
        return

    def render_plot_with_local_peaks(histogram, smoothed, selection):
        base = original(histogram, smoothed, selection)
        try:
            return _overlay_plot(base, smoothed, selection)
        except Exception:
            return base

    render_plot_with_local_peaks._dark_anchor_local_peak_overlay = True  # type: ignore[attr-defined]
    diagnostics._render_plot = render_plot_with_local_peaks


def _install_json_overlay() -> None:
    original = diagnostics._json_bytes
    if getattr(original, "_dark_anchor_local_peak_overlay", False):
        return

    def json_bytes_with_local_peaks(histogram, smoothed, selection):
        base = original(histogram, smoothed, selection)
        try:
            payload = json.loads(base.decode("utf-8"))
            algorithm = payload.get("algorithm_selection")
            if not isinstance(algorithm, dict):
                return base
            algorithm.update(
                {
                    "foreground_selection": selection.get("foreground_selection"),
                    "valley_gate_role": selection.get("valley_gate_role"),
                    "foreground_peak_candidate_count": selection.get(
                        "foreground_peak_candidate_count"
                    ),
                    "qualified_foreground_peak_candidate_count": selection.get(
                        "qualified_foreground_peak_candidate_count"
                    ),
                    "foreground_peak_candidates": list(
                        selection.get("foreground_peak_candidates") or []
                    ),
                    "selected_foreground_peak_support_ratio": selection.get(
                        "selected_foreground_peak_support_ratio"
                    ),
                    "selected_foreground_peak_prominence_ratio": selection.get(
                        "selected_foreground_peak_prominence_ratio"
                    ),
                }
            )
            return json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        except Exception:
            return base

    json_bytes_with_local_peaks._dark_anchor_local_peak_overlay = True  # type: ignore[attr-defined]
    diagnostics._json_bytes = json_bytes_with_local_peaks


def install_pdf_crop_dark_foreground_anchor_peak_diagnostics_compat() -> None:
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _install_plot_overlay()
        _install_json_overlay()
        _INSTALLED = True


__all__ = ["install_pdf_crop_dark_foreground_anchor_peak_diagnostics_compat"]
