"""Install Staging-only S0 v5 Phase 1 shared analysis beneath Phase 0 profiling."""
from __future__ import annotations

import threading

from app.processing import s0_v5_phase1_shared_cache as shared
from app.processing import s0_v5_phase1_shared_classification as classification
from app.processing import s0_v5_phase1_shared_v4 as shared_v4


_INSTALL_LOCK = threading.Lock()
_INSTALLED = False


def install_s0_v5_phase1_shared_analysis() -> None:
    """Share classification/V4 evidence without changing classifier or v4 gates."""
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return

        from app.processing import pdf_geometry_integration as integration
        from app.processing import pdf_opencv_quality_pipeline as v4
        from app.processing import pdf_page_presentation_bridge as bridge
        from app.processing import pdf_page_presentation_preprocess_compat as presentation
        from app.processing import pdf_s0_bounded_v4_output_compat as bounded

        base_v4 = bounded._BASE_PREPROCESSOR
        if base_v4 is None:
            raise RuntimeError(
                "S0 v5 Phase 1 requires bounded V4 output compatibility first"
            )

        shared.configure(
            geometry_delegate=bridge._geometry_only_page,
            render_delegate=v4._render_page_bgr,
            build_ordinary_delegate=presentation._build_ordinary_source,
            page_offset_delegate=bounded._page_offset,
        )
        shared_v4.configure(base_delegate=base_v4)

        # Install beneath Phase 0. The Phase 0 installer runs after this module
        # and therefore times the actual shared functions/render calls rather
        # than the pre-Phase1 delegates.
        v4._render_page_bgr = shared.render_page_bgr
        bridge._geometry_only_page = shared.geometry_only_page
        presentation._classify_source_pages = classification.classify_source_pages
        presentation._build_ordinary_source = shared.build_ordinary_source
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
            classifier_contract="unchanged",
            v4_quality_gates="unchanged",
        )


__all__ = ["install_s0_v5_phase1_shared_analysis"]
