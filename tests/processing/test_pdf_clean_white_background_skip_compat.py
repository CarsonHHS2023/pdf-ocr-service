from __future__ import annotations

from copy import deepcopy

import cv2
import fitz  # type: ignore[import]
import numpy as np

from app.processing import pdf_clean_white_background_skip_compat as skip
from app.processing import pdf_geometry_integration as integration
from app.processing import pdf_opencv_modal_bridge as bridge
from app.processing import pdf_opencv_quality_pipeline as v4


def _png(image: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def _white_diagram(width: int = 900, height: int = 500) -> np.ndarray:
    image = np.full((height, width, 3), 255, dtype=np.uint8)
    # Intentional gray diagram content occupies a large interior region while the
    # surrounding page/crop remains one connected white background.
    cv2.rectangle(
        image,
        (int(width * 0.08), int(height * 0.18)),
        (int(width * 0.90), int(height * 0.72)),
        (165, 165, 165),
        -1,
    )
    cv2.rectangle(
        image,
        (int(width * 0.18), int(height * 0.28)),
        (int(width * 0.80), int(height * 0.62)),
        (205, 205, 205),
        -1,
    )
    for x in range(int(width * 0.20), int(width * 0.78), max(12, width // 14)):
        cv2.circle(image, (x, int(height * 0.45)), 4, (125, 125, 125), -1)
    return image


def _gray_scan(width: int = 900, height: int = 500) -> np.ndarray:
    y, x = np.indices((height, width))
    gray = 205 + ((x * 3 + y * 5) % 17 - 8)
    gray = np.clip(gray, 0, 255).astype(np.uint8)
    image = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    cv2.line(image, (50, 90), (850, 90), (85, 85, 85), 2)
    cv2.putText(
        image,
        "15,000  16,224  18,250",
        (120, 250),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (70, 70, 70),
        2,
        cv2.LINE_AA,
    )
    return image


def _page_manifest(*, geometry_accepted: bool = True) -> dict[str, object]:
    precheck = skip._clean_white_precheck(_white_diagram())
    assert precheck["skip_background_cleanup"] is True
    return {
        "route": "geometry_only" if geometry_accepted else "quality_gate_original",
        "selected": "geometry" if geometry_accepted else "original",
        "geometry": {"accepted": geometry_accepted, "gate": {}},
        "background": {
            "attempted": False,
            "accepted": False,
            "reason": skip._PAGE_SKIP_REASON,
            "precheck": precheck,
            "gate": {},
        },
    }


def _saved_runtime() -> dict[str, object]:
    return {
        "normalize": v4._normalize_background,
        "gate": v4._gate_background_candidate,
        "preprocess_v4": v4.preprocess_pdf_geometry_opencv,
        "preprocess_integration": integration.preprocess_pdf_geometry,
        "retry": bridge._whole_page_rejected,
        "process": bridge.process_visual_crop_v4,
        "installed": skip._INSTALLED,
    }


def _restore_runtime(saved: dict[str, object]) -> None:
    v4._normalize_background = saved["normalize"]
    v4._gate_background_candidate = saved["gate"]
    v4.preprocess_pdf_geometry_opencv = saved["preprocess_v4"]
    integration.preprocess_pdf_geometry = saved["preprocess_integration"]
    bridge._whole_page_rejected = saved["retry"]
    bridge.process_visual_crop_v4 = saved["process"]
    skip._INSTALLED = saved["installed"]


def test_white_background_with_intentional_gray_diagram_is_skipped() -> None:
    result = skip._clean_white_precheck(_white_diagram())
    assert result["skip_background_cleanup"] is True
    assert result["near_white_ratio"] >= 0.50
    assert result["largest_near_white_component_ratio"] >= 0.45
    assert result["largest_border_connected_near_white_component_ratio"] >= 0.45
    assert result["border_near_white_ratio"] >= 0.80


def test_gray_scan_still_requires_background_cleanup() -> None:
    result = skip._clean_white_precheck(_gray_scan())
    assert result["skip_background_cleanup"] is False
    assert result["near_white_ratio"] < 0.50


def test_white_background_precheck_is_conservative_at_half_page_boundary() -> None:
    image = np.full((500, 900, 3), 255, dtype=np.uint8)
    # Leave less than half the image near-white even though the outer border is
    # white. This must not be skipped merely because the border is white.
    cv2.rectangle(image, (60, 40), (840, 330), (190, 190, 190), -1)
    cv2.rectangle(image, (60, 330), (840, 460), (205, 205, 205), -1)
    result = skip._clean_white_precheck(image)
    assert result["border_near_white_ratio"] >= 0.80
    assert result["near_white_ratio"] < 0.50
    assert result["skip_background_cleanup"] is False


def test_large_interior_white_region_must_connect_to_border_background() -> None:
    image = np.full((500, 900, 3), 255, dtype=np.uint8)
    # A thick dark frame disconnects a very large white interior from the white
    # outer margin. Large-white + white-border metrics alone would be misleading.
    cv2.rectangle(image, (75, 55), (825, 445), (80, 80, 80), 24)
    result = skip._clean_white_precheck(image)
    assert result["near_white_ratio"] >= 0.50
    assert result["largest_near_white_component_ratio"] >= 0.45
    assert result["border_near_white_ratio"] >= 0.80
    assert result["largest_border_connected_near_white_component_ratio"] < 0.45
    assert result["skip_background_cleanup"] is False


def test_precheck_analysis_is_bounded_for_large_pages() -> None:
    image = _white_diagram(width=3600, height=2400)
    result = skip._clean_white_precheck(image)
    assert max(result["analysis_dimensions"]) <= skip._ANALYSIS_MAX_SIDE
    assert result["source_dimensions"] == [3600, 2400]


def test_page_manifest_rewrite_marks_clean_white_as_not_attempted() -> None:
    checksum = "f" * 64
    precheck = skip._clean_white_precheck(_white_diagram())
    manifest = {
        "pages": [
            {
                "page_number": 1,
                "background": {
                    "attempted": True,
                    "accepted": False,
                    "reason": skip._PAGE_SKIP_REASON,
                    "gate": {"clean_white_precheck": deepcopy(precheck)},
                },
            }
        ]
    }
    with v4._DIAGNOSTIC_LOCK:
        old = v4._DIAGNOSTIC_MANIFESTS.get(checksum)
        v4._DIAGNOSTIC_MANIFESTS[checksum] = manifest
    try:
        skip._rewrite_clean_white_manifest(checksum)
        with v4._DIAGNOSTIC_LOCK:
            background = v4._DIAGNOSTIC_MANIFESTS[checksum]["pages"][0]["background"]
        assert background["attempted"] is False
        assert background["accepted"] is False
        assert background["reason"] == skip._PAGE_SKIP_REASON
        assert background["precheck"]["skip_background_cleanup"] is True
        assert background["gate"] == {}
    finally:
        with v4._DIAGNOSTIC_LOCK:
            if old is None:
                v4._DIAGNOSTIC_MANIFESTS.pop(checksum, None)
            else:
                v4._DIAGNOSTIC_MANIFESTS[checksum] = old


def test_page_manifest_keeps_non_skip_precheck_for_real_world_tuning() -> None:
    checksum = "e" * 64
    precheck = skip._clean_white_precheck(_gray_scan())
    manifest = {
        "pages": [
            {
                "page_number": 1,
                "background": {
                    "attempted": True,
                    "accepted": False,
                    "reason": "content_guard_rejected",
                    "gate": {
                        "edge_retention": 0.66,
                        "clean_white_precheck": deepcopy(precheck),
                    },
                },
            }
        ]
    }
    with v4._DIAGNOSTIC_LOCK:
        old = v4._DIAGNOSTIC_MANIFESTS.get(checksum)
        v4._DIAGNOSTIC_MANIFESTS[checksum] = manifest
    try:
        skip._rewrite_clean_white_manifest(checksum)
        with v4._DIAGNOSTIC_LOCK:
            background = v4._DIAGNOSTIC_MANIFESTS[checksum]["pages"][0]["background"]
        assert background["attempted"] is True
        assert background["reason"] == "content_guard_rejected"
        assert background["precheck"]["skip_background_cleanup"] is False
        assert background["gate"]["edge_retention"] == 0.66
    finally:
        with v4._DIAGNOSTIC_LOCK:
            if old is None:
                v4._DIAGNOSTIC_MANIFESTS.pop(checksum, None)
            else:
                v4._DIAGNOSTIC_MANIFESTS[checksum] = old


def test_clean_white_page_is_crop_retry_eligible_in_geometry_or_original_state() -> None:
    geometry_page = _page_manifest(geometry_accepted=True)
    original_page = _page_manifest(geometry_accepted=False)
    assert skip._page_clean_white_skipped(geometry_page)
    assert skip._page_state_consistent_for_crop_retry(geometry_page)
    assert skip._page_state_consistent_for_crop_retry(original_page)

    bad = deepcopy(geometry_page)
    bad["selected"] = "original"
    assert not skip._page_state_consistent_for_crop_retry(bad)


def test_crop_skip_keeps_geometry_but_never_generates_background_candidate(monkeypatch) -> None:
    source = _white_diagram()
    png = _png(source)
    geometry = source.copy()
    geometry[20:24, 20:24] = 250
    diagnostic = v4._GeometryDiagnostic(
        perspective_applied=False,
        perspective_confidence=1.0,
        perspective_distortion=0.0,
        deskew_applied=True,
        deskew_angle_degrees=0.5,
        deskew_confidence=0.9,
        residual_angle_degrees=0.0,
        residual_confidence=0.9,
    )
    monkeypatch.setattr(v4, "_build_geometry_candidate", lambda image: (geometry, diagnostic))
    monkeypatch.setattr(
        v4,
        "_gate_geometry_candidate",
        lambda original, candidate, diag: (True, "accepted", {"deskew_improved": True}),
    )
    analysis = skip._crop_geometry_analysis(png)
    output, metadata = skip._build_clean_white_crop_result(
        png,
        page_manifest=_page_manifest(),
        precheck=skip._clean_white_precheck(analysis[-1]),
        geometry_analysis=analysis,
    )
    assert output == bridge._encode_png(geometry)
    assert metadata["selected"] == "geometry"
    assert metadata["background"]["attempted"] is False
    assert metadata["background"]["reason"] == skip._CROP_SKIP_REASON
    assert metadata["semantic_gate"]["invoked"] is False
    assert metadata["opencv_candidate_sha256"] is None
    assert metadata["foreground_lock_used"] is False
    assert metadata["gpt_image_used"] is False


def test_installed_policy_skips_white_crop_but_delegates_gray_crop() -> None:
    saved = _saved_runtime()
    calls: list[str] = []

    def delegate(png_bytes: bytes, *, page_manifest, **kwargs):
        calls.append("delegate")
        return png_bytes, {"background": {"attempted": True}, "delegated": True}

    bridge.process_visual_crop_v4 = delegate
    skip._INSTALLED = False
    try:
        skip.install_pdf_clean_white_background_skip_compat()
        white_png = _png(_white_diagram())
        _, metadata = bridge.process_visual_crop_v4(
            white_png,
            page_manifest=_page_manifest(),
        )
        assert calls == []
        assert metadata["background"]["attempted"] is False
        assert metadata["semantic_gate"]["invoked"] is False

        gray_png = _png(_gray_scan())
        _, metadata = bridge.process_visual_crop_v4(
            gray_png,
            page_manifest=_page_manifest(),
        )
        assert calls == ["delegate"]
        assert metadata["delegated"] is True
        assert metadata["background"]["precheck"]["skip_background_cleanup"] is False

        # A white crop from a page that was not skipped for clean-white must keep
        # the existing path; the crop rule is intentionally conditional on page state.
        _, metadata = bridge.process_visual_crop_v4(
            white_png,
            page_manifest={"background": {"accepted": False, "reason": "content_guard_rejected"}},
        )
        assert calls == ["delegate", "delegate"]
        assert metadata["delegated"] is True
    finally:
        _restore_runtime(saved)


def test_page_normalizer_is_true_noop_for_clean_white_page() -> None:
    saved = _saved_runtime()
    normalize_calls = 0
    original_normalize = v4._normalize_background

    def counting_normalize(image):
        nonlocal normalize_calls
        normalize_calls += 1
        return original_normalize(image)

    v4._normalize_background = counting_normalize
    skip._INSTALLED = False
    try:
        skip.install_pdf_clean_white_background_skip_compat()
        token = skip._PAGE_PREPROCESS_ACTIVE.set(True)
        last = skip._PAGE_LAST_PRECHECK.set(None)
        try:
            source = _white_diagram()
            candidate = v4._normalize_background(source)
            accepted, reason, gate = v4._gate_background_candidate(source, candidate)
        finally:
            skip._PAGE_LAST_PRECHECK.reset(last)
            skip._PAGE_PREPROCESS_ACTIVE.reset(token)
        assert normalize_calls == 0
        assert np.array_equal(candidate, source)
        assert accepted is False
        assert reason == skip._PAGE_SKIP_REASON
        assert gate["clean_white_precheck"]["skip_background_cleanup"] is True
    finally:
        _restore_runtime(saved)


def test_full_page_preprocess_records_true_clean_white_skip_without_background_steps() -> None:
    saved = _saved_runtime()
    document = fitz.open()
    page = document.new_page(width=360, height=200)
    page.insert_image(page.rect, stream=_png(_white_diagram(width=1080, height=600)))
    pdf_bytes = document.tobytes(garbage=4, deflate=True)
    document.close()

    skip._INSTALLED = False
    processed = None
    try:
        skip.install_pdf_clean_white_background_skip_compat()
        processed = integration.preprocess_pdf_geometry(pdf_bytes, expected_page_count=1)
        with v4._DIAGNOSTIC_LOCK:
            manifest = deepcopy(v4._DIAGNOSTIC_MANIFESTS[processed.checksum_sha256])
        background = manifest["pages"][0]["background"]
        assert background["attempted"] is False
        assert background["accepted"] is False
        assert background["reason"] == skip._PAGE_SKIP_REASON
        assert background["precheck"]["skip_background_cleanup"] is True
        assert not any(
            step.startswith("opencv_background_")
            for step in processed.pages[0].applied_steps
        )
    finally:
        if processed is not None:
            with v4._DIAGNOSTIC_LOCK:
                v4._DIAGNOSTIC_MANIFESTS.pop(processed.checksum_sha256, None)
        _restore_runtime(saved)
