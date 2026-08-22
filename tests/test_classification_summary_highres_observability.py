from __future__ import annotations

from types import SimpleNamespace

from app.processing import pdf_page_classification_observability_compat as classification_obs
from app.processing import pdf_page_presentation_bridge as bridge
from app.processing import pdf_page_presentation_preprocess_compat as preprocess


def _decision(
    page_number: int,
    *,
    decision_reason: str,
    skip_ocr: bool,
    native_text_accepted: bool = False,
    page_role: str = "body",
) -> dict[str, object]:
    return {
        "page_number": page_number,
        "source_unit_id": f"pdf-page:{page_number:06d}",
        "candidate": True,
        "classification": {
            "page_role": page_role,
            "confidence": 0.99,
            "provider": "openai",
            "model_id": "test-model",
            "cache_hit": False,
            "reason_codes": [],
        },
        "skip_ocr": skip_ocr,
        "native_text_accepted": native_text_accepted,
        "decision_reason": decision_reason,
    }


def _run_observed_classification(monkeypatch, decisions: list[dict[str, object]]):
    diagnostics: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY", "configured-test-key")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_OPENAI_MODEL", "test-model")
    monkeypatch.setattr(
        bridge,
        "_diagnostic",
        lambda event, **fields: diagnostics.append((event, fields)),
    )
    monkeypatch.setattr(preprocess, "_classify_source_pages", lambda source: decisions)
    monkeypatch.setattr(classification_obs, "_INSTALLED", False)

    classification_obs.install_page_classification_observability_compat()
    with classification_obs.page_classification_observation_context("attempt-summary-highres"):
        result = preprocess._classify_source_pages(SimpleNamespace())

    assert result is decisions
    return diagnostics


def test_high_resolution_presentation_summary_matches_real_routing_counts(monkeypatch) -> None:
    decisions = [
        _decision(
            1,
            decision_reason="presentation_page_high_resolution_confirmed",
            skip_ocr=True,
            page_role="cover",
        ),
        *[
            _decision(
                page_number,
                decision_reason="role_not_presentation",
                skip_ocr=False,
            )
            for page_number in range(2, 7)
        ],
        _decision(
            7,
            decision_reason="local_dense_text_visual_conflict",
            skip_ocr=False,
            page_role="full_page_chart",
        ),
        _decision(
            8,
            decision_reason="presentation_page_high_resolution_confirmed",
            skip_ocr=True,
            page_role="chapter_divider",
        ),
        _decision(
            9,
            decision_reason="native_pdf_text_accepted",
            skip_ocr=True,
            native_text_accepted=True,
        ),
        _decision(
            10,
            decision_reason="role_not_presentation",
            skip_ocr=False,
        ),
        _decision(
            11,
            decision_reason="presentation_page_high_resolution_confirmed",
            skip_ocr=True,
            page_role="back_cover",
        ),
    ]

    diagnostics = _run_observed_classification(monkeypatch, decisions)
    summary = next(
        fields
        for event, fields in diagnostics
        if event == "PDF_PAGE_CLASSIFICATION_SUMMARY"
    )

    assert summary["document_page_count"] == 11
    assert summary["candidate_count"] == 11
    assert summary["classifier_success_count"] == 11
    assert summary["presentation_page_count"] == 3
    assert summary["native_text_page_count"] == 1
    assert summary["provider_page_count"] == 7
    assert summary["excluded_from_provider_count"] == 4
    assert summary["candidate_to_ocr_count"] == 7
    assert summary["classified_candidate_to_ocr_count"] == 7
    assert summary["classifier_fail_open_to_ocr_count"] == 0
    assert sum(event == "PDF_PAGE_CLASSIFICATION_DECISION" for event, _ in diagnostics) == 11


def test_legacy_presentation_summary_reason_remains_supported(monkeypatch) -> None:
    decisions = [
        _decision(
            1,
            decision_reason="presentation_page_confirmed",
            skip_ocr=True,
            page_role="cover",
        ),
        _decision(2, decision_reason="role_not_presentation", skip_ocr=False),
    ]

    diagnostics = _run_observed_classification(monkeypatch, decisions)
    summary = next(
        fields
        for event, fields in diagnostics
        if event == "PDF_PAGE_CLASSIFICATION_SUMMARY"
    )

    assert summary["presentation_page_count"] == 1
    assert summary["native_text_page_count"] == 0
    assert summary["provider_page_count"] == 1
    assert summary["excluded_from_provider_count"] == 1
