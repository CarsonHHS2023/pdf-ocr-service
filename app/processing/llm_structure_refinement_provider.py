"""Provider-neutral JSON adapter for bounded PDF refinement."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from app.processing.llm_structure_refinement import (
    DEFAULT_STRUCTURE_REFINEMENT_PROMPT_VERSION,
    PageRole,
    PageRoleReview,
    RefinementOperationKind,
    StructureRefinementOperation,
    StructureRefinementPatch,
)
from app.processing.llm_structure_refinement_request import build_structure_refinement_request
from app.processing.structured_result_v2.model import ProcessingNodeKind, StructuredProcessingResultV2

JsonTransport = Callable[[dict[str, object]], Mapping[str, Any]]

_OPERATION_SPECIFIC_FIELDS = (
    "target_kind",
    "heading_level",
    "toc_level",
    "parent_id",
    "original_text",
    "corrected_text",
    "warning",
)


class StructureRefinementResponseError(ValueError):
    """Bounded response-validation error with safe diagnostic context."""

    def __init__(
        self,
        message: str,
        *,
        stage: str,
        operation_index: int | None = None,
        operation_kind: str | None = None,
        null_fields: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.operation_index = operation_index
        self.operation_kind = operation_kind
        self.null_fields = tuple(null_fields)


@dataclass(frozen=True, slots=True)
class JsonStructureRefiner:
    model_id: str
    transport: JsonTransport
    prompt_version: str = DEFAULT_STRUCTURE_REFINEMENT_PROMPT_VERSION

    def propose(self, spr: StructuredProcessingResultV2) -> StructureRefinementPatch:
        response = self.transport(build_structure_refinement_request(spr))
        return parse_structure_refinement_response(
            response,
            model_id=self.model_id,
            prompt_version=self.prompt_version,
        )


def parse_structure_refinement_response(
    payload: Mapping[str, Any],
    *,
    model_id: str,
    prompt_version: str = DEFAULT_STRUCTURE_REFINEMENT_PROMPT_VERSION,
) -> StructureRefinementPatch:
    if not isinstance(payload, Mapping):
        raise StructureRefinementResponseError(
            "structure refinement response must be an object",
            stage="response_root_validation",
        )
    raw_operations = payload.get("operations")
    if not isinstance(raw_operations, list):
        raise StructureRefinementResponseError(
            "structure refinement response requires an operations array",
            stage="operations_validation",
        )
    raw_page_reviews = payload.get("page_reviews", [])
    if not isinstance(raw_page_reviews, list):
        raise StructureRefinementResponseError(
            "page_reviews must be an array",
            stage="page_reviews_validation",
        )

    operations: list[StructureRefinementOperation] = []
    for operation_index, item in enumerate(raw_operations):
        operations.append(_parse_operation(item, operation_index=operation_index))
    page_reviews = tuple(
        _parse_page_review(item, review_index=review_index)
        for review_index, item in enumerate(raw_page_reviews)
    )
    return StructureRefinementPatch(
        model_id=model_id,
        prompt_version=prompt_version,
        operations=tuple(operations),
        page_reviews=page_reviews,
    )


def _parse_page_review(payload: Any, *, review_index: int) -> PageRoleReview:
    if not isinstance(payload, Mapping):
        raise StructureRefinementResponseError(
            "each page-role review must be an object",
            stage="page_review_not_object",
            operation_index=review_index,
            operation_kind="page_role_review",
        )
    raw_reasons = payload.get("reason_codes")
    if not isinstance(raw_reasons, list):
        raise StructureRefinementResponseError(
            "page-role reason_codes must be an array",
            stage="page_review_reason_codes",
            operation_index=review_index,
            operation_kind="page_role_review",
        )
    try:
        return PageRoleReview(
            source_unit_id=str(payload["source_unit_id"]),
            page_role=PageRole(str(payload["page_role"])),
            confidence=float(payload["confidence"]),
            reason_codes=tuple(str(item) for item in raw_reasons),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise StructureRefinementResponseError(
            "invalid page-role review",
            stage="page_review_semantics",
            operation_index=review_index,
            operation_kind="page_role_review",
        ) from exc


def _parse_operation(
    payload: Any,
    *,
    operation_index: int,
) -> StructureRefinementOperation:
    if not isinstance(payload, Mapping):
        raise StructureRefinementResponseError(
            "each refinement operation must be an object",
            stage="operation_not_object",
            operation_index=operation_index,
        )

    operation_kind = _operation_kind(payload)
    null_fields = _null_operation_fields(payload)
    try:
        kind = RefinementOperationKind(str(payload["op"]))
        node_id = str(payload["node_id"])
        confidence = float(payload["confidence"])
    except (KeyError, TypeError, ValueError) as exc:
        raise StructureRefinementResponseError(
            "invalid refinement operation identity",
            stage="operation_identity",
            operation_index=operation_index,
            operation_kind=operation_kind,
            null_fields=null_fields,
        ) from exc

    raw_reasons = payload.get("reason_codes")
    if not isinstance(raw_reasons, list):
        raise StructureRefinementResponseError(
            "reason_codes must be an array",
            stage="operation_reason_codes",
            operation_index=operation_index,
            operation_kind=kind.value,
            null_fields=null_fields,
        )

    target_kind = payload.get("target_kind")
    try:
        parsed_target = (
            ProcessingNodeKind(str(target_kind))
            if target_kind is not None
            else None
        )
    except ValueError as exc:
        raise StructureRefinementResponseError(
            "target_kind must be an allowed processing node kind",
            stage="operation_target_kind",
            operation_index=operation_index,
            operation_kind=kind.value,
            null_fields=null_fields,
        ) from exc

    try:
        return StructureRefinementOperation(
            kind=kind,
            node_id=node_id,
            confidence=confidence,
            reason_codes=tuple(str(item) for item in raw_reasons),
            target_kind=parsed_target,
            heading_level=payload.get("heading_level"),
            toc_level=payload.get("toc_level"),
            parent_id=payload.get("parent_id"),
            original_text=payload.get("original_text"),
            corrected_text=payload.get("corrected_text"),
            warning=payload.get("warning"),
        )
    except ValueError as exc:
        raise StructureRefinementResponseError(
            str(exc),
            stage="operation_semantics",
            operation_index=operation_index,
            operation_kind=kind.value,
            null_fields=null_fields,
        ) from exc


def _operation_kind(payload: Mapping[str, Any]) -> str | None:
    value = payload.get("op")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:64]


def _null_operation_fields(payload: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(
        field
        for field in _OPERATION_SPECIFIC_FIELDS
        if field in payload and payload.get(field) is None
    )


__all__ = [
    "DEFAULT_STRUCTURE_REFINEMENT_PROMPT_VERSION",
    "JsonStructureRefiner",
    "JsonTransport",
    "StructureRefinementResponseError",
    "parse_structure_refinement_response",
]
