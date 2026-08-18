from __future__ import annotations

from types import SimpleNamespace

from app.processing import s0_v5_phase0_observability_compat as phase0
from app.processing.s0_v5_shadow_planner import CheapPageObservation
from scripts.apply_s0_v5_phase0_observability import (
    patch_s0_v5_phase0_observability,
)


def _shadow_observation(page_number: int = 7) -> CheapPageObservation:
    return CheapPageObservation(
        page_number=page_number,
        born_digital=False,
        embedded_image_count=1,
        maximum_embedded_image_coverage=1.0,
        single_full_page_raster=True,
        native_raster_width_pixels=701,
        native_raster_height_pixels=1084,
        native_raster_xdpi=150.0,
        native_raster_ydpi=150.0,
        near_white_ratio=0.2,
        border_near_white_ratio=0.3,
        largest_border_connected_near_white_ratio=0.2,
        background_std=12.0,
        background_range=35.0,
        dark_ratio=0.01,
        high_saturation_ratio=0.0,
        color_critical=False,
        estimated_skew_degrees=0.0,
        estimated_skew_confidence=0.0,
        perspective_coverage=0.0,
        perspective_distortion=0.0,
        clean_white=False,
        background_suspect=True,
        geometry_suspect=False,
    )


def test_timing_wrapper_preserves_delegate_return_identity() -> None:
    sentinel = object()
    state = phase0._new_state()
    token = phase0._ACTIVE_PROFILE.set(state)
    try:
        wrapped = phase0._stage_wrapper(
            lambda: sentinel,
            stage="unit_stage_ms",
        )
        result = wrapped()
    finally:
        phase0._ACTIVE_PROFILE.reset(token)

    assert result is sentinel
    assert state["stage_counts"] == {"unit_stage_ms": 1}
    assert state["stage_ms"]["unit_stage_ms"] >= 0.0


def test_shadow_feature_probe_returns_exact_delegate_features(monkeypatch) -> None:
    features = {
        "native_text_chars": 0,
        "maximum_embedded_image_coverage": 1.0,
        "pdf_rotation_metadata": 0,
    }
    bridge = SimpleNamespace(_combined_features=lambda page, image: features)
    monkeypatch.setattr(
        phase0.shadow,
        "observe_page",
        lambda **kwargs: _shadow_observation(7),
    )
    phase0._install_shadow_feature_probe(bridge)
    state = phase0._new_state()
    token = phase0._ACTIVE_PROFILE.set(state)
    try:
        result = bridge._combined_features(object(), object())
    finally:
        phase0._ACTIVE_PROFILE.reset(token)

    assert result is features
    assert state["observations"][7] == _shadow_observation(7)
    assert state["shadow_observation_failures"] == 0


def test_shadow_feature_failure_fails_open_to_original_features(monkeypatch) -> None:
    features = {"native_text_chars": 123}
    bridge = SimpleNamespace(_combined_features=lambda page, image: features)

    def fail(**kwargs):
        raise RuntimeError("shadow-only failure")

    monkeypatch.setattr(phase0.shadow, "observe_page", fail)
    monkeypatch.setattr(phase0.profile, "emit_profile", lambda *args, **kwargs: None)
    phase0._install_shadow_feature_probe(bridge)
    state = phase0._new_state()
    token = phase0._ACTIVE_PROFILE.set(state)
    try:
        result = bridge._combined_features(object(), object())
    finally:
        phase0._ACTIVE_PROFILE.reset(token)

    assert result is features
    assert state["observations"] == {}
    assert state["shadow_observation_failures"] == 1


def test_top_level_shadow_finalize_failure_cannot_replace_delegate_result(monkeypatch) -> None:
    sentinel = object()
    integration = SimpleNamespace(prepare_geometry_provider_input=lambda **kwargs: sentinel)
    monkeypatch.setattr(phase0.profile, "emit_profile", lambda *args, **kwargs: None)

    def fail_finalize(**kwargs):
        raise RuntimeError("profile finalize failed")

    monkeypatch.setattr(phase0, "_finalize_success", fail_finalize)
    phase0._install_top_level_wrapper(integration)

    result = integration.prepare_geometry_provider_input(example=True)

    assert result is sentinel
    assert phase0._ACTIVE_PROFILE.get() is None


def test_top_level_delegate_failure_is_preserved(monkeypatch) -> None:
    original = ValueError("authoritative delegate failure")

    def fail(**kwargs):
        raise original

    integration = SimpleNamespace(prepare_geometry_provider_input=fail)
    monkeypatch.setattr(phase0.profile, "emit_profile", lambda *args, **kwargs: None)
    phase0._install_top_level_wrapper(integration)

    try:
        integration.prepare_geometry_provider_input(example=True)
    except ValueError as exc:
        assert exc is original
    else:
        raise AssertionError("delegate exception was not preserved")
    assert phase0._ACTIVE_PROFILE.get() is None


def test_apply_script_inserts_phase0_after_prior_overlay_block(tmp_path) -> None:
    path = tmp_path / "pdf_ingestion.py"
    path.write_text(
        "from app.config import settings\n"
        "from app.processing.some_overlay import install_overlay\n\n"
        "install_overlay()\n\n"
        "from app.database import SessionLocal\n"
        "from app.models import Document\n",
        encoding="utf-8",
    )

    patch_s0_v5_phase0_observability(path)
    once = path.read_text(encoding="utf-8")
    patch_s0_v5_phase0_observability(path)
    twice = path.read_text(encoding="utf-8")

    assert once == twice
    assert once.count("install_s0_v5_cheap_shadow_geometry()") == 1
    assert once.count("install_s0_v5_phase0_observability()") == 1
    assert once.index("install_overlay()") < once.index(
        "install_s0_v5_cheap_shadow_geometry()"
    )
    assert once.index("install_s0_v5_cheap_shadow_geometry()") < once.index(
        "install_s0_v5_phase0_observability()"
    )
    assert once.index("install_s0_v5_phase0_observability()") < once.index(
        "from app.database import SessionLocal"
    )
