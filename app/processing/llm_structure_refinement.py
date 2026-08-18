"""Bounded LLM-assisted structure and OCR refinement for recovered PDF SPR v2."""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Protocol

from app.processing.structured_result_v2.model import (
    ProcessingNode,
    ProcessingNodeKind,
    ProcessingNodeRecoveryState,
    StructuredProcessingResultV2,
)
from app.processing.structured_result_v2.validation import validate_spr_v2


DEFAULT_STRUCTURE_AUTO_APPLY_THRESHOLD = 0.90
DEFAULT_TOC_LEVEL_AUTO_APPLY_THRESHOLD = 0.85
DEFAULT_TEXT_CORRECTION_THRESHOLD = 0.90
DEFAULT_TEXT_CORRECTION_MAX_SOURCE_OCR_CONFIDENCE = 0.80
DEFAULT_STRUCTURE_REFINEMENT_PROMPT_VERSION = (
    "pdf_structure_refinement_v4_page_roles_v5_unresolved_review"
)
_PAGE_ROLE_CARRIER_PREFIX = "llm-page-role-carrier:"


class RefinementOperationKind(str, Enum):
    RECLASSIFY_NODE = "reclassify_node"
    SET_TOC_LEVEL = "set_toc_level"
    SET_PARENT = "set_parent"
    SUPPRESS_AS_ARTIFACT = "suppress_as_artifact"
    CORRECT_TEXT = "correct_text"
    ADD_WARNING = "add_warning"


class PageRole(str, Enum):
    COVER = "cover"
    BACK_COVER = "back_cover"
    TITLE_PAGE = "title_page"
    COPYRIGHT_PAGE = "copyright_page"
    BODY = "body"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PageRoleReview:
    source_unit_id: str
    page_role: PageRole
    confidence: float
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.source_unit_id, str) or not self.source_unit_id.strip():
            raise ValueError("source_unit_id must be non-empty")
        if not isinstance(self.page_role, PageRole):
            raise ValueError("page_role must be a PageRole")
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not 0 <= float(self.confidence) <= 1
        ):
            raise ValueError("confidence must be between 0 and 1")
        if not self.reason_codes or any(not code.strip() for code in self.reason_codes):
            raise ValueError("reason_codes must contain non-empty values")


@dataclass(frozen=True, slots=True)
class StructureRefinementOperation:
    kind: RefinementOperationKind
    node_id: str
    confidence: float
    reason_codes: tuple[str, ...]
    target_kind: ProcessingNodeKind | None = None
    heading_level: int | None = None
    toc_level: int | None = None
    parent_id: str | None = None
    original_text: str | None = None
    corrected_text: str | None = None
    warning: str | None = None

    def __post_init__(self) -> None:
        if not self.node_id.strip():
            raise ValueError("node_id must be non-empty")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if not self.reason_codes or any(not code.strip() for code in self.reason_codes):
            raise ValueError("reason_codes must contain non-empty values")
        if self.kind is RefinementOperationKind.RECLASSIFY_NODE and self.target_kind is None:
            raise ValueError("reclassify_node requires target_kind")
        if self.kind is RefinementOperationKind.SET_TOC_LEVEL:
            if not isinstance(self.toc_level, int) or isinstance(self.toc_level, bool) or self.toc_level < 1:
                raise ValueError("set_toc_level requires a positive integer toc_level")
        if self.kind is RefinementOperationKind.CORRECT_TEXT:
            if self.original_text is None:
                raise ValueError("correct_text requires original_text")
            if not isinstance(self.corrected_text, str) or not self.corrected_text.strip():
                raise ValueError("correct_text requires non-empty corrected_text")
            if self.corrected_text == self.original_text:
                raise ValueError("correct_text must change the text")
        if self.kind is RefinementOperationKind.ADD_WARNING and not (self.warning or "").strip():
            raise ValueError("add_warning requires warning")


@dataclass(frozen=True, slots=True)
class StructureRefinementPatch:
    model_id: str
    operations: tuple[StructureRefinementOperation, ...]
    prompt_version: str = DEFAULT_STRUCTURE_REFINEMENT_PROMPT_VERSION
    page_reviews: tuple[PageRoleReview, ...] = ()


class StructureRefiner(Protocol):
    def propose(self, spr: StructuredProcessingResultV2) -> StructureRefinementPatch: ...


def _validated_threshold(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
        raise ValueError(f"{name} must be a number between 0 and 1")
    return float(value)


def _maximum_linked_source_ocr_confidence(
    spr: StructuredProcessingResultV2,
    node: ProcessingNode,
) -> float | None:
    observations = {item.observation_id: item for item in spr.observations}
    values = [
        float(observations[observation_id].confidence)
        for observation_id in node.observation_ids
        if observation_id in observations and observations[observation_id].confidence is not None
    ]
    return max(values) if values else None


def apply_structure_refinement_patch(
    spr: StructuredProcessingResultV2,
    patch: StructureRefinementPatch,
    *,
    auto_apply_threshold: float = DEFAULT_STRUCTURE_AUTO_APPLY_THRESHOLD,
    toc_level_auto_apply_threshold: float = DEFAULT_TOC_LEVEL_AUTO_APPLY_THRESHOLD,
    text_correction_threshold: float = DEFAULT_TEXT_CORRECTION_THRESHOLD,
    text_correction_max_source_ocr_confidence: float = (
        DEFAULT_TEXT_CORRECTION_MAX_SOURCE_OCR_CONFIDENCE
    ),
) -> StructuredProcessingResultV2:
    """Apply bounded operations and retain page-role reviews as node metadata."""
    auto_apply_threshold = _validated_threshold("auto_apply_threshold", auto_apply_threshold)
    toc_level_auto_apply_threshold = _validated_threshold(
        "toc_level_auto_apply_threshold", toc_level_auto_apply_threshold
    )
    text_correction_threshold = _validated_threshold(
        "text_correction_threshold", text_correction_threshold
    )
    text_correction_max_source_ocr_confidence = _validated_threshold(
        "text_correction_max_source_ocr_confidence",
        text_correction_max_source_ocr_confidence,
    )

    nodes = {node.node_id: node for node in spr.nodes}
    reclassification_outcomes: dict[str, bool] = {}
    for operation in patch.operations:
        node = nodes.get(operation.node_id)
        if node is None:
            raise ValueError(f"refinement references unknown node_id: {operation.node_id}")

        if operation.kind is RefinementOperationKind.CORRECT_TEXT:
            source_ocr_confidence = _maximum_linked_source_ocr_confidence(spr, node)
            policy: dict[str, object] = {
                "model_confidence_must_be_strictly_greater_than": text_correction_threshold,
                "source_ocr_confidence_must_be_strictly_below": (
                    text_correction_max_source_ocr_confidence
                ),
                "maximum_linked_source_ocr_confidence": source_ocr_confidence,
            }
            rejection_reason = None
            if operation.confidence <= text_correction_threshold:
                rejection_reason = "model_confidence_not_strictly_above_threshold"
            elif source_ocr_confidence is None:
                rejection_reason = "source_ocr_confidence_missing"
            elif source_ocr_confidence >= text_correction_max_source_ocr_confidence:
                rejection_reason = "source_ocr_confidence_not_strictly_below_threshold"
            if rejection_reason is not None:
                policy["rejection_reason"] = rejection_reason
                nodes[node.node_id] = _append_audit(
                    node,
                    patch,
                    operation,
                    applied=False,
                    application_policy=policy,
                )
                continue
            nodes[node.node_id] = _apply_operation(
                node,
                nodes,
                patch,
                operation,
                source_ocr_confidence=source_ocr_confidence,
                application_policy=policy,
            )
            continue

        if (
            operation.kind is RefinementOperationKind.SET_TOC_LEVEL
            and node.kind is not ProcessingNodeKind.LIST_ITEM
            and reclassification_outcomes.get(node.node_id) is False
        ):
            nodes[node.node_id] = _append_audit(
                node,
                patch,
                operation,
                applied=False,
                application_policy={
                    "depends_on": RefinementOperationKind.RECLASSIFY_NODE.value,
                    "dependent_reclassification_applied": False,
                    "reclassification_auto_apply_threshold": auto_apply_threshold,
                    "rejection_reason": "dependent_reclassification_not_applied",
                },
            )
            continue

        threshold = (
            toc_level_auto_apply_threshold
            if operation.kind is RefinementOperationKind.SET_TOC_LEVEL
            else auto_apply_threshold
        )
        if operation.confidence < threshold:
            nodes[node.node_id] = _append_audit(node, patch, operation, applied=False)
            if operation.kind is RefinementOperationKind.RECLASSIFY_NODE:
                reclassification_outcomes[node.node_id] = False
            continue
        nodes[node.node_id] = _apply_operation(node, nodes, patch, operation)
        if operation.kind is RefinementOperationKind.RECLASSIFY_NODE:
            reclassification_outcomes[node.node_id] = True

    known_source_unit_ids = frozenset(unit.source_unit_id for unit in spr.source_units)
    next_order = max((node.order for node in nodes.values()), default=-1) + 1
    for review in patch.page_reviews:
        if review.source_unit_id not in known_source_unit_ids:
            raise ValueError(
                "page-role review references unknown source_unit_id: "
                f"{review.source_unit_id}"
            )
        target_ids = [
            node_id
            for node_id, node in nodes.items()
            if review.source_unit_id in node.source_unit_ids
        ]
        if not target_ids:
            carrier_id = _page_role_carrier_node_id(review.source_unit_id)
            if carrier_id in nodes:
                raise ValueError(f"page-role carrier node_id collision: {carrier_id}")
            carrier = ProcessingNode(
                node_id=carrier_id,
                kind=ProcessingNodeKind.REFERENCE,
                order=next_order,
                source_unit_ids=(review.source_unit_id,),
                recovery_state=ProcessingNodeRecoveryState.UNAVAILABLE,
                metadata={
                    "llm_page_role_carrier": True,
                    "suppressed_as_artifact": True,
                    "suppressed_original_kind": "page_role_carrier",
                    "suppression_source": "llm_page_role_review",
                },
            )
            next_order += 1
            nodes[carrier_id] = carrier
            target_ids = [carrier_id]
        for node_id in target_ids:
            nodes[node_id] = _append_page_role_audit(nodes[node_id], patch, review)

    refined = replace(
        spr,
        nodes=tuple(sorted(nodes.values(), key=lambda item: (item.order, item.node_id))),
    )
    validate_spr_v2(refined)
    return refined


def _page_role_carrier_node_id(source_unit_id: str) -> str:
    return f"{_PAGE_ROLE_CARRIER_PREFIX}{source_unit_id}"


def _apply_operation(
    node: ProcessingNode,
    nodes: dict[str, ProcessingNode],
    patch: StructureRefinementPatch,
    operation: StructureRefinementOperation,
    *,
    source_ocr_confidence: float | None = None,
    application_policy: dict[str, object] | None = None,
) -> ProcessingNode:
    updated = node
    if operation.kind is RefinementOperationKind.RECLASSIFY_NODE:
        target = operation.target_kind
        assert target is not None
        level = operation.heading_level
        if target is ProcessingNodeKind.HEADING:
            level = level or node.heading_level or 2
        elif target is not ProcessingNodeKind.TITLE:
            level = None
        updated = replace(node, kind=target, heading_level=level)
    elif operation.kind is RefinementOperationKind.SET_TOC_LEVEL:
        if node.kind is not ProcessingNodeKind.LIST_ITEM:
            raise ValueError("toc_level is only valid for list_item nodes")
        metadata = dict(node.metadata or {})
        metadata["toc_level"] = operation.toc_level
        metadata["toc_level_confidence"] = operation.confidence
        metadata["toc_level_source"] = "llm_structure_refinement"
        updated = replace(node, metadata=metadata)
    elif operation.kind is RefinementOperationKind.SET_PARENT:
        if operation.parent_id == node.node_id:
            raise ValueError("node cannot be its own parent")
        if operation.parent_id is not None and operation.parent_id not in nodes:
            raise ValueError("parent_id must reference an existing node")
        updated = replace(node, parent_id=operation.parent_id)
    elif operation.kind is RefinementOperationKind.SUPPRESS_AS_ARTIFACT:
        metadata = dict(node.metadata or {})
        metadata["suppressed_original_kind"] = node.kind.value
        metadata["suppressed_as_artifact"] = True
        metadata["suppression_source"] = "llm_structure_refinement"
        metadata["suppression_confidence"] = operation.confidence
        metadata["suppression_reason_codes"] = list(operation.reason_codes)
        updated = replace(
            node,
            kind=ProcessingNodeKind.UNKNOWN,
            heading_level=None,
            recovery_state=ProcessingNodeRecoveryState.DEGRADED,
            metadata=metadata,
        )
    elif operation.kind is RefinementOperationKind.CORRECT_TEXT:
        if (node.text or "") != operation.original_text:
            raise ValueError("correct_text original_text does not match current node text")
        metadata = dict(node.metadata or {})
        corrections = list(metadata.get("ocr_text_corrections") or [])
        corrections.append(
            {
                "original_text": operation.original_text,
                "corrected_text": operation.corrected_text,
                "confidence": operation.confidence,
                "source_ocr_confidence": source_ocr_confidence,
                "reason_codes": list(operation.reason_codes),
                "source": "llm_structure_refinement",
            }
        )
        metadata["ocr_text_corrections"] = corrections
        updated = replace(node, text=operation.corrected_text, metadata=metadata)
    elif operation.kind is RefinementOperationKind.ADD_WARNING:
        metadata = dict(node.metadata or {})
        warnings = list(metadata.get("refinement_warnings") or [])
        warnings.append(operation.warning)
        metadata["refinement_warnings"] = warnings
        updated = replace(node, metadata=metadata)
    return _append_audit(
        updated,
        patch,
        operation,
        applied=True,
        application_policy=application_policy,
    )


def _append_audit(
    node: ProcessingNode,
    patch: StructureRefinementPatch,
    operation: StructureRefinementOperation,
    *,
    applied: bool,
    application_policy: dict[str, object] | None = None,
) -> ProcessingNode:
    metadata = dict(node.metadata or {})
    history = list(metadata.get("llm_structure_refinement") or [])
    entry: dict[str, object] = {
        "model_id": patch.model_id,
        "prompt_version": patch.prompt_version,
        "operation": operation.kind.value,
        "confidence": operation.confidence,
        "reason_codes": list(operation.reason_codes),
        "applied": applied,
    }
    if application_policy is not None:
        entry["application_policy"] = dict(application_policy)
    history.append(entry)
    metadata["llm_structure_refinement"] = history
    return replace(node, metadata=metadata)


def _append_page_role_audit(
    node: ProcessingNode,
    patch: StructureRefinementPatch,
    review: PageRoleReview,
) -> ProcessingNode:
    metadata = dict(node.metadata or {})
    history = list(metadata.get("llm_page_role_review") or [])
    history.append(
        {
            "model_id": patch.model_id,
            "prompt_version": patch.prompt_version,
            "source_unit_id": review.source_unit_id,
            "page_role": review.page_role.value,
            "confidence": review.confidence,
            "reason_codes": list(review.reason_codes),
        }
    )
    metadata["llm_page_role_review"] = history
    return replace(node, metadata=metadata)


__all__ = [
    "DEFAULT_STRUCTURE_AUTO_APPLY_THRESHOLD",
    "DEFAULT_STRUCTURE_REFINEMENT_PROMPT_VERSION",
    "DEFAULT_TOC_LEVEL_AUTO_APPLY_THRESHOLD",
    "DEFAULT_TEXT_CORRECTION_THRESHOLD",
    "DEFAULT_TEXT_CORRECTION_MAX_SOURCE_OCR_CONFIDENCE",
    "PageRole",
    "PageRoleReview",
    "RefinementOperationKind",
    "StructureRefinementOperation",
    "StructureRefinementPatch",
    "StructureRefiner",
    "apply_structure_refinement_patch",
]
