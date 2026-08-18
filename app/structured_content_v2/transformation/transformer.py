from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
import unicodedata

from app.processing.structured_result_v2 import (
    ProcessingNodeKind,
    ProcessingNodeRecoveryState,
    StructuredProcessingResultV2,
    validate_spr_v2,
)
from app.source_units import SourceUnitRecoveryState
from app.structured_content_v2 import (
    ContentNodeTypeV2,
    ContentNodeV2,
    ContentRecoveryStateV2,
    ContentRecoverySummaryV2,
    ContentWarningV2,
    EvidenceReferenceV2,
    NodeRecoveryStateV2,
    StructuredContentCandidateV2,
    StructuredSourceUnit,
    WarningSeverityV2,
    validate_candidate_v2,
)


@dataclass(frozen=True, slots=True)
class TransformationContextV2:
    document_ref: str
    candidate_id: str
    lineage_key: str
    structured_processing_result_ref: str

    def __post_init__(self) -> None:
        for name in ("document_ref", "candidate_id", "lineage_key", "structured_processing_result_ref"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")


@dataclass(frozen=True, slots=True)
class TransformationPolicyV2:
    transformer_ref: str = "atlas.spr-v2-to-structured-content-v2"
    transformation_policy_ref: str = "atlas.structured-content-v2.default"
    recovery_policy_ref: str = "atlas.structured-content-v2.recovery.default"
    unknown_node_warning_code: str = "UNKNOWN_ELEMENT_KIND"

    def __post_init__(self) -> None:
        for name in (
            "transformer_ref",
            "transformation_policy_ref",
            "recovery_policy_ref",
            "unknown_node_warning_code",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")


DEFAULT_TRANSFORMATION_POLICY_V2 = TransformationPolicyV2()


def _ref(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part) for part in parts)
    digest = sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _normalize_text(text: str | None) -> str | None:
    if text is None:
        return None
    normalized = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    if "\x00" in normalized:
        raise ValueError("text must not contain NUL")
    for char in normalized:
        codepoint = ord(char)
        if codepoint < 32 and char not in {"\n", "\t"}:
            raise ValueError(f"text contains unsupported control character U+{codepoint:04X}")
    return normalized


_NODE_TYPE_MAP = {
    ProcessingNodeKind.TITLE: ContentNodeTypeV2.HEADING,
    ProcessingNodeKind.HEADING: ContentNodeTypeV2.HEADING,
    ProcessingNodeKind.PARAGRAPH: ContentNodeTypeV2.PARAGRAPH,
    ProcessingNodeKind.LIST: ContentNodeTypeV2.LIST,
    ProcessingNodeKind.LIST_ITEM: ContentNodeTypeV2.LIST_ITEM,
    ProcessingNodeKind.CAPTION: ContentNodeTypeV2.CAPTION,
    ProcessingNodeKind.FORMULA: ContentNodeTypeV2.FORMULA,
    ProcessingNodeKind.HEADER: ContentNodeTypeV2.HEADER,
    ProcessingNodeKind.FOOTER: ContentNodeTypeV2.FOOTER,
    ProcessingNodeKind.FOOTNOTE: ContentNodeTypeV2.FOOTNOTE,
    ProcessingNodeKind.TABLE: ContentNodeTypeV2.TABLE,
    ProcessingNodeKind.FIGURE: ContentNodeTypeV2.FIGURE,
    ProcessingNodeKind.QUOTE: ContentNodeTypeV2.QUOTE,
    ProcessingNodeKind.CODE: ContentNodeTypeV2.CODE,
    ProcessingNodeKind.REFERENCE: ContentNodeTypeV2.REFERENCE,
    ProcessingNodeKind.UNKNOWN: ContentNodeTypeV2.UNKNOWN,
}


def _node_recovery(state: ProcessingNodeRecoveryState) -> NodeRecoveryStateV2:
    return {
        ProcessingNodeRecoveryState.COMPLETE: NodeRecoveryStateV2.COMPLETE,
        ProcessingNodeRecoveryState.DEGRADED: NodeRecoveryStateV2.DEGRADED,
        ProcessingNodeRecoveryState.UNAVAILABLE: NodeRecoveryStateV2.UNAVAILABLE,
    }[state]


def _content_recovery_summary(
    spr: StructuredProcessingResultV2,
    warning_ids: tuple[str, ...],
    policy: TransformationPolicyV2,
) -> ContentRecoverySummaryV2:
    states = Counter(unit.recovery_state for unit in spr.source_units)
    total = len(spr.source_units)
    if total == 0:
        state = ContentRecoveryStateV2.COMPLETE
    elif states[SourceUnitRecoveryState.UNAVAILABLE] == total:
        state = ContentRecoveryStateV2.UNAVAILABLE
    elif states[SourceUnitRecoveryState.COMPLETE] == total:
        state = ContentRecoveryStateV2.COMPLETE
    else:
        state = ContentRecoveryStateV2.DEGRADED
    return ContentRecoverySummaryV2(
        state=state,
        total_source_units=total,
        complete_source_units=states[SourceUnitRecoveryState.COMPLETE],
        degraded_source_units=states[SourceUnitRecoveryState.DEGRADED],
        no_usable_semantic_content_source_units=states[SourceUnitRecoveryState.NO_USABLE_SEMANTIC_CONTENT],
        unavailable_source_units=states[SourceUnitRecoveryState.UNAVAILABLE],
        warning_ids=warning_ids,
        recovery_policy_ref=policy.recovery_policy_ref,
    )


def _sibling_orders(spr: StructuredProcessingResultV2) -> dict[str, int]:
    children: dict[str | None, list[object]] = defaultdict(list)
    for node in spr.nodes:
        children[node.parent_id].append(node)

    result: dict[str, int] = {}
    for siblings in children.values():
        ordered = sorted(siblings, key=lambda item: (item.order, item.node_id))
        for index, node in enumerate(ordered):
            result[node.node_id] = index
    return result


def transform_spr_v2_to_candidate(
    spr: StructuredProcessingResultV2,
    *,
    context: TransformationContextV2,
    policy: TransformationPolicyV2 = DEFAULT_TRANSFORMATION_POLICY_V2,
) -> StructuredContentCandidateV2:
    """Pure deterministic transformation from validated SPR v2 to canonical Structured Content v2."""

    if not isinstance(spr, StructuredProcessingResultV2):
        raise TypeError("spr must be a StructuredProcessingResultV2")
    if not isinstance(context, TransformationContextV2):
        raise TypeError("context must be a TransformationContextV2")
    if not isinstance(policy, TransformationPolicyV2):
        raise TypeError("policy must be a TransformationPolicyV2")
    validate_spr_v2(spr)
    if spr.document_ref != context.document_ref:
        raise ValueError("context document_ref must match SPR document_ref")

    source_order = {unit.source_unit_id: unit.source_order for unit in spr.source_units}
    source_units = tuple(
        StructuredSourceUnit(source_unit=unit)
        for unit in sorted(spr.source_units, key=lambda unit: (unit.source_order, unit.source_unit_id))
    )

    spr_evidence_id_map = {
        item.evidence_id: _ref("sce", context.candidate_id, "spr-evidence", item.evidence_id)
        for item in spr.evidence
    }
    observation_evidence_id_map = {
        item.observation_id: _ref("sce", context.candidate_id, "observation", item.observation_id)
        for item in spr.observations
    }
    node_evidence_id_map = {
        item.node_id: _ref("sce", context.candidate_id, "node", item.node_id)
        for item in spr.nodes
    }

    evidence: list[EvidenceReferenceV2] = []
    for item in sorted(spr.evidence, key=lambda value: value.evidence_id):
        evidence.append(
            EvidenceReferenceV2(
                evidence_id=spr_evidence_id_map[item.evidence_id],
                source_unit_id=item.source_unit_id,
                source_anchors=tuple(item.anchors),
                processing_run_ref=item.processing_run_ref or spr.processing_run_ref,
                raw_result_ref=item.raw_result_ref or spr.raw_result_ref,
                structured_processing_result_ref=context.structured_processing_result_ref,
                spr_observation_ref=item.observation_id,
                metadata={
                    "spr_evidence_ref": item.evidence_id,
                    **({"provider_ref": item.provider_ref} if item.provider_ref is not None else {}),
                    **({"spr_metadata": item.metadata} if item.metadata is not None else {}),
                },
            )
        )

    for item in sorted(
        spr.observations,
        key=lambda value: (source_order[value.source_unit_id], value.order, value.observation_id),
    ):
        evidence.append(
            EvidenceReferenceV2(
                evidence_id=observation_evidence_id_map[item.observation_id],
                source_unit_id=item.source_unit_id,
                source_anchors=tuple(item.anchors),
                processing_run_ref=spr.processing_run_ref,
                raw_result_ref=spr.raw_result_ref,
                structured_processing_result_ref=context.structured_processing_result_ref,
                spr_observation_ref=item.observation_id,
                metadata={"observed_kind": item.observed_kind},
            )
        )

    for item in sorted(spr.nodes, key=lambda value: (value.order, value.node_id)):
        evidence.append(
            EvidenceReferenceV2(
                evidence_id=node_evidence_id_map[item.node_id],
                source_unit_id=item.source_unit_ids[0] if len(item.source_unit_ids) == 1 else None,
                source_anchors=tuple(item.anchors),
                processing_run_ref=spr.processing_run_ref,
                raw_result_ref=spr.raw_result_ref,
                structured_processing_result_ref=context.structured_processing_result_ref,
                spr_node_ref=item.node_id,
            )
        )

    node_id_map = {
        item.node_id: _ref("scn", context.candidate_id, item.node_id)
        for item in spr.nodes
    }
    sibling_order = _sibling_orders(spr)

    warnings: list[ContentWarningV2] = []
    warning_by_spr_node: dict[str, str] = {}
    for item in spr.nodes:
        if item.kind is ProcessingNodeKind.UNKNOWN:
            warning_id = _ref("scw", context.candidate_id, policy.unknown_node_warning_code, item.node_id)
            warning_by_spr_node[item.node_id] = warning_id
            warnings.append(
                ContentWarningV2(
                    warning_id=warning_id,
                    code=policy.unknown_node_warning_code,
                    severity=WarningSeverityV2.WARNING,
                    scope_ref=node_id_map[item.node_id],
                    safe_summary="The processing result contained an unknown semantic element kind.",
                    evidence_ids=(node_evidence_id_map[item.node_id],),
                    recoverable=True,
                )
            )

    nodes: list[ContentNodeV2] = []
    for item in sorted(spr.nodes, key=lambda value: (value.order, value.node_id)):
        node_type = _NODE_TYPE_MAP[item.kind]
        heading_level = item.heading_level
        if item.kind is ProcessingNodeKind.TITLE:
            heading_level = item.heading_level or 1

        mapped_evidence = {node_evidence_id_map[item.node_id]}
        mapped_evidence.update(spr_evidence_id_map[evidence_id] for evidence_id in item.evidence_ids)
        mapped_evidence.update(observation_evidence_id_map[observation_id] for observation_id in item.observation_ids)

        ordered_unit_ids = tuple(
            sorted(item.source_unit_ids, key=lambda unit_id: (source_order[unit_id], unit_id))
        )
        warning_ids = ()
        if item.node_id in warning_by_spr_node:
            warning_ids = (warning_by_spr_node[item.node_id],)

        nodes.append(
            ContentNodeV2(
                node_id=node_id_map[item.node_id],
                lineage_key=_ref("scl", context.lineage_key, item.node_id),
                node_type=node_type,
                source_unit_ids=ordered_unit_ids,
                sibling_order=sibling_order[item.node_id],
                recovery_state=_node_recovery(item.recovery_state),
                parent_id=node_id_map[item.parent_id] if item.parent_id is not None else None,
                text=_normalize_text(item.text),
                heading_level=heading_level if node_type is ContentNodeTypeV2.HEADING else None,
                source_anchors=tuple(item.anchors),
                evidence_ids=tuple(sorted(mapped_evidence)),
                warning_ids=warning_ids,
                metadata={"spr_node_kind": item.kind.value, **(item.metadata or {})},
            )
        )

    warning_ids = tuple(sorted(warning.warning_id for warning in warnings))
    candidate = StructuredContentCandidateV2(
        document_ref=context.document_ref,
        candidate_id=context.candidate_id,
        lineage_key=context.lineage_key,
        recovery_summary=_content_recovery_summary(spr, warning_ids, policy),
        source_units=source_units,
        nodes=tuple(nodes),
        evidence=tuple(evidence),
        warnings=tuple(warnings),
        transformer_ref=policy.transformer_ref,
        transformation_policy_ref=policy.transformation_policy_ref,
        processing_run_ref=spr.processing_run_ref,
        raw_result_ref=spr.raw_result_ref,
        structured_processing_result_ref=context.structured_processing_result_ref,
    )
    return validate_candidate_v2(candidate)