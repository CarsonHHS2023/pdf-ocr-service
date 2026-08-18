from __future__ import annotations

from dataclasses import replace

import pytest

from app.processing import pdf_page_presentation_bridge as presentation
from app.storage.models import StorageReference


def _input(*, provider_page_count: int = 2):
    pages = [
        {
            "page_number": 1,
            "source_unit_id": "pdf-page:000001",
            "page_kind": "cover",
            "ocr_route": "skipped_presentation_image",
            "page_width_points": 612.0,
            "page_height_points": 792.0,
            "background": {
                "attempted": False,
                "reason": "presentation_page_background_skipped",
            },
            "page_classification": {
                "source_unit_id": "pdf-page:000001",
                "page_role": "cover",
                "confidence": 0.99,
                "reason_codes": ["book_cover"],
                "provider": "openai",
            },
        },
        {
            "page_number": 2,
            "source_unit_id": "pdf-page:000002",
            "ocr_route": "modal_paddle_ocr",
            "page_width_points": 612.0,
            "page_height_points": 792.0,
            "page_classification": {
                "source_unit_id": "pdf-page:000002",
                "page_role": "body",
                "confidence": 0.98,
                "reason_codes": ["continuous_prose"],
                "provider": "openai",
            },
        },
        {
            "page_number": 3,
            "source_unit_id": "pdf-page:000003",
            "page_kind": "chapter_divider",
            "ocr_route": "skipped_presentation_image",
            "page_width_points": 612.0,
            "page_height_points": 792.0,
            "background": {
                "attempted": False,
                "reason": "presentation_page_background_skipped",
            },
            "page_classification": {
                "source_unit_id": "pdf-page:000003",
                "page_role": "chapter_divider",
                "confidence": 0.97,
                "reason_codes": ["large_centered_title"],
                "provider": "openai",
            },
        },
        {
            "page_number": 4,
            "source_unit_id": "pdf-page:000004",
            "ocr_route": "modal_paddle_ocr",
            "page_width_points": 612.0,
            "page_height_points": 792.0,
            "page_classification": {
                "source_unit_id": "pdf-page:000004",
                "page_role": "body",
                "confidence": 0.99,
                "reason_codes": ["continuous_prose"],
                "provider": "openai",
            },
        },
        {
            "page_number": 5,
            "source_unit_id": "pdf-page:000005",
            "page_kind": "full_page_chart",
            "ocr_route": "skipped_presentation_image",
            "page_width_points": 792.0,
            "page_height_points": 612.0,
            "background": {
                "attempted": False,
                "reason": "presentation_page_background_skipped",
            },
            "page_classification": {
                "source_unit_id": "pdf-page:000005",
                "page_role": "full_page_chart",
                "confidence": 0.96,
                "reason_codes": ["chart_dominates_page"],
                "provider": "openai",
            },
        },
    ]
    return presentation.PresentationProviderInput(
        processing_attempt_id="attempt-1",
        storage_reference=StorageReference.parse("src_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
        checksum_sha256="a" * 64,
        byte_size=100,
        media_type="application/pdf",
        filename="render.pdf",
        preprocessing=None,
        provider_storage_reference=StorageReference.parse(
            "src_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        ),
        provider_checksum_sha256="b" * 64,
        provider_byte_size=50,
        provider_filename="ordinary.pdf",
        provider_page_count=provider_page_count,
        provider_page_map=(
            {
                "provider_page_index": 0,
                "original_page_index": 1,
                "original_page_number": 2,
                "source_unit_id": "pdf-page:000002",
            },
            {
                "provider_page_index": 1,
                "original_page_index": 3,
                "original_page_number": 4,
                "source_unit_id": "pdf-page:000004",
            },
        )
        if provider_page_count
        else (),
        presentation_manifest={
            "page_count": 5,
            "provider_page_count": provider_page_count,
            "presentation_page_count": 3 if provider_page_count else 5,
            "pages": pages,
        },
    )


def _features(**overrides):
    values = {
        "native_text_chars": 40,
        "native_text_block_count": 2,
        "native_text_line_count": 2,
        "whitespace_ratio": 0.75,
        "maximum_embedded_image_coverage": 0.0,
        "dominant_visual_region_ratio": 0.1,
        "estimated_continuous_body_prose_ratio": 0.05,
        "largest_font_to_median_ratio": 2.5,
        "text_region_dispersion": 0.2,
        "likely_discrete_orientation": 0,
    }
    values.update(overrides)
    return values


def test_first_and_last_pages_are_always_candidates():
    selected, first_reasons = presentation._is_candidate(
        _features(
            native_text_chars=4000,
            native_text_block_count=60,
            whitespace_ratio=0.1,
            largest_font_to_median_ratio=1.0,
        ),
        first_page=True,
        last_page=False,
    )
    assert selected is True
    assert "first_physical_page" in first_reasons

    selected, last_reasons = presentation._is_candidate(
        _features(
            native_text_chars=4000,
            native_text_block_count=60,
            whitespace_ratio=0.1,
            largest_font_to_median_ratio=1.0,
        ),
        first_page=False,
        last_page=True,
    )
    assert selected is True
    assert "last_physical_page" in last_reasons


def test_plain_inner_body_page_is_not_selected_for_llm():
    selected, reasons = presentation._is_candidate(
        _features(
            native_text_chars=4000,
            native_text_block_count=50,
            native_text_line_count=70,
            whitespace_ratio=0.15,
            largest_font_to_median_ratio=1.1,
            text_region_dispersion=0.1,
            estimated_continuous_body_prose_ratio=0.9,
        ),
        first_page=False,
        last_page=False,
    )
    assert selected is False
    assert reasons == ()


@pytest.mark.parametrize(
    "role",
    [
        "cover",
        "back_cover",
        "title_page",
        "chapter_divider",
        "full_page_figure",
        "full_page_chart",
    ],
)
def test_high_confidence_presentation_roles_skip_ocr(role):
    skip, reason = presentation._skip_ocr_decision(
        {
            "source_unit_id": "pdf-page:000002",
            "page_role": role,
            "confidence": 0.95,
            "reason_codes": ["visual_presentation"],
        },
        _features(),
    )
    assert skip is True
    assert reason == "presentation_page_confirmed"


def test_unknown_low_confidence_and_invalid_json_fail_safe_to_ocr():
    skip, _ = presentation._skip_ocr_decision(
        {
            "source_unit_id": "pdf-page:000002",
            "page_role": "unknown",
            "confidence": 0.99,
            "reason_codes": ["uncertain"],
        },
        _features(),
    )
    assert skip is False

    skip, reason = presentation._skip_ocr_decision(
        {
            "source_unit_id": "pdf-page:000002",
            "page_role": "cover",
            "confidence": 0.89,
            "reason_codes": ["possible_cover"],
        },
        _features(),
    )
    assert skip is False
    assert reason == "classification_below_confidence_threshold"

    with pytest.raises(ValueError):
        presentation._strict_classification(
            {
                "source_unit_id": "pdf-page:000002",
                "page_role": "cover",
                "confidence": 0.99,
                "reason_codes": ["cover"],
                "extra": True,
            },
            expected_source_unit_id="pdf-page:000002",
        )


def test_local_continuous_prose_conflict_forces_ocr():
    skip, reason = presentation._skip_ocr_decision(
        {
            "source_unit_id": "pdf-page:000002",
            "page_role": "title_page",
            "confidence": 0.99,
            "reason_codes": ["large_title"],
        },
        _features(
            native_text_chars=3000,
            native_text_line_count=60,
            estimated_continuous_body_prose_ratio=0.92,
        ),
    )
    assert skip is False
    assert reason == "local_continuous_prose_conflict"


def test_mixed_provider_pages_are_remapped_to_original_order():
    provider_input = _input()
    provider_pages = [
        {
            "page_number": 1,
            "page_index": 0,
            "local_page_index": 0,
            "source_page_range": {"page_start": 1, "page_end": 1},
            "width": 1000,
            "height": 1300,
            "blocks": [{"type": "paragraph", "text": "page two"}],
        },
        {
            "page_number": 2,
            "page_index": 1,
            "local_page_index": 1,
            "source_page_range": {"page_start": 1, "page_end": 2},
            "width": 1000,
            "height": 1300,
            "blocks": [{"type": "paragraph", "text": "page four"}],
        },
    ]

    remapped = presentation._remap_raw_pages(provider_pages, provider_input)

    assert [page["page_number"] for page in remapped] == [1, 2, 3, 4, 5]
    assert remapped[1]["blocks"][0]["text"] == "page two"
    assert remapped[3]["blocks"][0]["text"] == "page four"
    assert remapped[0]["blocks"] == []
    assert remapped[2]["blocks"] == []
    assert remapped[4]["blocks"] == []
    assert (
        remapped[0]["metadata"]["opencv_preprocessing"]["background"]["attempted"]
        is False
    )
    assert (
        remapped[0]["metadata"]["opencv_preprocessing"]["background"]["reason"]
        == "presentation_page_background_skipped"
    )


def test_provider_mapping_rejects_missing_or_duplicate_pages():
    provider_input = _input()
    with pytest.raises(ValueError):
        presentation._remap_raw_pages([], provider_input)

    duplicate_mapping = replace(
        provider_input,
        provider_page_map=(
            provider_input.provider_page_map[0],
            {
                **provider_input.provider_page_map[1],
                "original_page_number": 2,
                "original_page_index": 1,
            },
        ),
    )
    with pytest.raises(ValueError):
        presentation._remap_raw_pages(
            [
                {"page_number": 1, "page_index": 0, "blocks": []},
                {"page_number": 2, "page_index": 1, "blocks": []},
            ],
            duplicate_mapping,
        )


def test_all_presentation_document_builds_local_synthetic_pages():
    provider_input = _input(provider_page_count=0)
    pages = provider_input.presentation_manifest["pages"]
    provider_input.presentation_manifest["pages"] = [
        {
            **page,
            "ocr_route": "skipped_presentation_image",
            "page_kind": page.get("page_kind") or "title_page",
        }
        for page in pages
    ]

    class Request:
        document_id = "document-1"

    documents = presentation._all_special_documents(Request(), provider_input)
    assert len(documents) == 1
    assert [page["page_number"] for page in documents[0]["raw_result"]] == [
        1,
        2,
        3,
        4,
        5,
    ]
    assert all(page["blocks"] == [] for page in documents[0]["raw_result"])


def test_pre_reviewed_pages_include_body_decisions_to_avoid_duplicate_role_calls():
    reviewed = presentation._pre_reviewed_source_units(
        _input().presentation_manifest
    )
    assert reviewed == {
        "pdf-page:000001",
        "pdf-page:000002",
        "pdf-page:000003",
        "pdf-page:000004",
        "pdf-page:000005",
    }


def test_classification_cache_rebinds_source_unit_id(monkeypatch):
    presentation._CLASSIFICATION_CACHE.clear()
    calls = []

    def classify(_png, _features, context):
        calls.append(context["source_unit_id"])
        return {
            "source_unit_id": context["source_unit_id"],
            "page_role": "cover",
            "confidence": 0.99,
            "reason_codes": ["same_page_checksum"],
        }

    monkeypatch.setattr(presentation, "_CLASSIFIER_OVERRIDE", classify)
    first = presentation._classify(
        b"same-image",
        _features(),
        {"source_unit_id": "pdf-page:000001"},
    )
    second = presentation._classify(
        b"same-image",
        _features(),
        {"source_unit_id": "pdf-page:000099"},
    )

    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert second["source_unit_id"] == "pdf-page:000099"
    assert calls == ["pdf-page:000001"]
