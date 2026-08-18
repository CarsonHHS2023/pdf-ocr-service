"""Install Staging-only S0 v5 Phase 1 low-level shared analysis.

Phase 1 is intentionally installed after Phase 0 profiling.  It captures the
Phase-0-wrapped expensive delegates, then adds cache checks outside them.  Real
cache misses remain timed/countable by Phase 0; cache hits skip those delegates.
The already-composed classifier/native/orientation/fail-open chain is untouched.
"""
from __future__ import annotations

import threading

from app.processing import s0_v5_phase1_shared_cache as shared
from app.processing import s0_v5_phase1_shared_v4 as shared_v4


_INSTALL_LOCK = threading.Lock()
_INSTALLED = False


def install_s0_v5_phase1_shared_analysis() -> None:
    """Share low-level page evidence without replacing classification policy."""
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return

        from app.processing import pdf_geometry_integration as integration
        from app.processing import pdf_native_text_compat as native
        from app.processing import pdf_opencv_quality_pipeline as v4
        from app.processing import pdf_page_orientation_compat as orientation
        from app.processing import pdf_page_presentation_bridge as bridge
        from app.processing import pdf_page_presentation_preprocess_compat as presentation
        from app.processing import pdf_s0_bounded_v4_output_compat as bounded

        base_v4 = bounded._BASE_PREPROCESSOR
        if base_v4 is None:
            raise RuntimeError(
                "S0 v5 Phase 1 requires bounded V4 output compatibility first"
            )

        # Capture the fully composed, Phase-0-profiled delegates exactly as they
        # exist at this installation point.  No classifier wrapper is replaced.
        shared.configure(
            analysis_delegate=bridge._analysis_image,
            geometry_delegate=bridge._geometry_only_page,
            oriented_geometry_delegate=orientation._oriented_geometry,
            orientation_image_delegate=orientation._orientation_image_from_decision,
            render_delegate=v4._render_page_bgr,
            gate_delegate=v4._gate_geometry_candidate,
            build_ordinary_delegate=presentation._build_ordinary_source,
            page_offset_delegate=bounded._page_offset,
        )
        shared_v4.configure(base_delegate=base_v4)

        bridge._analysis_image = shared.analysis_image
        v4._render_page_bgr = shared.render_page_bgr
        v4._gate_geometry_candidate = shared.gate_geometry_candidate
        bridge._geometry_only_page = shared.geometry_only_page
        orientation._oriented_geometry = shared.oriented_geometry
        orientation._orientation_image_from_decision = (
            shared.orientation_image_from_decision
        )
        presentation._build_ordinary_source = shared.build_ordinary_source
        # Bounded-memory/native composition keeps this alias and may call it
        # directly.  Point it at the same authoritative-builder wrapper.
        native._build_ordinary_source_with_native = shared.build_ordinary_source
        bounded._page_offset = shared.page_offset
        bounded._BASE_PREPROCESSOR = shared_v4.preprocess_pdf_geometry_opencv_shared

        current = integration.prepare_geometry_provider_input
        wrapped = shared.wrap_top_level(current)
        integration.prepare_geometry_provider_input = wrapped
        bridge.prepare_presentation_provider_input = wrapped
        presentation.prepare_presentation_provider_input_v2 = wrapped

        _INSTALLED = True
        shared.diagnostic(
            "PDF_S0_V5_PHASE1_SHARED_ANALYSIS_INSTALLED",
            scratch_mode="run_local_temporary",
            classifier_contract="authoritative_chain_untouched",
            phase0_delegate_accounting="cache_misses_only",
            v4_quality_gates="unchanged",
        )


__all__ = ["install_s0_v5_phase1_shared_analysis"]
