from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import fitz  # type: ignore[import]
import numpy as np
import pytest

from app.processing import pdf_opencv_quality_pipeline as v4
from app.processing import s0_v5_phase1_shared_cache as shared
from app.processing import s0_v5_phase1_shared_v4 as shared_v4


def _shared_state(tmp_path, *, provider_map=None):
    return {
        "scratch_root": tmp_path,
        "pages": {},
        "provider_map": list(provider_map or []),
        "metrics": {},
    }


def _geometry_dict(*, accepted: bool = True, v4_accepted: bool | None = None):
    return {
        "accepted": accepted,
        "v4_geometry_accepted": (
            accepted if v4_accepted is None else bool(v4_accepted)
        ),
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


def _diagnostic() -> v4._GeometryDiagnostic:
    return v4._GeometryDiagnostic(
        perspective_applied=False,
        perspective_confidence=0.0,
        perspective_distortion=0.0,
        deskew_applied=False,
        deskew_angle_degrees=0.0,
        deskew_confidence=0.0,
        residual_angle_degrees=0.0,
        residual_confidence=0.0,
    )


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


def test_analysis_image_populates_evidence_and_reuses_same_page_120_render(
    tmp_path,
    monkeypatch,
) -> None:
    document = fitz.open()
    page = document.new_page(width=72, height=96)
    analysis = np.full((24, 18, 3), 211, dtype=np.uint8)
    calls = {"analysis": 0, "render": 0}

    def analysis_delegate(_page):
        calls["analysis"] += 1
        return analysis

    def render_delegate(*args, **kwargs):
        calls["render"] += 1
        raise AssertionError("same-page 120 render should hit the shared cache")

    monkeypatch.setattr(shared, "_ANALYSIS_DELEGATE", analysis_delegate)
    monkeypatch.setattr(shared, "_RENDER_DELEGATE", render_delegate)
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

    state = _shared_state(tmp_path)
    token = shared._ACTIVE.set(state)
    try:
        first = shared.analysis_image(page)
        second = shared.render_page_bgr(page, dpi=120)
    finally:
        shared._ACTIVE.reset(token)
        document.close()

    assert first is analysis
    assert second is analysis
    assert calls == {"analysis": 1, "render": 0}
    assert state["metrics"]["analysis_pages"] == 1
    assert state["metrics"]["analysis_render_cache_hits"] == 1
    assert state["pages"][1]["structure"].born_digital is False
    assert state["pages"][1]["color"].color_critical is False


def test_geometry_delegate_is_computed_once_and_reused_from_lossless_scratch(
    tmp_path,
    monkeypatch,
) -> None:
    document = fitz.open()
    page = document.new_page(width=72, height=96)
    image = np.full((24, 16, 3), 217, dtype=np.uint8)
    calls = {"geometry": 0}

    def geometry_delegate(_page):
        calls["geometry"] += 1
        return image.copy(), _geometry_dict(accepted=True)

    monkeypatch.setattr(shared, "_GEOMETRY_DELEGATE", geometry_delegate)
    state = _shared_state(tmp_path)
    token = shared._ACTIVE.set(state)
    try:
        first_image, first_geometry = shared.geometry_only_page(page)
        second_image, second_geometry = shared.geometry_only_page(page)
    finally:
        shared._ACTIVE.reset(token)
        document.close()

    assert calls["geometry"] == 1
    assert first_geometry == second_geometry
    assert np.array_equal(first_image, image)
    assert np.array_equal(second_image, image)
    assert state["metrics"]["geometry_computed"] == 1
    assert state["metrics"]["presentation_geometry_cache_hits"] == 1
    cached = state["pages"][1]
    assert cached["geometry_completed"] is True
    assert cached["geometry_variant"] == "base"
    assert str(cached["ordinary_geometry_path"]).endswith(
        "page-000001-geometry-selected.npy"
    )
    assert cached["presentation_geometry_path"] == cached["ordinary_geometry_path"]


def test_oriented_geometry_keeps_v4_acceptance_separate_from_orientation(
    tmp_path,
    monkeypatch,
) -> None:
    document = fitz.open()
    page = document.new_page(width=72, height=96)
    oriented = np.full((30, 20, 3), 199, dtype=np.uint8)
    orientation = SimpleNamespace(correction_degrees=90)
    calls = {"geometry": 0}

    def oriented_delegate(_page, _orientation):
        calls["geometry"] += 1
        return (
            oriented,
            _geometry_dict(accepted=True, v4_accepted=False),
            oriented,
        )

    monkeypatch.setattr(shared, "_ORIENTED_GEOMETRY_DELEGATE", oriented_delegate)
    state = _shared_state(tmp_path)
    token = shared._ACTIVE.set(state)
    try:
        first = shared.oriented_geometry(page, orientation)
        second = shared.oriented_geometry(page, orientation)
        ordinary = shared.cached_geometry_for_ordinary(
            1,
            provider_input_mode="orientation_corrected_raster",
        )
    finally:
        shared._ACTIVE.reset(token)
        document.close()

    assert calls["geometry"] == 1
    assert first[1] == second[1]
    assert np.array_equal(first[0], oriented)
    assert np.array_equal(second[0], oriented)
    assert np.array_equal(second[2], oriented)
    assert ordinary is not None
    assert ordinary[2] is False
    assert np.array_equal(ordinary[0], oriented)


def test_shared_v4_reuses_pdf_structure_color_and_geometry_without_second_render(
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
        provider_map=[
            {
                "original_page_number": page_number,
                "provider_input_mode": "pdf_page",
            }
        ],
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
        "ordinary_geometry_path": str(geometry_path),
        "geometry_diag": _diagnostic(),
        "ordinary_geometry_accepted": False,
        "ordinary_geometry_reason": "no_change",
        "ordinary_geometry_gate": {"quality": "ok"},
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


def test_orientation_raster_does_not_reuse_original_pdf_structure(
    tmp_path,
    monkeypatch,
) -> None:
    source = fitz.open()
    source.new_page(width=72, height=96)
    pdf_bytes = source.tobytes(garbage=4, deflate=True)
    source.close()

    page_number = 8
    geometry_image = np.full((32, 24, 3), 230, dtype=np.uint8)
    geometry_path = tmp_path / "page-000008-geometry-selected.npy"
    np.save(geometry_path, geometry_image, allow_pickle=False)
    state = _shared_state(
        tmp_path,
        provider_map=[
            {
                "original_page_number": page_number,
                "provider_input_mode": "orientation_corrected_raster",
            }
        ],
    )
    state["pages"][page_number] = {
        # Reusing this would incorrectly make the raster provider page a born-
        # digital no-op.  The shared V4 coordinator must inspect the raster.
        "structure": v4._PageStructure(
            text_chars=500,
            max_image_coverage=0.0,
            born_digital=True,
        ),
        "color": v4._ColorFeatures(
            high_saturation_ratio=0.2,
            largest_saturated_component_ratio=0.1,
            saturation_p90=90.0,
            color_critical=True,
        ),
        "geometry_completed": True,
        "ordinary_geometry_path": str(geometry_path),
        "geometry_diag": _diagnostic(),
        "ordinary_geometry_accepted": False,
        "ordinary_geometry_reason": "no_change",
        "ordinary_geometry_gate": {"quality": "ok"},
    }
    inspect_calls = {"count": 0}

    def inspect(_page):
        inspect_calls["count"] += 1
        return v4._PageStructure(
            text_chars=0,
            max_image_coverage=1.0,
            born_digital=False,
        )

    monkeypatch.setattr(v4, "_inspect_page_structure", inspect)
    monkeypatch.setattr(v4, "_log_page_decision", lambda decision: None)

    token = shared._ACTIVE.set(state)
    try:
        processed = shared_v4.preprocess_pdf_geometry_opencv_shared(
            pdf_bytes,
            expected_page_count=1,
        )
    finally:
        shared._ACTIVE.reset(token)

    assert inspect_calls["count"] == 1
    assert processed.pages[0].route == "color_critical_no_op"
    assert "ordinary_structure_cache_hits" not in state["metrics"]
    assert state["metrics"]["ordinary_color_cache_hits"] == 1
    assert state["metrics"]["ordinary_geometry_cache_hits"] == 1


def test_chunk_offset_maps_provider_page_to_original_page(tmp_path, monkeypatch) -> None:
    provider_map = [
        {
            "original_page_number": 101 + index,
            "provider_input_mode": "pdf_page",
        }
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
        "ordinary_geometry_path": str(tmp_path / "missing.npy"),
        "geometry_diag": _diagnostic(),
        "ordinary_geometry_accepted": True,
        "ordinary_geometry_reason": "accepted",
        "ordinary_geometry_gate": {"quality": "ok"},
    }

    token = shared._ACTIVE.set(state)
    try:
        assert (
            shared.cached_geometry_for_ordinary(
                page_number,
                provider_input_mode="pdf_page",
            )
            is None
        )
    finally:
        shared._ACTIVE.reset(token)

    assert "ordinary_geometry_cache_hits" not in state["metrics"]


def test_native_fallback_mode_never_reuses_original_geometry(tmp_path) -> None:
    page_number = 10
    geometry_path = tmp_path / "page-000010-geometry-selected.npy"
    np.save(geometry_path, np.zeros((4, 4, 3), dtype=np.uint8), allow_pickle=False)
    state = _shared_state(tmp_path)
    state["pages"][page_number] = {
        "geometry_completed": True,
        "ordinary_geometry_path": str(geometry_path),
        "geometry_diag": _diagnostic(),
        "ordinary_geometry_accepted": True,
        "ordinary_geometry_reason": "accepted",
        "ordinary_geometry_gate": {"quality": "ok"},
    }

    token = shared._ACTIVE.set(state)
    try:
        assert (
            shared.cached_geometry_for_ordinary(
                page_number,
                provider_input_mode="native_text_fallback_raster",
            )
            is None
        )
    finally:
        shared._ACTIVE.reset(token)


def test_phase1_installer_never_replaces_classifier_pipeline() -> None:
    source = Path(
        "app/processing/s0_v5_phase1_shared_analysis_compat.py"
    ).read_text(encoding="utf-8")
    assert "_classify_source_pages =" not in source
    assert "s0_v5_phase1_shared_classification" not in source
