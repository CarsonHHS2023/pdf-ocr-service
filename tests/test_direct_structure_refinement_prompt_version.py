from __future__ import annotations

from app.processing.llm_structure_refinement_provider import (
    DEFAULT_STRUCTURE_REFINEMENT_PROMPT_VERSION,
    JsonStructureRefiner,
    parse_structure_refinement_response,
)
from app.processing.openai_structure_refinement_provider import (
    OpenAIResponsesStructureRefiner,
)
from app.processing.structured_result_v2.model import StructuredProcessingResultV2
from app.source_units import SourceUnit, SourceUnitDimensions, SourceUnitKind


def _spr() -> StructuredProcessingResultV2:
    unit = SourceUnit(
        "pdf-page:000001",
        SourceUnitKind.PHYSICAL_PAGE,
        0,
        "pdf-source",
        dimensions=SourceUnitDimensions(888, 1226),
    )
    return StructuredProcessingResultV2(
        document_ref="doc-1",
        processing_run_ref="run-1",
        source_units=(unit,),
        observations=(),
        nodes=(),
    )


def _empty_v5_response() -> dict[str, object]:
    return {
        "page_reviews": [
            {
                "source_unit_id": "pdf-page:000001",
                "page_role": "unknown",
                "confidence": 0.5,
                "reason_codes": ["test_fixture"],
            }
        ],
        "operations": [],
    }


def test_json_direct_provider_attributes_v5_request_to_v5_prompt() -> None:
    requests: list[dict[str, object]] = []
    refiner = JsonStructureRefiner(
        model_id="test-model",
        transport=lambda request: requests.append(request) or _empty_v5_response(),
    )

    patch = refiner.propose(_spr())

    assert requests[0]["request_version"] == 5
    assert patch.prompt_version == DEFAULT_STRUCTURE_REFINEMENT_PROMPT_VERSION
    assert patch.prompt_version == (
        "pdf_structure_refinement_v4_page_roles_v5_unresolved_review"
    )
    assert len(patch.page_reviews) == 1


def test_direct_response_parser_defaults_to_current_prompt_version() -> None:
    patch = parse_structure_refinement_response(
        _empty_v5_response(),
        model_id="test-model",
    )

    assert patch.prompt_version == DEFAULT_STRUCTURE_REFINEMENT_PROMPT_VERSION


def test_openai_direct_provider_attributes_v5_request_to_v5_prompt() -> None:
    import json

    refiner = OpenAIResponsesStructureRefiner(
        api_key="secret",
        model_id="test-model",
        http_post=lambda *_args: {"output_text": json.dumps(_empty_v5_response())},
    )

    patch = refiner.propose(_spr())

    assert patch.prompt_version == DEFAULT_STRUCTURE_REFINEMENT_PROMPT_VERSION
    assert patch.page_reviews[0].page_role.value == "unknown"


def test_direct_providers_preserve_explicit_custom_prompt_versions() -> None:
    import json

    json_patch = JsonStructureRefiner(
        model_id="test-model",
        transport=lambda _request: _empty_v5_response(),
        prompt_version="custom-prompt-v7",
    ).propose(_spr())
    openai_patch = OpenAIResponsesStructureRefiner(
        api_key="secret",
        model_id="test-model",
        prompt_version="custom-prompt-v7",
        http_post=lambda *_args: {"output_text": json.dumps(_empty_v5_response())},
    ).propose(_spr())

    assert json_patch.prompt_version == "custom-prompt-v7"
    assert openai_patch.prompt_version == "custom-prompt-v7"
