from __future__ import annotations

from types import SimpleNamespace

import fitz  # type: ignore[import]
import numpy as np
import pytest

from app.processing import pdf_opencv_quality_pipeline as v4
from app.processing import s0_v5_phase1_shared_cache as shared
from app.processing import s0_v5_phase1_shared_classification as classification
from app.processing import s0_v5_phase1_shared_v4 as shared_v4


def _shared_state(tmp_path, *, provider_map=None):
    return {
        "scratch_root": tmp_path,
        "pages": {},
        "provider_map": list(provider_map or []),
        "metrics": {},
    }


def _geometry_dict(*, accepted: bool = True) -> dict[str, object]:
    return {
        "accepted": accepted,
        "reason": "accepted" if accepted else "no_change",
        "gate": {"quality": "ok"},
        "perspective_applied": False,
        "perspective_confidence": 0.0,
        "perspective_distortion": 0.0,
        "deskew_applied": False,
        "deskew_angle_degrees": 0.0,
        "deskew_confidence": 0.0,
        "residual_angle_degrees": 0.0,
        "residual_confidence": 0.0,
        "applied_steps": [],
    }


def test_phase1_top_level_scope_is_run_local_and_resets() -> None:
    sentinel = object()
    observed: list[bool] = []

    def delegate(**kwargs):
        observed.append(shared.active_state() is not None)
        return sentinel

    wrapped = shared.wrap_top_level(delegate)
    result = wrapped(example=True)

    assert result is sentinel
    assert observed == [True]
    assert shared.active_state() is None


def test_phase1_top_level_scope_resets_after_delegate_failure() -> None:
    error = ValueError("authoritative failure")

    def delegate(**kwargs):
        assert shared.active_state() is not None
        raise error

    wrapped = shared.wrap_top_level(delegate)
    with pytest.raises(ValueError) as exc_info:
        wrapped(example=True)

    assert exc_info.value is error
    assert shared.active_state() is None


def test_geometry_delegate_is_computed_once_and_reused_from_lossless_scratch(
    tmp_path,
    monkeypatch,
) -> None:
    image = np.full((24, 16, 3), 217, dtype=np.uint8)
    calls = {"geometry": 0}

    def geometry_delegate(page):
        calls["geometry"] += 1
        return image.copy(), _geometry_dict(accepted=True)

    monkeypatch.setattr(shared, "_GEOMETRY_DELEGATE", geometry_delegate)
    state = _shared_state(tmp_path)
    token = shared._ACTIVE.set(state)
    try:
        first_image, first_geometry = shared.geometry_only_page(
            SimpleNamespace(number=0)
        )
        second_image, second_geometry = shared.geometry_only_page(
            SimpleNamespace(number=0)
        )
    finally:
        shared._ACTIVE.reset(token)

    assert calls["geometry"] == 1
    assert first_geometry == second_geometry
    assert np.array_equal(first_image, image)
    assert np.array_equal(second_image, image)
    assert state["metrics"]["geometry_computed"] == 1
    assert state["metrics"]["presentation_geometry_cache_hits"] == 1
    cached = state["pages"][1]
    assert cached["geometry_completed"] is True
    assert str(cached["geometry_path"]).endswith("page-000001-geometry-selected.npy")


def test_shared_classification_uses_one_analysis_image_when_geometry_is_rejected(
    monkeypatch,
) -> None:
    page = SimpleNamespace(
        number=0,
        rect=SimpleNamespace(width=100.0, height=200.0),
    )

    class Source:
        page_count = 1

        def __getitem__(self, index):
            assert index == 0
            return page

    from app.processing import pdf_page_presentation_bridge as bridge
    from app.processing import pdf_page_presentation_preprocess_compat as presentation

    analysis_calls = {"count": 0}

    def analysis_image(_page):
        analysis_calls["count"] += 1
        return np.zeros((20, 10, 3), dtype=np.uint8)

    monkeypatch.setattr(presentation, "_set_s0_work_phase", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        presentation,
        "_mark_s0_work_page_completed",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(bridge, "_source_unit_id", lambda page_number: "pdf-page:000001")
    monkeypatch.setattr(bridge, "_analysis_image", analysis_image)
    monkeypatch.setattr(
        bridge,
        "_combined_features",
        lambda _page, _image: {
            "native_text_chars": 0,
            "native_text_line_count": 0,
            "estimated_continuous_body_prose_ratio": 0.0,
        },
    )
    monkeypatch.setattr(bridge, "_is_candidate", lambda *args, **kwargs: (True, ("candidate",)))
    monkeypatch.setattr(
        bridge,
        "_fallback_classification",
        lambda source_unit_id, reason: {
            "source_unit_id": source_unit_id,
            "page_role": "unknown",
            "confidence": 0.0,
            "image_detail": "none",
            "cache_hit": False,
            "input_tokens": 0,
            "output_tokens": 0,
        },
    )
    monkeypatch.setattr(
        bridge,
        "_geometry_only_page",
        lambda _page: (None, _geometry_dict(accepted=False)),
    )
    monkeypatch.setattr(bridge, "_encode_png", lambda image: b"png")
    monkeypatch.setattr(
        bridge,
        "_classify",
        lambda *args, **kwargs: {
            "source_unit_id": "pdf-page:000001",
            "page_role": "body",
            "confidence": 0.99,
            "image_detail": "low",
            "cache_hit": False,
            "input_tokens": 1,
            "output_tokens": 1,
        },
    )
    monkeypatch.setattr(
        bridge,
        "_skip_ocr_decision",
        lambda *args, **kwargs: (False, "role_not_presentation"),
    )
    monkeypatch.setattr(bridge, "_json_clone", lambda value: value)
    monkeypatch.setattr(bridge, "_diagnostic", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        v4,
        "_inspect_page_structure",
        lambda _page: v4._PageStructure(
            text_chars=0,
            max_image_coverage=1.0,
            born_digital=False,
        ),
    )
    monkeypatch.setattr(
        v4,
        "_color_features",
        lambda _image: v4._ColorFeatures(
            high_saturation_ratio=0.0,
            largest_saturated_component_ratio=0.0,
            saturation_p90=0.0,
            color_critical=False,
        ),
    )

    state = {
        "scratch_root": None,
        "pages": {},
        "provider_map": [],
        "metrics": {},
    }
    token = shared._ACTIVE.set(state)
    try:
        decisions = classification.classify_source_pages(Source())
    finally:
        shared._ACTIVE.reset(token)

    assert analysis_calls["count"] == 1
    assert len(decisions) == 1
    assert decisions[0]["classification"]["page_role"] == "body"
    assert state["metrics"]["analysis_computed"] == 1


def test_shared_v4_reuses_structure_color_and_geometry_without_second_render(
    tmp_path,
    monkeypatch,
) -> None:
    source = fitz.open()
    source.new_page(width=72, height=96)
    pdf_bytes = source.tobytes(garbage=4, deflate=True)
    source.close()

    page_number = 7
    geometry_image = np.full((32, 24, 3), 240, dtype=np.uint8)
    geometry_path = tmp_path / "page-000007-geometry-selected.npy"
    np.save(geometry_path, geometry_image, allow_pickle=False)

    state = _shared_state(
        tmp_path,
        provider_map=[{"original_page_number": page_number}],
    )
    state["pages"][page_number] = {
        "structure": v4._PageStructure(
            text_chars=0,
            max_image_coverage=1.0,
            born_digital=False,
        ),
        "color": v4._ColorFeatures(
            high_saturation_ratio=0.2,
            largest_saturated_component_ratio=0.1,
            saturation_p90=90.0,
            color_critical=True,
        ),
        "geometry_completed": True,
        "geometry_path": str(geometry_path),
        "geometry_diag": v4._GeometryDiagnostic(
            perspective_applied=False,
            perspective_confidence=0.0,
            perspective_distortion=0.0,
            deskew_applied=False,
            deskew_angle_degrees=0.0,
            deskew_confidence=0.0,
            residual_angle_degrees=0.0,
            residual_confidence=0.0,
        ),
        "geometry_accepted": False,
        "geometry_reason": "no_change",
        "geometry_gate": {"quality": "ok"},
    }

    def duplicate_work(*args, **kwargs):
        raise AssertionError("shared evidence should prevent duplicate analysis")

    monkeypatch.setattr(v4, "_inspect_page_structure", duplicate_work)
    monkeypatch.setattr(v4, "_render_page_bgr", duplicate_work)
    monkeypatch.setattr(v4, "_color_features", duplicate_work)
    monkeypatch.setattr(v4, "_build_geometry_candidate", duplicate_work)
    monkeypatch.setattr(v4, "_gate_geometry_candidate", duplicate_work)
    monkeypatch.setattr(v4, "_log_page_decision", lambda decision: None)

    token = shared._ACTIVE.set(state)
    try:
        processed = shared_v4.preprocess_pdf_geometry_opencv_shared(
            pdf_bytes,
            expected_page_count=1,
        )
    finally:
        shared._ACTIVE.reset(token)

    assert processed.page_count == 1
    assert processed.changed_page_count == 0
    assert processed.pages[0].route == "color_critical_no_op"
    assert state["metrics"]["ordinary_structure_cache_hits"] == 1
    assert state["metrics"]["ordinary_color_cache_hits"] == 1
    assert state["metrics"]["ordinary_geometry_cache_hits"] == 1


def test_chunk_offset_maps_provider_page_to_original_page(tmp_path, monkeypatch) -> None:
    provider_map = [
        {"original_page_number": 101 + index}
        for index in range(20)
    ]
    state = _shared_state(tmp_path, provider_map=provider_map)
    monkeypatch.setattr(shared, "_PAGE_OFFSET_DELEGATE", None)

    token = shared._ACTIVE.set(state)
    try:
        with shared.page_offset(16):
            assert shared.original_page_number(SimpleNamespace(number=0)) == 117
            assert shared.original_page_number(SimpleNamespace(number=3)) == 120
    finally:
        shared._ACTIVE.reset(token)


def test_missing_geometry_scratch_forces_authoritative_fallback(tmp_path) -> None:
    page_number = 9
    state = _shared_state(tmp_path)
    state["pages"][page_number] = {
        "geometry_completed": True,
        "geometry_path": str(tmp_path / "missing.npy"),
        "geometry_diag": v4._GeometryDiagnostic(
            perspective_applied=False,
            perspective_confidence=0.0,
            perspective_distortion=0.0,
            deskew_applied=False,
            deskew_angle_degrees=0.0,
            deskew_confidence=0.0,
            residual_angle_degrees=0.0,
            residual_confidence=0.0,
        ),
        "geometry_accepted": True,
        "geometry_reason": "accepted",
        "geometry_gate": {"quality": "ok"},
    }

    token = shared._ACTIVE.set(state)
    try:
        assert shared.cached_geometry_for_ordinary(page_number) is None
    finally:
        shared._ACTIVE.reset(token)

    assert "ordinary_geometry_cache_hits" not in state["metrics"]
