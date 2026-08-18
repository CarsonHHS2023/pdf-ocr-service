from __future__ import annotations

from app.structured_content.enums import (
    ContentNodeType,
    ContentRecoveryState,
    NodeRecoveryState,
    PageRecoveryState,
)
from app.structured_content.identity import ContentNodeId, DocumentRef
from app.structured_content.model import HeadingAttributes, StructuredContentCandidate
from app.structured_content.persistence_mapping import sval
from app.structured_content.repository import StructuredContentCandidateRepository
from app.structured_content.selection_repository import StructuredContentSelectionRepository
from app.structured_document.assembler import assemble_structured_document
from app.structured_document.types import (
    DEFAULT_STRUCTURED_DOCUMENT_ASSEMBLY_POLICY,
    StructuredDocument,
    StructuredDocumentAssemblyPolicy,
)

from .contracts import (
    ReaderContentState,
    ReaderDocumentMetadata,
    ReaderDocumentView,
    ReaderLocation,
    ReaderNavigationEntry,
    ReaderNodeView,
    ReaderPageView,
    ReaderProcessingState,
    ReaderWarning,
    ReaderWarningCode,
)
from .validation import validate_reader_document


class ReaderServiceError(Exception):
    """Base bounded error for Reader application-view orchestration."""


class NoSelectedReaderContent(ReaderServiceError):
    """Raised when a document has no explicit Structured Content selection."""


class SelectedReaderCandidateDocumentMismatch(ReaderServiceError):
    """Raised when the selected candidate does not belong to the requested document."""


def _location(
    candidate: StructuredContentCandidate,
    *,
    page_id=None,
    node_id=None,
) -> ReaderLocation:
    return ReaderLocation(
        document_ref=candidate.document_ref,
        candidate_id=candidate.candidate_id,
        candidate_schema_id=candidate.schema_id,
        candidate_schema_version=candidate.schema_version,
        page_id=page_id,
        node_id=node_id,
    )


def _document_state(candidate: StructuredContentCandidate) -> ReaderContentState:
    if candidate.pages and all(
        page.recovery_state is PageRecoveryState.NO_USABLE_SEMANTIC_CONTENT
        for page in candidate.pages
    ):
        return ReaderContentState.NO_USABLE_SEMANTIC_CONTENT
    mapping = {
        ContentRecoveryState.COMPLETE: ReaderContentState.READY,
        ContentRecoveryState.PARTIAL: ReaderContentState.PARTIAL,
        ContentRecoveryState.DEGRADED: ReaderContentState.DEGRADED,
        ContentRecoveryState.UNAVAILABLE: ReaderContentState.UNAVAILABLE,
    }
    return mapping[candidate.recovery_summary.state]


def _page_state(state: PageRecoveryState) -> ReaderContentState:
    mapping = {
        PageRecoveryState.COMPLETE: ReaderContentState.READY,
        PageRecoveryState.PARTIAL: ReaderContentState.PARTIAL,
        PageRecoveryState.DEGRADED: ReaderContentState.DEGRADED,
        PageRecoveryState.NO_USABLE_SEMANTIC_CONTENT: ReaderContentState.NO_USABLE_SEMANTIC_CONTENT,
        PageRecoveryState.UNAVAILABLE: ReaderContentState.UNAVAILABLE,
        PageRecoveryState.UNSUPPORTED: ReaderContentState.UNAVAILABLE,
    }
    return mapping[state]


def _node_state(state: NodeRecoveryState) -> ReaderContentState:
    mapping = {
        NodeRecoveryState.COMPLETE: ReaderContentState.READY,
        NodeRecoveryState.PARTIAL: ReaderContentState.PARTIAL,
        NodeRecoveryState.DEGRADED: ReaderContentState.DEGRADED,
        NodeRecoveryState.RECOVERED: ReaderContentState.DEGRADED,
        NodeRecoveryState.UNSUPPORTED: ReaderContentState.UNAVAILABLE,
    }
    return mapping[state]


def _warning_code(code: str) -> ReaderWarningCode:
    normalized = str(code).upper()
    if "ASSET" in normalized:
        return ReaderWarningCode.ASSET_UNAVAILABLE
    if "UNSUPPORTED" in normalized:
        return ReaderWarningCode.UNSUPPORTED_CONTENT
    if "UNAVAILABLE" in normalized or "MISSING" in normalized:
        return ReaderWarningCode.CONTENT_UNAVAILABLE
    return ReaderWarningCode.CONTENT_DEGRADED


def _warnings(candidate: StructuredContentCandidate, warning_ids: tuple[object, ...]) -> tuple[ReaderWarning, ...]:
    by_id = {warning.warning_id: warning for warning in candidate.warnings}
    return tuple(
        ReaderWarning(_warning_code(by_id[warning_id].code))
        for warning_id in warning_ids
        if warning_id in by_id
    )


def _reader_heading_level(attributes: object) -> int:
    if not isinstance(attributes, HeadingAttributes):
        raise ReaderServiceError("validated heading node is missing HeadingAttributes")
    level = attributes.level
    if not isinstance(level, int) or isinstance(level, bool) or not 1 <= level <= 6:
        raise ReaderServiceError("selected heading level is not representable by the Reader contract")
    return level


def _reader_pages(
    structured_document: StructuredDocument,
    candidate: StructuredContentCandidate,
) -> tuple[ReaderPageView, ...]:
    content_pages = {page.page_id: page for page in candidate.pages}
    content_nodes = {node.node_id: node for node in candidate.nodes}
    document_nodes = {view.source_node_id: view for view in structured_document.node_views}
    pages: list[ReaderPageView] = []

    for page_view in structured_document.pages:
        source_page = content_pages[page_view.source_page_id]
        page_state = _page_state(source_page.recovery_state)
        nodes: list[ReaderNodeView] = []

        if page_state not in {
            ReaderContentState.NO_USABLE_SEMANTIC_CONTENT,
            ReaderContentState.UNAVAILABLE,
        }:
            for order, node_id in enumerate(page_view.reading_order_node_refs):
                source_node = content_nodes[node_id]
                document_node = document_nodes[node_id]
                heading_level = None
                if source_node.node_type is ContentNodeType.HEADING:
                    heading_level = _reader_heading_level(source_node.attributes)
                nodes.append(
                    ReaderNodeView(
                        location=_location(candidate, page_id=source_page.page_id, node_id=source_node.node_id),
                        node_id=source_node.node_id,
                        node_type=source_node.node_type,
                        order=order,
                        content_state=_node_state(source_node.recovery_state),
                        text=source_node.text,
                        heading_level=heading_level,
                        parent_ref=document_node.parent_ref,
                        child_refs=document_node.child_refs,
                        asset_refs=source_node.asset_ids,
                        warnings=_warnings(candidate, source_node.warning_ids),
                    )
                )

        pages.append(
            ReaderPageView(
                location=_location(candidate, page_id=source_page.page_id),
                page_id=source_page.page_id,
                page_order=page_view.page_order,
                content_state=page_state,
                nodes=tuple(nodes),
                warnings=_warnings(candidate, source_page.warning_ids),
            )
        )

    return tuple(pages)


def _navigation(pages: tuple[ReaderPageView, ...]) -> tuple[ReaderNavigationEntry, ...]:
    entries: list[ReaderNavigationEntry] = []
    for page in pages:
        for node in page.nodes:
            if node.node_type is ContentNodeType.HEADING:
                if node.heading_level is None:
                    raise ReaderServiceError("mapped heading is missing a Reader heading level")
                entries.append(
                    ReaderNavigationEntry(
                        location=node.location,
                        label=node.text or "Untitled heading",
                        order=len(entries),
                        heading_level=node.heading_level,
                    )
                )
    return tuple(entries)


def build_selected_reader_document(
    *,
    session,
    document_ref: DocumentRef | str,
    candidate_repository: StructuredContentCandidateRepository | None = None,
    selection_repository: StructuredContentSelectionRepository | None = None,
    assembly_policy: StructuredDocumentAssemblyPolicy = DEFAULT_STRUCTURED_DOCUMENT_ASSEMBLY_POLICY,
) -> ReaderDocumentView:
    """Build a deterministic Reader application view for the explicit selection.

    The service performs selection lookup and candidate reconstruction, then
    assembles StructuredDocument and maps it directly into the M5 Reader
    application contract. It does not use Reader Content Stream v2, persist a
    Reader projection, mutate the selected candidate, or fall back to a latest
    candidate.
    """

    document_id = sval(document_ref)
    candidates = candidate_repository or StructuredContentCandidateRepository()
    selections = selection_repository or StructuredContentSelectionRepository(candidates)

    selection = selections.get_selection(session, document_id)
    if selection is None:
        raise NoSelectedReaderContent(
            f"no selected structured content candidate for document {document_id}"
        )

    candidate = candidates.get_candidate(session, selection.candidate_id)
    if sval(candidate.document_ref) != document_id:
        raise SelectedReaderCandidateDocumentMismatch(
            f"selected candidate {selection.candidate_id} does not belong to document {document_id}"
        )

    structured_document = assemble_structured_document(candidate, policy=assembly_policy)
    pages = _reader_pages(structured_document, candidate)
    view = ReaderDocumentView(
        document_ref=candidate.document_ref,
        candidate_id=candidate.candidate_id,
        candidate_schema_id=candidate.schema_id,
        candidate_schema_version=candidate.schema_version,
        processing_state=ReaderProcessingState.COMPLETED,
        content_state=_document_state(candidate),
        metadata=ReaderDocumentMetadata(
            title=None,
            page_count=candidate.recovery_summary.total_pages,
        ),
        pages=pages,
        navigation=_navigation(pages),
        warnings=_warnings(candidate, candidate.recovery_summary.warning_ids),
    )
    validate_reader_document(view)
    return view


__all__ = [
    "NoSelectedReaderContent",
    "ReaderServiceError",
    "SelectedReaderCandidateDocumentMismatch",
    "build_selected_reader_document",
]
