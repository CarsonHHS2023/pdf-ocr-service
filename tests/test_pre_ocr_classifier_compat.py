from __future__ import annotations

from app.processing import pdf_page_presentation_bridge as presentation
from app.processing.pdf_page_presentation_classifier_compat import (
    install_classifier_audit_compat,
)


def test_enriched_provider_audit_fields_are_accepted(monkeypatch):
    presentation._CLASSIFICATION_CACHE.clear()

    def enriched(_png, _features, context):
        return {
            "source_unit_id": context["source_unit_id"],
            "page_role": "cover",
            "confidence": 0.99,
            "reason_codes": ["visual_cover"],
            "provider": "openai",
            "model_id": "gpt-test",
            "prompt_version": "prompt-v1",
            "image_detail": "high",
            "input_tokens": 123,
            "output_tokens": 17,
            "cache_hit": False,
        }

    monkeypatch.setattr(presentation, "_CLASSIFIER_OVERRIDE", enriched)
    install_classifier_audit_compat()

    result = presentation._classify(
        b"image-with-audit",
        {"native_text_chars": 10},
        {"source_unit_id": "pdf-page:000001"},
    )

    assert result["page_role"] == "cover"
    assert result["provider"] == "openai"
    assert result["model_id"] == "gpt-test"
    assert result["image_detail"] == "high"
    assert result["input_tokens"] == 123
    assert result["output_tokens"] == 17


def test_strict_model_json_still_rejects_extra_fields():
    try:
        presentation._strict_classification(
            {
                "source_unit_id": "pdf-page:000001",
                "page_role": "cover",
                "confidence": 0.99,
                "reason_codes": ["visual_cover"],
                "unexpected": True,
            },
            expected_source_unit_id="pdf-page:000001",
        )
    except ValueError as exc:
        assert "fields" in str(exc)
    else:
        raise AssertionError("strict model JSON accepted an extra field")


def test_identical_pixels_with_different_page_context_do_not_share_cache(monkeypatch):
    presentation._CLASSIFICATION_CACHE.clear()
    calls = []

    def contextual(_png, _features, context):
        calls.append(dict(context))
        return {
            "source_unit_id": context["source_unit_id"],
            "page_role": (
                "cover" if context["is_first_physical_page"] else "back_cover"
            ),
            "confidence": 0.99,
            "reason_codes": list(context["candidate_reasons"]),
        }

    monkeypatch.setattr(presentation, "_CLASSIFIER_OVERRIDE", contextual)
    install_classifier_audit_compat()
    common_features = {
        "native_text_chars": 10,
        "estimated_continuous_body_prose_ratio": 0.0,
    }
    first = presentation._classify(
        b"identical-rendering",
        common_features,
        {
            "source_unit_id": "pdf-page:000001",
            "page_number": 1,
            "page_index": 0,
            "page_count": 8,
            "is_first_physical_page": True,
            "is_last_physical_page": False,
            "candidate_reasons": ["first_physical_page"],
        },
    )
    last = presentation._classify(
        b"identical-rendering",
        common_features,
        {
            "source_unit_id": "pdf-page:000008",
            "page_number": 8,
            "page_index": 7,
            "page_count": 8,
            "is_first_physical_page": False,
            "is_last_physical_page": True,
            "candidate_reasons": ["last_physical_page"],
        },
    )

    assert first["page_role"] == "cover"
    assert last["page_role"] == "back_cover"
    assert first["cache_hit"] is False
    assert last["cache_hit"] is False
    assert len(calls) == 2


def test_context_equivalent_classification_can_rebind_source_identity(monkeypatch):
    presentation._CLASSIFICATION_CACHE.clear()
    calls = []

    def classify(_png, _features, context):
        calls.append(context["source_unit_id"])
        return {
            "source_unit_id": context["source_unit_id"],
            "page_role": "title_page",
            "confidence": 0.98,
            "reason_codes": ["same_prompt_context"],
        }

    monkeypatch.setattr(presentation, "_CLASSIFIER_OVERRIDE", classify)
    install_classifier_audit_compat()
    context = {
        "page_number": 2,
        "page_index": 1,
        "page_count": 10,
        "is_first_physical_page": False,
        "is_last_physical_page": False,
        "candidate_reasons": ["large_title"],
    }
    first = presentation._classify(
        b"same-image-and-context",
        {"native_text_chars": 20},
        {"source_unit_id": "pdf-page:000002", **context},
    )
    second = presentation._classify(
        b"same-image-and-context",
        {"native_text_chars": 20},
        {"source_unit_id": "pdf-page:000099", **context},
    )

    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert second["source_unit_id"] == "pdf-page:000099"
    assert calls == ["pdf-page:000002"]
