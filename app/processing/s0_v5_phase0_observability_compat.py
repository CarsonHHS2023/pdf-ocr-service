"""Staging-only Phase 0 profiling and S0 v5 shadow-planner overlay.

This compatibility layer is deliberately observational.  It wraps the already
installed staging S0 path after all existing compatibility layers are active,
records stage timings, and runs the S0 v5 planner in shadow mode from the
existing 120-DPI analysis image.  The delegate's provider input, PDF bytes,
page routes, and quality-gate decisions are returned unchanged.
"""
from __future__ import annotations

from collections import Counter
from contextvars import ContextVar
import logging
from time import perf_counter
import threading
from typing import Any, Callable, Mapping

from app.processing import s0_v5_observability as profile
from app.processing import s0_v5_shadow_planner as shadow


_logger = logging.getLogger("uvicorn.error")
_ACTIVE_PROFILE: ContextVar[dict[str, object] | None] = ContextVar(
    "atlas_s0_v5_phase0_profile", default=None
)
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False


def _active() -> dict[str, object] | None:
    value = _ACTIVE_PROFILE.get()
    return value if isinstance(value, dict) else None


def _new_state() -> dict[str, object]:
    return {
        "stage_ms": {},
        "stage_counts": {},
        "page_stage_ms": {},
        "page_stage_counts": {},
        "observations": {},
        "page_profiles_emitted": set(),
        "shadow_observation_ms": 0.0,
        "shadow_observation_failures": 0,
    }


def _current_page_number() -> int | None:
    identity = profile.active_identity()
    raw = identity.get("page_number")
    return int(raw) if isinstance(raw, int) and raw > 0 else None


def _record_timing(stage: str, elapsed: float, *, page_number: int | None = None) -> None:
    state = _active()
    if state is None:
        return
    milliseconds = round(max(0.0, float(elapsed) * 1000.0), 3)
    stage_ms = state.get("stage_ms")
    stage_counts = state.get("stage_counts")
    if not isinstance(stage_ms, dict) or not isinstance(stage_counts, dict):
        return
    stage_ms[stage] = round(float(stage_ms.get(stage, 0.0)) + milliseconds, 3)
    stage_counts[stage] = int(stage_counts.get(stage, 0)) + 1

    resolved_page = page_number or _current_page_number()
    if resolved_page is None:
        return
    page_stage_ms = state.get("page_stage_ms")
    page_stage_counts = state.get("page_stage_counts")
    if not isinstance(page_stage_ms, dict) or not isinstance(page_stage_counts, dict):
        return
    page_ms = page_stage_ms.setdefault(resolved_page, {})
    page_counts = page_stage_counts.setdefault(resolved_page, {})
    if isinstance(page_ms, dict) and isinstance(page_counts, dict):
        page_ms[stage] = round(float(page_ms.get(stage, 0.0)) + milliseconds, 3)
        page_counts[stage] = int(page_counts.get(stage, 0)) + 1


def _stage_wrapper(
    delegate: Callable[..., Any],
    *,
    stage: str,
    dynamic_render: bool = False,
) -> Callable[..., Any]:
    if getattr(delegate, "__atlas_s0_v5_phase0_timing__", False):
        return delegate

    def wrapped(*args: object, **kwargs: object):
        resolved_stage = stage
        if dynamic_render:
            dpi = kwargs.get("dpi")
            if dpi is None and len(args) > 1:
                dpi = args[1]
            if dpi == 120:
                resolved_stage = "render_120_ms"
            elif dpi == 300:
                resolved_stage = "render_300_ms"
            elif dpi == 150:
                resolved_stage = "render_150_diagnostics_ms"
            else:
                resolved_stage = f"render_{dpi}_ms"[:64]
        started = perf_counter()
        try:
            return delegate(*args, **kwargs)
        finally:
            _record_timing(resolved_stage, perf_counter() - started)

    setattr(wrapped, "__atlas_s0_v5_phase0_timing__", True)
    setattr(wrapped, "__atlas_s0_v5_phase0_delegate__", delegate)
    return wrapped


def _install_timed_function(module: object, name: str, stage: str, *, dynamic_render: bool = False) -> None:
    current = getattr(module, name)
    if getattr(current, "__atlas_s0_v5_phase0_timing__", False):
        return
    setattr(
        module,
        name,
        _stage_wrapper(current, stage=stage, dynamic_render=dynamic_render),
    )


def _install_shadow_feature_probe(bridge: object) -> None:
    current = bridge._combined_features
    if getattr(current, "__atlas_s0_v5_shadow_features__", False):
        return

    def wrapped(page: object, analysis_image: object):
        features = current(page, analysis_image)
        state = _active()
        if state is None:
            return features
        started = perf_counter()
        try:
            observation = shadow.observe_page(
                page=page,
                analysis_image=analysis_image,
                native_features=features,
            )
            observations = state.get("observations")
            if isinstance(observations, dict):
                observations[observation.page_number] = observation
        except Exception as exc:
            state["shadow_observation_failures"] = int(
                state.get("shadow_observation_failures") or 0
            ) + 1
            profile.emit_profile(
                "shadow_page_observation_failed",
                error_type=type(exc).__name__,
            )
        finally:
            elapsed = max(0.0, (perf_counter() - started) * 1000.0)
            state["shadow_observation_ms"] = round(
                float(state.get("shadow_observation_ms") or 0.0) + elapsed,
                3,
            )
        # Critical Phase 0 invariant: classifier/provider code receives the exact
        # delegate object, with no shadow-only fields injected into it.
        return features

    setattr(wrapped, "__atlas_s0_v5_shadow_features__", True)
    setattr(wrapped, "__atlas_s0_v5_phase0_delegate__", current)
    bridge._combined_features = wrapped


def _install_page_profile_probe(v4: object) -> None:
    current = v4._log_page_decision
    if getattr(current, "__atlas_s0_v5_page_profile__", False):
        return

    def wrapped(decision: dict[str, object]) -> None:
        current(decision)
        state = _active()
        if state is None:
            return
        try:
            page_number = _current_page_number()
            if page_number is None:
                raw = decision.get("page_number")
                page_number = int(raw) if isinstance(raw, int) and raw > 0 else None
            if page_number is None:
                return
            emitted = state.get("page_profiles_emitted")
            if not isinstance(emitted, set) or page_number in emitted:
                return
            emitted.add(page_number)
            page_stage_ms = state.get("page_stage_ms")
            page_stage_counts = state.get("page_stage_counts")
            ms = (
                dict(page_stage_ms.get(page_number, {}))
                if isinstance(page_stage_ms, dict)
                and isinstance(page_stage_ms.get(page_number), dict)
                else {}
            )
            counts = (
                dict(page_stage_counts.get(page_number, {}))
                if isinstance(page_stage_counts, dict)
                and isinstance(page_stage_counts.get(page_number), dict)
                else {}
            )
            profile.emit_profile(
                "legacy_page_complete",
                page_number=page_number,
                route=str(decision.get("route") or "unknown"),
                selected=str(decision.get("selected") or "unknown"),
                stage_ms=ms,
                stage_counts=counts,
            )
        except Exception:
            _logger.exception("S0 Phase 0 page profile failed open")

    setattr(wrapped, "__atlas_s0_v5_page_profile__", True)
    setattr(wrapped, "__atlas_s0_v5_phase0_delegate__", current)
    v4._log_page_decision = wrapped


def _actual_page_map(result: object) -> dict[int, Mapping[str, object]]:
    manifest = getattr(result, "presentation_manifest", None)
    if not isinstance(manifest, Mapping):
        return {}
    pages = manifest.get("pages")
    if not isinstance(pages, list):
        return {}
    mapped: dict[int, Mapping[str, object]] = {}
    for item in pages:
        if not isinstance(item, Mapping):
            continue
        raw = item.get("page_number")
        if isinstance(raw, int) and raw > 0:
            mapped[int(raw)] = item
    return mapped


def _persist_summary_scalars(
    *,
    summary: Mapping[str, object],
    stage_counts: Mapping[str, object],
    total_s0_ms: float,
) -> None:
    try:
        from app.processing import s0_pdf_resource_heartbeat as heartbeat

        state = heartbeat._active_state()
        if not isinstance(state, dict):
            return
        heartbeat.record_pdf_processing_heartbeat(
            processing_run_id=str(state["processing_run_id"]),
            document_id=str(state["document_id"]),
            phase="s0_v5_shadow_summary",
            page_count=int(state.get("document_page_count") or state.get("page_count") or 0),
            total_s0_ms=round(total_s0_ms, 3),
            shadow_false_negative_count=int(
                summary.get("false_negative_passthrough_count") or 0
            ),
            shadow_route_miss_count=int(summary.get("route_miss_count") or 0),
            shadow_unnecessary_escalation_count=int(
                summary.get("unnecessary_escalation_count") or 0
            ),
            render_120_count=int(stage_counts.get("render_120_ms") or 0),
            render_300_count=int(stage_counts.get("render_300_ms") or 0),
        )
    except Exception:
        _logger.exception("S0 Phase 0 durable summary failed open")


def _finalize_success(
    *,
    result: object,
    state: dict[str, object],
    total_s0_ms: float,
) -> None:
    started = perf_counter()
    observations_raw = state.get("observations")
    observations = (
        dict(observations_raw) if isinstance(observations_raw, dict) else {}
    )
    ordered_observations = [observations[key] for key in sorted(observations)]
    document_profile = shadow.build_document_profile(ordered_observations)
    actual_pages = _actual_page_map(result)
    route_counts: Counter[str] = Counter()
    native_raster_candidates = 0
    rows: list[dict[str, object]] = []
    miss_pages: list[int] = []

    for observation in ordered_observations:
        plan = shadow.plan_page(observation, document_profile)
        route_counts[plan.route] += 1
        native_raster_candidates += int(plan.native_raster_candidate)
        comparison = shadow.compare_plan_to_actual(
            plan,
            actual_pages.get(plan.page_number),
        )
        row = {
            "page_number": plan.page_number,
            "shadow_route": plan.route,
            "native_raster_candidate": plan.native_raster_candidate,
            **comparison,
        }
        rows.append(row)
        if comparison.get("route_miss") is True:
            miss_pages.append(plan.page_number)

    comparison_summary = shadow.summarize_shadow_results(rows)
    stage_ms_raw = state.get("stage_ms")
    stage_counts_raw = state.get("stage_counts")
    stage_ms = dict(stage_ms_raw) if isinstance(stage_ms_raw, dict) else {}
    stage_counts = (
        dict(stage_counts_raw) if isinstance(stage_counts_raw, dict) else {}
    )
    shadow_finalize_ms = round(
        max(0.0, (perf_counter() - started) * 1000.0), 3
    )
    preprocessing = getattr(result, "preprocessing", None)

    profile.emit_profile(
        "s0_phase0_summary",
        total_s0_ms=round(total_s0_ms, 3),
        stage_ms=stage_ms,
        stage_counts=stage_counts,
        changed_page_count=getattr(preprocessing, "changed_page_count", None),
        provider_input_size_bytes=getattr(result, "byte_size", None),
        document_profile=shadow.profile_dict(document_profile),
        shadow_route_counts=dict(sorted(route_counts.items())),
        native_raster_candidate_count=native_raster_candidates,
        shadow_comparison=comparison_summary,
        shadow_route_miss_pages=miss_pages[:32],
        shadow_observation_ms=state.get("shadow_observation_ms"),
        shadow_observation_failures=state.get("shadow_observation_failures"),
        shadow_finalize_ms=shadow_finalize_ms,
        note="delegate_output_unchanged",
    )
    _persist_summary_scalars(
        summary=comparison_summary,
        stage_counts=stage_counts,
        total_s0_ms=total_s0_ms,
    )


def _install_top_level_wrapper(integration: object) -> None:
    current = integration.prepare_geometry_provider_input
    if getattr(current, "__atlas_s0_v5_phase0_top_level__", False):
        return

    def wrapped(*args: object, **kwargs: object):
        state = _new_state()
        token = _ACTIVE_PROFILE.set(state)
        started = perf_counter()
        profile.emit_profile("s0_phase0_started")
        try:
            result = current(*args, **kwargs)
        except BaseException as exc:
            total_s0_ms = round(max(0.0, (perf_counter() - started) * 1000.0), 3)
            try:
                profile.emit_profile(
                    "s0_phase0_delegate_failed",
                    total_s0_ms=total_s0_ms,
                    error_type=type(exc).__name__,
                    stage_ms=state.get("stage_ms"),
                    stage_counts=state.get("stage_counts"),
                )
            except Exception:
                _logger.exception("S0 Phase 0 failure profile failed open")
            raise
        else:
            total_s0_ms = round(max(0.0, (perf_counter() - started) * 1000.0), 3)
            try:
                _finalize_success(
                    result=result,
                    state=state,
                    total_s0_ms=total_s0_ms,
                )
            except Exception:
                _logger.exception("S0 Phase 0 shadow finalize failed open")
            # Critical invariant: never replace, mutate, or reinterpret the
            # authoritative delegate result in Phase 0.
            return result
        finally:
            _ACTIVE_PROFILE.reset(token)

    setattr(wrapped, "__atlas_s0_v5_phase0_top_level__", True)
    setattr(wrapped, "__atlas_s0_v5_phase0_delegate__", current)
    integration.prepare_geometry_provider_input = wrapped


def install_s0_v5_phase0_observability() -> None:
    """Install profiling after all existing staging compatibility layers."""
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        from app.processing import pdf_geometry_integration as integration
        from app.processing import pdf_opencv_quality_pipeline as v4
        from app.processing import pdf_page_presentation_bridge as bridge
        from app.processing import pdf_page_presentation_preprocess_compat as presentation
        from app.processing import pdf_s0_bounded_v4_output_compat as bounded

        _install_timed_function(v4, "_inspect_page_structure", "inspect_structure_ms")
        _install_timed_function(v4, "_render_page_bgr", "render_ms", dynamic_render=True)
        _install_timed_function(v4, "_color_features", "color_analysis_ms")
        _install_timed_function(v4, "_build_geometry_candidate", "geometry_build_ms")
        _install_timed_function(v4, "_gate_geometry_candidate", "geometry_gate_ms")
        _install_timed_function(v4, "_normalize_background", "background_build_ms")
        _install_timed_function(v4, "_gate_background_candidate", "background_gate_ms")
        _install_timed_function(v4, "_insert_raster_page", "output_insert_ms")
        _install_timed_function(bounded, "_serialize_source_chunk", "chunk_serialize_ms")
        _install_timed_function(bounded, "_merge_processed_chunks", "chunk_merge_ms")
        _install_timed_function(presentation, "_build_ordinary_source", "ordinary_source_build_ms")
        _install_timed_function(
            presentation,
            "_build_full_render",
            "presentation_render_assembly_ms",
        )
        _install_shadow_feature_probe(bridge)
        _install_page_profile_probe(v4)
        _install_top_level_wrapper(integration)
        _INSTALLED = True
        profile.emit_profile(
            "s0_phase0_installed",
            shadow_planner_version=shadow.SHADOW_PLANNER_VERSION,
        )


__all__ = [
    "install_s0_v5_phase0_observability",
]
