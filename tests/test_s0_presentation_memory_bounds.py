from __future__ import annotations

import fitz
import numpy as np

from app.processing import pdf_page_orientation_compat as orientation
from app.processing import pdf_page_presentation_bridge as bridge
from app.processing import pdf_page_presentation_preprocess_compat as compat
from app.processing import pdf_s0_bounded_memory_compat as bounded
from app.processing import s0_pdf_resource_heartbeat as heartbeat


def _pdf(page_count: int = 1) -> bytes:
    document = fitz.open()
    try:
        for page_number in range(1, page_count + 1):
            page = document.new_page(width=300, height=400)
            page.insert_text((40, 80), f"Page {page_number}")
        return document.tobytes(garbage=4, deflate=True)
    finally:
        document.close()


def _contains_ndarray(value) -> bool:
    if isinstance(value, np.ndarray):
        return True
    if isinstance(value, dict):
        return any(_contains_ndarray(child) for child in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_ndarray(child) for child in value)
    return False


def _classification_result():
    return {
        "source_unit_id": "pdf-page:000001",
        "page_role": "cover",
        "confidence": 0.99,
        "reason_codes": ["test"],
        "provider": "test",
        "model_id": "test-model",
        "prompt_version": "test-prompt",
        "image_detail": "low",
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_hit": False,
    }


def _presentation_decision():
    return {
        "page_index": 0,
        "page_number": 1,
        "source_unit_id": "pdf-page:000001",
        "features": {
            "native_text_chars": 12,
            "maximum_embedded_image_coverage": 0.0,
        },
        "candidate": True,
        "candidate_reasons": ("test",),
        "classification": {
            **_classification_result(),
            "candidate_features": {},
            "candidate_reasons": ["test"],
            "skip_ocr": True,
            "decision_reason": "presentation_page_confirmed",
        },
        "skip_ocr": True,
        "decision_reason": "presentation_page_confirmed",
        "orientation": {
            "correction_degrees": 0,
            "applied": False,
            "confidence": 1.0,
            "source": "test",
            "native_text_chars": 0,
            "image_score": 0.0,
        },
        "geometry": {
            "accepted": False,
            "reason": "no_geometry_change",
            "gate": {},
            "applied_steps": [],
        },
        "page_width_points": 300.0,
        "page_height_points": 400.0,
    }


def test_oriented_classification_does_not_retain_page_rasters(monkeypatch):
    geometry_image = np.ones((16, 16, 3), dtype=np.uint8)
    orientation_image = np.ones((18, 12, 3), dtype=np.uint8)
    analysis_image = np.zeros((8, 8, 3), dtype=np.uint8)
    detected = orientation.DiscreteOrientation(
        correction_degrees=90,
        confidence=0.99,
        source="test",
        native_text_chars=0,
        image_score=1.0,
    )

    monkeypatch.setattr(bridge, "_analysis_image", lambda _page: analysis_image)
    monkeypatch.setattr(
        orientation,
        "detect_discrete_orientation",
        lambda _page, _image: detected,
    )
    monkeypatch.setattr(
        bridge,
        "_native_page_features",
        lambda _page: {"native_text_chars": 12},
    )
    monkeypatch.setattr(
        bridge,
        "_image_features",
        lambda _image: {"maximum_embedded_image_coverage": 0.0},
    )
    monkeypatch.setattr(
        bridge,
        "_is_candidate",
        lambda *_args, **_kwargs: (True, ("test",)),
    )
    monkeypatch.setattr(
        orientation,
        "_oriented_geometry",
        lambda _page, _orientation: (
            geometry_image,
            {
                "accepted": True,
                "reason": "accepted",
                "gate": {},
                "applied_steps": ["discrete_orientation_90"],
                "orientation": {
                    "detected_degrees": 90,
                    "correction_degrees": 90,
                    "applied": True,
                    "confidence": 0.99,
                    "source": "test",
                    "native_text_chars": 0,
                    "image_score": 1.0,
                },
            },
            orientation_image,
        ),
    )
    monkeypatch.setattr(
        bridge,
        "_encode_png",
        lambda image: b"png" if image is geometry_image else b"unexpected",
    )
    monkeypatch.setattr(
        bridge,
        "_classify",
        lambda *_args, **_kwargs: _classification_result(),
    )
    monkeypatch.setattr(
        bridge,
        "_skip_ocr_decision",
        lambda *_args, **_kwargs: (True, "presentation_page_confirmed"),
    )
    monkeypatch.setattr(compat, "_set_s0_work_phase", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        compat,
        "_mark_s0_work_page_completed",
        lambda **_kwargs: None,
    )

    document = fitz.open(stream=_pdf(), filetype="pdf")
    try:
        decisions = orientation._classify_source_pages_oriented(document)
    finally:
        document.close()

    assert len(decisions) == 1
    assert not isinstance(decisions[0].get("geometry_image"), np.ndarray)
    assert not isinstance(decisions[0].get("orientation_image"), np.ndarray)
    assert _contains_ndarray(decisions) is False
    assert decisions[0]["geometry"]["accepted"] is True


def test_final_bounded_classifier_strips_legacy_raster_slots(monkeypatch):
    raster = np.ones((8, 8, 3), dtype=np.uint8)
    source_decision = _presentation_decision()
    source_decision["geometry_image"] = raster
    source_decision["orientation_image"] = raster
    monkeypatch.setattr(
        bounded,
        "_ORIGINAL_CLASSIFY",
        lambda _source: [source_decision],
    )

    document = fitz.open(stream=_pdf(), filetype="pdf")
    try:
        decisions = bounded._bounded_classify_source_pages(document)
    finally:
        document.close()

    assert "geometry_image" not in decisions[0]
    assert "orientation_image" not in decisions[0]
    assert _contains_ndarray(decisions) is False


def test_render_recomputes_presentation_geometry_instead_of_reusing_raster(monkeypatch):
    decision = _presentation_decision()
    geometry_image = np.ones((12, 12, 3), dtype=np.uint8)
    inserted = []

    monkeypatch.setattr(compat, "_set_s0_work_phase", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        compat,
        "_mark_s0_work_page_completed",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        orientation,
        "_presentation_geometry_from_decision",
        lambda _page, _decision: (
            geometry_image,
            {
                "accepted": True,
                "reason": "accepted",
                "gate": {},
                "applied_steps": ["opencv_deskew"],
            },
        ),
    )

    def insert(output, source, page_index, image):
        inserted.append(image)
        output.insert_pdf(source, from_page=page_index, to_page=page_index)

    monkeypatch.setattr(bridge, "_insert_geometry_or_original", insert)

    source = fitz.open(stream=_pdf(), filetype="pdf")
    try:
        rendered = bounded._bounded_build_full_render(source, [decision], None)
    finally:
        source.close()

    output = fitz.open(stream=rendered, filetype="pdf")
    try:
        assert output.page_count == 1
    finally:
        output.close()
    assert len(inserted) == 1
    assert inserted[0] is geometry_image
    assert decision["geometry"]["accepted"] is True


def test_native_text_render_preserves_original_without_geometry_recompute(monkeypatch):
    decision = _presentation_decision()
    decision["native_text_accepted"] = True
    decision["decision_reason"] = "native_pdf_text_accepted"

    monkeypatch.setattr(compat, "_set_s0_work_phase", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        compat,
        "_mark_s0_work_page_completed",
        lambda **_kwargs: None,
    )

    def unexpected(*_args, **_kwargs):
        raise AssertionError("native text render must not recompute presentation geometry")

    monkeypatch.setattr(
        orientation,
        "_presentation_geometry_from_decision",
        unexpected,
    )

    source = fitz.open(stream=_pdf(), filetype="pdf")
    try:
        rendered = bounded._bounded_build_full_render(source, [decision], None)
    finally:
        source.close()

    output = fitz.open(stream=rendered, filetype="pdf")
    try:
        assert output.page_count == 1
    finally:
        output.close()


def test_orientation_adjusted_manifest_preserves_quarter_turn_dimensions(monkeypatch):
    decision = _presentation_decision()
    decision["orientation"] = {
        "correction_degrees": 90,
        "applied": True,
        "confidence": 0.99,
        "source": "test",
        "native_text_chars": 0,
        "image_score": 1.0,
    }
    decision["geometry"] = {
        "accepted": True,
        "orientation": {
            "detected_degrees": 90,
            "correction_degrees": 90,
            "applied": True,
            "confidence": 0.99,
            "source": "test",
        },
    }
    monkeypatch.setattr(
        bounded,
        "_ORIGINAL_MANIFEST_PAGE",
        lambda _decision: {
            "page_width_points": 300.0,
            "page_height_points": 400.0,
        },
    )

    result = bounded._orientation_adjusted_manifest_page(decision)

    assert result["source_page_width_points"] == 300.0
    assert result["source_page_height_points"] == 400.0
    assert result["page_width_points"] == 400.0
    assert result["page_height_points"] == 300.0


def test_phase_telemetry_separates_classification_and_ordinary_v4(monkeypatch):
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        heartbeat,
        "record_pdf_processing_heartbeat",
        lambda **kwargs: events.append(kwargs) or {},
    )
    state = heartbeat._new_observation_state(
        processing_run_id="pdf-ingest-test",
        document_id="doc-1",
        page_count=528,
    )
    previous_state = getattr(heartbeat._CONTEXT, "value", None)
    original_stage = heartbeat._set_opencv_stage
    heartbeat._CONTEXT.value = state
    try:
        compat._set_s0_work_phase("presentation_classification", 528)
        compat._mark_s0_work_page_completed(
            page_number=10,
            page_count=528,
            route="presentation_classification",
        )
        heartbeat._set_opencv_stage(
            "geometry_candidate_start",
            page_number=11,
            durable_first_page=False,
        )
        heartbeat._record_liveness_heartbeat(state)

        compat._set_s0_work_phase("ordinary_v4_preprocessing", 500)
        heartbeat._set_opencv_stage(
            "source_render_300dpi_start",
            page_number=1,
        )
        heartbeat._record_liveness_heartbeat(state)
    finally:
        heartbeat._set_opencv_stage = original_stage
        heartbeat._CONTEXT.value = previous_state

    classification_liveness = next(
        item
        for item in events
        if item["phase"] == "opencv_liveness"
        and item["current_stage"].startswith("presentation_classification:")
    )
    assert classification_liveness["page_number"] == 11
    assert classification_liveness["page_count"] == 528
    assert classification_liveness["last_completed_page"] == 10

    ordinary_start = next(
        item
        for item in events
        if item["phase"] == "work_phase_started"
        and item.get("work_phase") == "ordinary_v4_preprocessing"
    )
    assert ordinary_start["page_count"] == 500
    assert ordinary_start["document_page_count"] == 528
    assert ordinary_start["last_completed_page"] == 0

    ordinary_liveness = next(
        item
        for item in events
        if item["phase"] == "opencv_liveness"
        and item["current_stage"].startswith("ordinary_v4_preprocessing:")
    )
    assert ordinary_liveness["page_number"] == 1
    assert ordinary_liveness["page_count"] == 500
    assert ordinary_liveness["last_completed_page"] == 0
