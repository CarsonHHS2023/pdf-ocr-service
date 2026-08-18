"""Shared classification pass for S0 v5 Phase 1."""
from __future__ import annotations

import fitz  # type: ignore[import]
import numpy as np

from app.processing import s0_v5_phase1_shared_cache as shared


def classify_source_pages(source: fitz.Document) -> list[dict[str, object]]:
    """Preserve current classifier inputs while retaining reusable V4 evidence."""
    from app.processing import pdf_opencv_quality_pipeline as v4
    from app.processing import pdf_page_presentation_bridge as bridge
    from app.processing import pdf_page_presentation_preprocess_compat as presentation

    decisions: list[dict[str, object]] = []
    page_count = source.page_count
    presentation._set_s0_work_phase("presentation_classification", page_count)

    for page_index in range(page_count):
        page_number = page_index + 1
        source_unit_id = bridge._source_unit_id(page_number)
        page = source[page_index]

        # One shared low-resolution render. The exact same image is used for
        # presentation features, V4 color evidence, and rejected-geometry
        # classifier input.
        analysis_image = bridge._analysis_image(page)
        structure = v4._inspect_page_structure(page)
        color = v4._color_features(analysis_image)
        shared.store_analysis(
            page_number,
            structure=structure,
            color=color,
        )

        features = bridge._combined_features(page, analysis_image)
        candidate, candidate_reasons = bridge._is_candidate(
            features,
            first_page=page_index == 0,
            last_page=page_index == page_count - 1,
        )
        bridge._diagnostic(
            "PDF_PAGE_CLASSIFICATION_CANDIDATE",
            source_unit_id=source_unit_id,
            candidate=candidate,
            reason_count=len(candidate_reasons),
        )

        classification = bridge._fallback_classification(
            source_unit_id,
            "not_selected_for_multimodal_review",
        )
        geometry: dict[str, object] = {}
        geometry_image: np.ndarray | None = None
        if candidate:
            # The installed geometry delegate stays authoritative. The Phase 1
            # wrapper captures its one 300-DPI source render and selected result.
            geometry_image, geometry = bridge._geometry_only_page(page)
            classification_image = (
                geometry_image if geometry_image is not None else analysis_image
            )
            try:
                classification = bridge._classify(
                    bridge._encode_png(classification_image),
                    features,
                    {
                        "source_unit_id": source_unit_id,
                        "page_number": page_number,
                        "page_index": page_index,
                        "page_count": page_count,
                        "is_first_physical_page": page_index == 0,
                        "is_last_physical_page": page_index == page_count - 1,
                        "page_width_points": float(page.rect.width),
                        "page_height_points": float(page.rect.height),
                        "candidate_reasons": list(candidate_reasons),
                    },
                )
            except Exception as exc:
                classification = bridge._fallback_classification(
                    source_unit_id,
                    f"classification_failed:{type(exc).__name__}",
                )
                bridge._diagnostic(
                    "PDF_PAGE_CLASSIFICATION_FALLBACK_TO_OCR",
                    source_unit_id=source_unit_id,
                    reason=type(exc).__name__,
                )
            finally:
                classification_image = None
                geometry_image = None

            skip_ocr, decision_reason = bridge._skip_ocr_decision(
                classification,
                features,
            )
        else:
            skip_ocr = False
            decision_reason = "not_a_local_candidate"

        classification = {
            **classification,
            "candidate_features": bridge._json_clone(features),
            "candidate_reasons": list(candidate_reasons),
            "skip_ocr": skip_ocr,
            "decision_reason": decision_reason,
        }
        bridge._diagnostic(
            "PDF_PAGE_CLASSIFICATION_RESULT",
            source_unit_id=source_unit_id,
            page_role=classification["page_role"],
            confidence=classification["confidence"],
            skip_ocr=skip_ocr,
            image_detail=classification["image_detail"],
            cache_hit=classification["cache_hit"],
            input_tokens=classification["input_tokens"],
            output_tokens=classification["output_tokens"],
        )
        if (
            candidate
            and not skip_ocr
            and classification["page_role"] in bridge.PRESENTATION_PAGE_ROLES
        ):
            bridge._diagnostic(
                "PDF_PAGE_CLASSIFICATION_FALLBACK_TO_OCR",
                source_unit_id=source_unit_id,
                reason=decision_reason,
            )

        decisions.append(
            {
                "page_index": page_index,
                "page_number": page_number,
                "source_unit_id": source_unit_id,
                "features": features,
                "candidate": candidate,
                "candidate_reasons": candidate_reasons,
                "classification": classification,
                "skip_ocr": skip_ocr,
                "decision_reason": decision_reason,
                "geometry": geometry,
                "page_width_points": float(page.rect.width),
                "page_height_points": float(page.rect.height),
            }
        )
        analysis_image = None
        presentation._mark_s0_work_page_completed(
            page_number=page_number,
            page_count=page_count,
            route="presentation_classification",
        )

    return decisions


__all__ = ["classify_source_pages"]
