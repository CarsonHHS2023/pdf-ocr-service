from __future__ import annotations

import cv2
import numpy as np

from app.processing import pdf_opencv_quality_pipeline as v4
from app.processing.pdf_opencv_modal_bridge import (
    _merge_manifest_into_raw_pages,
    _whole_page_rejected,
    process_visual_crop_v4,
)


def _rejected_page() -> dict[str, object]:
    return {
        "page_number": 9,
        "route": "quality_gate_original",
        "selected": "original",
        "geometry": {
            "accepted": False,
            "reason": "content_guard_rejected",
            "gate": {"long_lines_safe": False},
        },
        "background": {
            "attempted": True,
            "accepted": False,
            "reason": "content_guard_rejected",
            "gate": {"edge_retention": 0.67},
        },
    }


def _geometry_only_page() -> dict[str, object]:
    return {
        **_rejected_page(),
        "route": "geometry_only",
        "selected": "geometry",
        "geometry": {
            "accepted": True,
            "reason": "accepted",
            "gate": {"deskew_improved": True},
        },
    }


def _png() -> bytes:
    image = np.full((80, 120, 3), 220, dtype=np.uint8)
    cv2.rectangle(image, (10, 10), (110, 70), (0, 0, 0), 2)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def test_crop_retry_requires_failed_background_gate_and_consistent_page_state() -> None:
    rejected = _rejected_page()
    geometry_only = _geometry_only_page()

    assert _whole_page_rejected(rejected)
    assert _whole_page_rejected(geometry_only)
    assert not _whole_page_rejected({**rejected, "selected": "background"})
    assert not _whole_page_rejected({**rejected, "route": "color_critical_no_op"})
    assert not _whole_page_rejected({**geometry_only, "selected": "original"})
    assert not _whole_page_rejected({**geometry_only, "route": "quality_gate_original"})
    assert not _whole_page_rejected(
        {
            **geometry_only,
            "background": {
                "attempted": True,
                "accepted": True,
                "reason": "accepted",
                "gate": {"edge_retention": 0.90},
            },
        }
    )
    assert not _whole_page_rejected(
        {
            **geometry_only,
            "background": {
                "attempted": False,
                "accepted": False,
                "reason": "color_critical_background_skipped",
                "gate": {},
            },
        }
    )


def test_manifest_is_merged_without_losing_provider_page_metadata() -> None:
    page = _rejected_page()
    merged = _merge_manifest_into_raw_pages(
        [
            {
                "page_number": 9,
                "width": 100,
                "height": 100,
                "metadata": {"provider": "paddle"},
            }
        ],
        {"pages": [page]},
    )
    assert merged[0]["metadata"]["provider"] == "paddle"
    assert merged[0]["metadata"]["opencv_preprocessing"] == page


def test_noneligible_crop_is_preserved_without_llm_request() -> None:
    source = _png()
    selected, metadata = process_visual_crop_v4(
        source,
        page_manifest={**_rejected_page(), "route": "geometry_only"},
    )
    assert selected == source
    assert metadata["status"] == "not_required"
    assert metadata["changed"] is False
    assert metadata["llm_fallback"] == {
        "required": False,
        "status": "not_required",
        "invoked": False,
    }


def test_rejected_crop_records_deferred_llm_without_invocation(monkeypatch) -> None:
    source = _png()
    diagnostic = v4._GeometryDiagnostic(
        perspective_applied=False,
        perspective_confidence=0.0,
        perspective_distortion=0.0,
        deskew_applied=False,
        deskew_angle_degrees=0.0,
        deskew_confidence=0.0,
        residual_angle_degrees=0.0,
        residual_confidence=0.0,
    )
    color = v4._ColorFeatures(0.0, 0.0, 0.0, False)
    monkeypatch.setattr(v4, "_color_features", lambda image: color)
    monkeypatch.setattr(v4, "_build_geometry_candidate", lambda image: (image, diagnostic))
    monkeypatch.setattr(
        v4,
        "_gate_geometry_candidate",
        lambda original, candidate, diag: (False, "geometry_not_required", {}),
    )
    monkeypatch.setattr(v4, "_normalize_background", lambda image: image)
    monkeypatch.setattr(
        v4,
        "_gate_background_candidate",
        lambda baseline, candidate: (
            False,
            "content_guard_rejected",
            {"edge_retention": 0.65},
        ),
    )

    selected, metadata = process_visual_crop_v4(source, page_manifest=_rejected_page())

    assert selected == source
    assert metadata["status"] == "quality_gate_original"
    assert metadata["selected"] == "original"
    assert metadata["llm_fallback"] == {
        "required": True,
        "status": "deferred",
        "invoked": False,
    }


def test_geometry_only_page_retries_crop_and_uses_accepted_v4_result(monkeypatch) -> None:
    source = _png()
    diagnostic = v4._GeometryDiagnostic(
        perspective_applied=False,
        perspective_confidence=0.0,
        perspective_distortion=0.0,
        deskew_applied=False,
        deskew_angle_degrees=0.0,
        deskew_confidence=0.0,
        residual_angle_degrees=0.0,
        residual_confidence=0.0,
    )
    color = v4._ColorFeatures(0.0, 0.0, 0.0, False)
    monkeypatch.setattr(v4, "_color_features", lambda image: color)
    monkeypatch.setattr(v4, "_build_geometry_candidate", lambda image: (image, diagnostic))
    monkeypatch.setattr(
        v4,
        "_gate_geometry_candidate",
        lambda original, candidate, diag: (False, "geometry_not_required", {}),
    )
    monkeypatch.setattr(
        v4,
        "_normalize_background",
        lambda image: np.full_like(image, 255),
    )
    monkeypatch.setattr(
        v4,
        "_gate_background_candidate",
        lambda baseline, candidate: (
            True,
            "accepted",
            {"edge_retention": 0.90, "white_ratio_improved": True},
        ),
    )

    selected, metadata = process_visual_crop_v4(
        source,
        page_manifest=_geometry_only_page(),
    )

    assert selected != source
    assert metadata["page_retry_eligible"] is True
    assert metadata["whole_page_route"] == "geometry_only"
    assert metadata["whole_page_selected"] == "geometry"
    assert metadata["status"] == "accepted"
    assert metadata["selected"] == "background"
    assert metadata["changed"] is True
    assert metadata["llm_fallback"] == {
        "required": False,
        "status": "not_required",
        "invoked": False,
    }
