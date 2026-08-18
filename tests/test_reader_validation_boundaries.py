from __future__ import annotations

import pytest

from app.reader import (
    ReaderContentChunk,
    ReaderContentState,
    ReaderContractError,
    ReaderDocumentMetadata,
    ReaderDocumentView,
    ReaderLocation,
    ReaderNavigationEntry,
    ReaderNodeView,
    ReaderPageView,
    ReaderProcessingState,
    validate_reader_content_chunk,
    validate_reader_document,
    validate_reader_node,
    validate_reader_page,
)
from app.structured_content.enums import ContentNodeType
from app.structured_content.identity import ContentCandidateId, ContentNodeId, ContentPageId, DocumentRef
from app.structured_content.model import SCHEMA_ID, SCHEMA_VERSION


def _location(*, page: str | None = None, node: str | None = None) -> ReaderLocation:
    return ReaderLocation(
        document_ref=DocumentRef("document-1"),
        candidate_id=ContentCandidateId("candidate-1"),
        candidate_schema_id=SCHEMA_ID,
        candidate_schema_version=SCHEMA_VERSION,
        page_id=ContentPageId(page) if page is not None else None,
        node_id=ContentNodeId(node) if node is not None else None,
    )


def _node() -> ReaderNodeView:
    return ReaderNodeView(
        location=_location(page="page-0", node="node-0"),
        node_id=ContentNodeId("node-0"),
        node_type=ContentNodeType.HEADING,
        order=0,
        content_state=ReaderContentState.READY,
        text="Heading",
        heading_level=1,
    )


def _page(*, nodes: tuple[ReaderNodeView, ...] | list[ReaderNodeView] | None = None) -> ReaderPageView:
    return ReaderPageView(
        location=_location(page="page-0"),
        page_id=ContentPageId("page-0"),
        page_order=0,
        content_state=ReaderContentState.READY,
        nodes=(_node(),) if nodes is None else nodes,  # type: ignore[arg-type]
    )


def _document(
    *,
    pages: tuple[ReaderPageView, ...] | list[ReaderPageView] | None = None,
    navigation: tuple[ReaderNavigationEntry, ...] | list[ReaderNavigationEntry] | None = None,
) -> ReaderDocumentView:
    source_pages = (_page(),) if pages is None else pages
    source_navigation = (
        ReaderNavigationEntry(_location(page="page-0", node="node-0"), "Heading", 0, 1),
    ) if navigation is None else navigation
    return ReaderDocumentView(
        document_ref=DocumentRef("document-1"),
        candidate_id=ContentCandidateId("candidate-1"),
        candidate_schema_id=SCHEMA_ID,
        candidate_schema_version=SCHEMA_VERSION,
        processing_state=ReaderProcessingState.COMPLETED,
        content_state=ReaderContentState.READY,
        metadata=ReaderDocumentMetadata(title="Document", page_count=1),
        pages=source_pages,  # type: ignore[arg-type]
        navigation=source_navigation,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize("malformed_location", (None, object(), 1, [], {}))
def test_node_page_context_validates_page_location_before_source_dereference(
    malformed_location: object,
) -> None:
    context = _page()
    object.__setattr__(context, "location", malformed_location)

    with pytest.raises(ReaderContractError):
        validate_reader_node(_node(), context)


def test_page_rejects_mutated_list_nodes() -> None:
    value = _page()
    object.__setattr__(value, "nodes", list(value.nodes))

    with pytest.raises(ReaderContractError, match="nodes must be an immutable tuple") as exc:
        validate_reader_page(value)
    assert exc.value.code.value == "invalid_page"


def test_document_rejects_mutated_list_pages() -> None:
    value = _document()
    object.__setattr__(value, "pages", list(value.pages))

    with pytest.raises(ReaderContractError, match="pages must be an immutable tuple") as exc:
        validate_reader_document(value)
    assert exc.value.code.value == "invalid_document"


def test_document_rejects_mutated_list_navigation() -> None:
    value = _document()
    object.__setattr__(value, "navigation", list(value.navigation))

    with pytest.raises(ReaderContractError, match="navigation must be an immutable tuple") as exc:
        validate_reader_document(value)
    assert exc.value.code.value == "invalid_document"


def test_chunk_rejects_mutated_list_pages() -> None:
    value = ReaderContentChunk(
        DocumentRef("document-1"),
        ContentCandidateId("candidate-1"),
        SCHEMA_ID,
        SCHEMA_VERSION,
        (_page(),),
        False,
    )
    object.__setattr__(value, "pages", list(value.pages))

    with pytest.raises(ReaderContractError, match="pages must be an immutable tuple") as exc:
        validate_reader_content_chunk(value)
    assert exc.value.code.value == "invalid_chunk"


def test_constructor_source_lists_are_canonicalized_to_tuples() -> None:
    source_nodes = [_node()]
    page_value = _page(nodes=source_nodes)
    assert isinstance(page_value.nodes, tuple)
    assert validate_reader_page(page_value) is None

    source_pages = [page_value]
    source_navigation = [
        ReaderNavigationEntry(_location(page="page-0", node="node-0"), "Heading", 0, 1)
    ]
    document_value = _document(pages=source_pages, navigation=source_navigation)
    assert isinstance(document_value.pages, tuple)
    assert isinstance(document_value.navigation, tuple)
    assert validate_reader_document(document_value) is None

    chunk_value = ReaderContentChunk(
        DocumentRef("document-1"),
        ContentCandidateId("candidate-1"),
        SCHEMA_ID,
        SCHEMA_VERSION,
        source_pages,  # type: ignore[arg-type]
        False,
    )
    assert isinstance(chunk_value.pages, tuple)
    assert validate_reader_content_chunk(chunk_value) is None
