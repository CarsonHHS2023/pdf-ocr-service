from __future__ import annotations

import base64

import pytest

from app.processing.pdf_structure_refinement_images import (
    PdfPageImageBatchPlanner,
    PdfPageImagePolicy,
    PdfPageImageResolver,
    openai_pdf_structure_refinement_is_configured,
    pdf_page_image_policy_from_env,
)
from app.processing.structured_result_v2.model import (
    ProcessingNode,
    ProcessingNodeKind,
    StructuredProcessingResultV2,
)
from app.source_units import SourceUnit, SourceUnitDimensions, SourceUnitKind


def _pdf_bytes(page_count: int = 3) -> bytes:
    import fitz

    document = fitz.open()
    try:
        for index in range(page_count):
            page = document.new_page(width=600, height=900)
            page.insert_text((72, 96), f"Page {index + 1}")
        return document.tobytes()
    finally:
        document.close()


def _spr(page_count: int = 3) -> StructuredProcessingResultV2:
    units = tuple(
        SourceUnit(
            f"pdf-page:{index + 1:06d}",
            SourceUnitKind.PHYSICAL_PAGE,
            index,
            "source-pdf",
            dimensions=SourceUnitDimensions(600, 900),
        )
        for index in range(page_count)
    )
    nodes = tuple(
        ProcessingNode(
            f"heading-page-{index + 1}",
            ProcessingNodeKind.HEADING,
            index,
            (units[index].source_unit_id,),
            text=f"Chapter {index + 1}",
            heading_level=1,
        )
        for index in range(page_count)
    )
    return StructuredProcessingResultV2(
        document_ref="doc",
        processing_run_ref="run",
        source_units=units,
        observations=(),
        nodes=nodes,
    )


def test_resolver_includes_first_relevant_and_last_pages_as_bounded_jpegs() -> None:
    resolver = PdfPageImageResolver(
        _pdf_bytes(),
        policy=PdfPageImagePolicy(max_pages=3, max_dimension_pixels=700, jpeg_quality=70),
    )

    images = resolver(_spr())

    assert list(images) == ["pdf-page:000001", "pdf-page:000002", "pdf-page:000003"]
    for data_url in images.values():
        assert data_url.startswith("data:image/jpeg;base64,")
        decoded = base64.b64decode(data_url.split(",", 1)[1])
        assert decoded.startswith(b"\xff\xd8")
        assert len(decoded) <= 1_500_000


def test_resolver_honors_page_limit_and_returns_defensive_copies() -> None:
    resolver = PdfPageImageResolver(_pdf_bytes(), policy=PdfPageImagePolicy(max_pages=2))

    first = resolver(_spr())
    first.clear()
    second = resolver(_spr())

    assert list(second) == ["pdf-page:000001", "pdf-page:000002"]


def test_batch_planner_covers_every_selected_page_without_truncation() -> None:
    planner = PdfPageImageBatchPlanner(_pdf_bytes(7), policy=PdfPageImagePolicy(max_pages=3))

    batches = planner(_spr(7))

    assert [len(batch) for batch in batches] == [3, 3, 1]
    assert [page for batch in batches for page in batch] == [
        f"pdf-page:{index:06d}" for index in range(1, 8)
    ]


def test_policy_rejects_unbounded_or_invalid_values() -> None:
    with pytest.raises(ValueError, match="max_pages"):
        PdfPageImagePolicy(max_pages=0)
    with pytest.raises(ValueError, match="jpeg_quality"):
        PdfPageImagePolicy(jpeg_quality=100)
    with pytest.raises(ValueError, match="max_image_bytes"):
        PdfPageImagePolicy(max_image_bytes=100)


def test_policy_loads_production_image_limits_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_MAX_PAGES_PER_BATCH", "8")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_MAX_IMAGE_DIMENSION_PIXELS", "1200")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_JPEG_QUALITY", "68")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_MAX_IMAGE_BYTES", "900000")

    policy = pdf_page_image_policy_from_env()

    assert policy == PdfPageImagePolicy(
        max_pages=8,
        max_dimension_pixels=1200,
        jpeg_quality=68,
        max_image_bytes=900_000,
    )


def test_policy_environment_values_are_strictly_validated(monkeypatch) -> None:
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_MAX_PAGES_PER_BATCH", "many")
    with pytest.raises(
        ValueError,
        match="PDF_STRUCTURE_REFINEMENT_MAX_PAGES_PER_BATCH must be an integer",
    ):
        pdf_page_image_policy_from_env()

    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_MAX_PAGES_PER_BATCH", "4")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_JPEG_QUALITY", "10")
    with pytest.raises(ValueError, match="jpeg_quality"):
        pdf_page_image_policy_from_env()


def test_batch_planner_uses_environment_policy_when_not_explicitly_overridden(monkeypatch) -> None:
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_MAX_PAGES_PER_BATCH", "2")

    planner = PdfPageImageBatchPlanner(_pdf_bytes(5))
    batches = planner(_spr(5))

    assert [len(batch) for batch in batches] == [2, 2, 1]


def test_resolver_rejects_empty_pdf_bytes() -> None:
    with pytest.raises(ValueError, match="pdf_bytes"):
        PdfPageImageResolver(b"")


def test_openai_refinement_configuration_is_explicit_and_complete(monkeypatch) -> None:
    monkeypatch.delenv("PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PDF_STRUCTURE_REFINEMENT_OPENAI_MODEL", raising=False)
    assert openai_pdf_structure_refinement_is_configured() is False

    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY", "secret")
    with pytest.raises(ValueError, match="both PDF_STRUCTURE_REFINEMENT"):
        openai_pdf_structure_refinement_is_configured()

    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_OPENAI_MODEL", "vision-model")
    assert openai_pdf_structure_refinement_is_configured() is True
