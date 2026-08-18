from __future__ import annotations

from types import SimpleNamespace

import cv2
import numpy as np

from app.processing import pdf_clean_white_background_skip_compat as skip
from app.processing import pdf_geometry_integration as integration
from app.processing import pdf_opencv_modal_bridge as bridge
from app.processing import pdf_opencv_quality_pipeline as v4


def _png(image: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def _white_image() -> np.ndarray:
    image = np.full((300, 600, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (100, 90), (500, 210), (170, 170, 170), -1)
    return image


def _clean_white_page_manifest() -> dict[str, object]:
    precheck = skip._clean_white_precheck(_white_image())
    assert precheck["skip_background_cleanup"] is True
    return {
        "route": "geometry_only",
        "selected": "geometry",
        "geometry": {"accepted": True, "gate": {}},
        "background": {
            "attempted": False,
            "accepted": False,
            "reason": skip._PAGE_SKIP_REASON,
            "precheck": precheck,
            "gate": {},
        },
    }


def _save_runtime() -> dict[str, object]:
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


def test_safe_precheck_failure_is_bounded_and_never_requests_skip(monkeypatch) -> None:
    image = _white_image()

    def fail(_image):
        raise RuntimeError("simulated precheck failure with private detail")

    monkeypatch.setattr(skip, "_clean_white_precheck", fail)
    result = skip._safe_clean_white_precheck(image)

    assert result == {
        "policy_version": skip._POLICY_VERSION,
        "status": "failed",
        "skip_background_cleanup": False,
        "reason": skip._PRECHECK_FAILURE_REASON,
        "error_type": "RuntimeError",
        "source_dimensions": [600, 300],
    }
    assert "private detail" not in repr(result)


def test_page_precheck_failure_delegates_to_existing_normalizer_and_gate(monkeypatch) -> None:
    saved = _save_runtime()
    image = _white_image()
    calls: list[str] = []

    def legacy_normalize(source):
        calls.append("normalize")
        return np.minimum(source.astype(np.int16) + 1, 255).astype(np.uint8)

    def legacy_gate(baseline, candidate):
        calls.append("gate")
        return True, "legacy_gate_accepted", {"edge_retention": 0.99}

    def fail_precheck(_image):
        raise cv2.error("simulated")

    v4._normalize_background = legacy_normalize
    v4._gate_background_candidate = legacy_gate
    monkeypatch.setattr(skip, "_clean_white_precheck", fail_precheck)
    skip._INSTALLED = False
    try:
        skip.install_pdf_clean_white_background_skip_compat()
        active = skip._PAGE_PREPROCESS_ACTIVE.set(True)
        last = skip._PAGE_LAST_PRECHECK.set(None)
        try:
            candidate = v4._normalize_background(image)
            accepted, reason, gate = v4._gate_background_candidate(image, candidate)
        finally:
            skip._PAGE_LAST_PRECHECK.reset(last)
            skip._PAGE_PREPROCESS_ACTIVE.reset(active)

        assert calls == ["normalize", "gate"]
        assert accepted is True
        assert reason == "legacy_gate_accepted"
        assert gate["edge_retention"] == 0.99
        failure = gate["clean_white_precheck"]
        assert failure["status"] == "failed"
        assert failure["skip_background_cleanup"] is False
        assert failure["error_type"] == "error"
    finally:
        _restore_runtime(saved)


def test_crop_precheck_failure_delegates_to_existing_semantic_path(monkeypatch) -> None:
    image = _white_image()
    png = _png(image)
    page_manifest = _clean_white_page_manifest()
    calls: list[str] = []

    def fail_precheck(_image):
        raise RuntimeError("simulated")

    def delegate(png_bytes: bytes, *, page_manifest, **kwargs):
        calls.append("delegate")
        return png_bytes, {
            "status": "quality_gate_original",
            "background": {"attempted": True, "accepted": False},
        }

    monkeypatch.setattr(skip, "_clean_white_precheck", fail_precheck)
    output, metadata = skip._process_crop_with_policy(
        delegate,
        png,
        page_manifest=page_manifest,
    )

    assert calls == ["delegate"]
    assert output == png
    failure = metadata["background"]["precheck"]
    assert failure["status"] == "failed"
    assert failure["skip_background_cleanup"] is False
    assert failure["error_type"] == "RuntimeError"


def test_manifest_rewrite_failure_cannot_fail_successful_preprocess(monkeypatch) -> None:
    saved = _save_runtime()
    processed = SimpleNamespace(checksum_sha256="a" * 64)

    def successful_preprocess(pdf_bytes: bytes, **kwargs):
        return processed

    def fail_rewrite(_checksum):
        raise TypeError("simulated diagnostic-only rewrite failure")

    integration.preprocess_pdf_geometry = successful_preprocess
    monkeypatch.setattr(skip, "_rewrite_clean_white_manifest", fail_rewrite)
    skip._INSTALLED = False
    try:
        skip.install_pdf_clean_white_background_skip_compat()
        assert integration.preprocess_pdf_geometry(b"%PDF-test") is processed
    finally:
        _restore_runtime(saved)
