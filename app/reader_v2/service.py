"""Selected Structured Content v2 -> deterministic Reader v2 projection."""
from __future__ import annotations

from collections import defaultdict

from app.source_units import SourceUnitKind, SourceUnitRecoveryState
from app.structured_content_v2.model import (
    ContentNodeTypeV2,
    ContentRecoveryStateV2,
    NodeRecoveryStateV2,
    StructuredContentCandidateV2,
)
from app.structured_content_v2.repository import StructuredContentCandidateV2Repository
from app.structured_content_v2.selection import (
    StructuredContentV2SelectionNotFound,
    StructuredContentV2SelectionRepository,
)

from .contracts import (
    REFLOWABLE_SOURCE_UNIT_KINDS,
    ReaderDocumentMetadataV2,
    ReaderDocumentViewV2,
    ReaderLocationV2,
    ReaderNavigationEntryV2,
    ReaderNodeViewV2,
    ReaderSourceUnitViewV2,
    ReaderV2ContentState,
    ReaderV2Warning,
    ReaderV2WarningCode,
)


class ReaderV2ServiceError(RuntimeError):
    pass


class NoSelectedReaderV2Content(ReaderV2ServiceError):
    pass


class SelectedReaderV2CandidateDocumentMismatch(ReaderV2ServiceError):
    pass


def _location(candidate: StructuredContentCandidateV2, *, node=None) -> ReaderLocationV2:
    source_unit_id = None
    source_anchor = None
    node_id = None
    if node is not None:
        node_id = node.node_id
        if node.source_anchors:
            source_anchor = node.source_anchors[0]
            source_unit_id = source_anchor.source_unit_id
        elif node.source_unit_ids:
            source_unit_id = node.source_unit_ids[0]
    return ReaderLocationV2(
        document_ref=candidate.document_ref,
        candidate_id=candidate.candidate_id,
        candidate_schema_id=candidate.schema_id,
        candidate_schema_version=candidate.schema_version,
        node_id=node_id,
        source_unit_id=source_unit_id,
        source_anchor=source_anchor,
    )


def _document_state(candidate: StructuredContentCandidateV2) -> ReaderV2ContentState:
    if candidate.recovery_summary.total_source_units and (
        candidate.recovery_summary.no_usable_semantic_content_source_units
        == candidate.recovery_summary.total_source_units
    ):
        return ReaderV2ContentState.NO_USABLE_SEMANTIC_CONTENT
    return {
        ContentRecoveryStateV2.COMPLETE: ReaderV2ContentState.READY,
        ContentRecoveryStateV2.DEGRADED: ReaderV2ContentState.DEGRADED,
        ContentRecoveryStateV2.UNAVAILABLE: ReaderV2ContentState.UNAVAILABLE,
    }[candidate.recovery_summary.state]


def _unit_state(state: SourceUnitRecoveryState) -> ReaderV2ContentState:
    return {
        SourceUnitRecoveryState.COMPLETE: ReaderV2ContentState.READY,
        SourceUnitRecoveryState.DEGRADED: ReaderV2ContentState.DEGRADED,
        SourceUnitRecoveryState.NO_USABLE_SEMANTIC_CONTENT: ReaderV2ContentState.NO_USABLE_SEMANTIC_CONTENT,
        SourceUnitRecoveryState.UNAVAILABLE: ReaderV2ContentState.UNAVAILABLE,
    }[state]


def _node_state(state: NodeRecoveryStateV2) -> ReaderV2ContentState:
    return {
        NodeRecoveryStateV2.COMPLETE: ReaderV2ContentState.READY,
        NodeRecoveryStateV2.DEGRADED: ReaderV2ContentState.DEGRADED,
        NodeRecoveryStateV2.RECOVERED: ReaderV2ContentState.DEGRADED,
        NodeRecoveryStateV2.UNAVAILABLE: ReaderV2ContentState.UNAVAILABLE,
    }[state]


def _warning_code(code: str) -> ReaderV2WarningCode:
    normalized = code.upper()
    if "ASSET" in normalized:
        return ReaderV2WarningCode.ASSET_UNAVAILABLE
    if "UNAVAILABLE" in normalized or "MISSING" in normalized:
        return ReaderV2WarningCode.CONTENT_UNAVAILABLE
    return ReaderV2WarningCode.CONTENT_DEGRADED


def _warnings(candidate: StructuredContentCandidateV2, warning_ids: tuple[str, ...]) -> tuple[ReaderV2Warning, ...]:
    by_id = {warning.warning_id: warning for warning in candidate.warnings}
    return tuple(
        ReaderV2Warning(_warning_code(by_id[warning_id].code))
        for warning_id in warning_ids
        if warning_id in by_id
    )


def _preorder_nodes(candidate: StructuredContentCandidateV2):
    by_parent = defaultdict(list)
    by_id = {node.node_id: node for node in candidate.nodes}
    for node in candidate.nodes:
        by_parent[node.parent_id].append(node)
    for children in by_parent.values():
        children.sort(key=lambda node: (node.sibling_order, node.node_id))

    ordered = []

    def visit(node):
        ordered.append(node)
        for child in by_parent.get(node.node_id, ()):  # canonical graph validation rejects cycles
            visit(child)

    for root in by_parent.get(None, ()):
        visit(root)

    if len(ordered) != len(by_id):
        raise ReaderV2ServiceError("selected candidate semantic hierarchy is incomplete")
    return tuple(ordered), by_parent


def build_selected_reader_v2_document(
    *,
    session,
    document_ref: str,
    candidate_repository: StructuredContentCandidateV2Repository | None = None,
    selection_repository: StructuredContentV2SelectionRepository | None = None,
) -> ReaderDocumentViewV2:
    candidates = candidate_repository or StructuredContentCandidateV2Repository()
    selections = selection_repository or StructuredContentV2SelectionRepository(candidates)

    try:
        selection = selections.get_selection(session, document_ref)
    except StructuredContentV2SelectionNotFound as exc:
        raise NoSelectedReaderV2Content(
            f"no selected Structured Content v2 candidate for document {document_ref}"
        ) from exc

    candidate = candidates.get_candidate(session, selection.candidate_id)
    if candidate.document_ref != document_ref:
        raise SelectedReaderV2CandidateDocumentMismatch(
            f"selected candidate {selection.candidate_id} does not belong to document {document_ref}"
        )

    ordered_nodes, children_by_parent = _preorder_nodes(candidate)
    source_units = tuple(
        ReaderSourceUnitViewV2(
            source_unit=item.source_unit,
            content_state=_unit_state(item.source_unit.recovery_state),
            warnings=_warnings(candidate, item.warning_ids),
        )
        for item in sorted(
            candidate.source_units,
            key=lambda item: (item.source_unit.source_order, item.source_unit.source_unit_id),
        )
    )

    node_views: list[ReaderNodeViewV2] = []
    for order, node in enumerate(ordered_nodes):
        node_views.append(
            ReaderNodeViewV2(
                location=_location(candidate, node=node),
                node_id=node.node_id,
                node_type=node.node_type,
                order=order,
                content_state=_node_state(node.recovery_state),
                source_unit_ids=node.source_unit_ids,
                source_anchors=node.source_anchors,
                text=node.text,
                heading_level=node.heading_level,
                parent_ref=node.parent_id,
                child_refs=tuple(child.node_id for child in children_by_parent.get(node.node_id, ())),
                asset_refs=node.asset_ids,
                warnings=_warnings(candidate, node.warning_ids),
                metadata=node.metadata,
            )
        )

    navigation = tuple(
        ReaderNavigationEntryV2(
            location=view.location,
            label=view.text or "Untitled heading",
            order=index,
            heading_level=view.heading_level or 1,
        )
        for index, view in enumerate(view for view in node_views if view.node_type is ContentNodeTypeV2.HEADING)
    )

    physical_pages = sum(
        1 for item in source_units if item.source_unit.kind is SourceUnitKind.PHYSICAL_PAGE
    )
    reflowable = sum(
        1 for item in source_units if item.source_unit.kind in REFLOWABLE_SOURCE_UNIT_KINDS
    )

    return ReaderDocumentViewV2(
        document_ref=candidate.document_ref,
        candidate_id=candidate.candidate_id,
        candidate_schema_id=candidate.schema_id,
        candidate_schema_version=candidate.schema_version,
        content_state=_document_state(candidate),
        source_units=source_units,
        nodes=tuple(node_views),
        navigation=navigation,
        metadata=ReaderDocumentMetadataV2(
            source_unit_count=len(source_units),
            physical_page_count=physical_pages,
            reflowable_source_unit_count=reflowable,
        ),
        warnings=_warnings(candidate, candidate.recovery_summary.warning_ids),
    )


__all__ = [
    "NoSelectedReaderV2Content",
    "ReaderV2ServiceError",
    "SelectedReaderV2CandidateDocumentMismatch",
    "build_selected_reader_v2_document",
]