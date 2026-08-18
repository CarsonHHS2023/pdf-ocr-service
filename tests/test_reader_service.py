from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from app.reader import (
    NoSelectedReaderContent,
    ReaderContentState,
    ReaderProcessingState,
    ReaderServiceError,
    SelectedReaderCandidateDocumentMismatch,
    build_selected_reader_document,
    serialize_reader_contract,
    validate_reader_document,
)
from app.structured_content.enums import ContentNodeType, ContentRecoveryState, NodeRecoveryState, PageRecoveryState
from app.structured_content.identity import ContentCandidateId, ContentLineageKey, DocumentRef
from app.structured_content.model import ContentRecoverySummary, HeadingAttributes
from app.structured_content.repository import StructuredContentCandidateRepository
from app.structured_content.selection_repository import StructuredContentSelectionRepository
from tests.structured_content.candidate_factory import make_linear_candidate, make_wide_hierarchy
from tests.structured_content.integration_factory import add_document, candidate_for, sqlite_session


def _repos():
    candidates = StructuredContentCandidateRepository()
    selections = StructuredContentSelectionRepository(candidates)
    return candidates, selections


def _build(session, candidates, selections, document_ref: str = "doc"):
    return build_selected_reader_document(
        session=session,
        document_ref=document_ref,
        candidate_repository=candidates,
        selection_repository=selections,
    )


def _with_identity(candidate, *, document_ref: str, candidate_id: str):
    return replace(
        candidate,
        document_ref=DocumentRef(document_ref),
        candidate_id=ContentCandidateId(candidate_id),
        lineage_key=ContentLineageKey(f"lineage-{candidate_id}"),
    )


def test_reader_service_requires_explicit_selection_and_never_falls_back_to_latest():
    session, _ = sqlite_session()
    candidates, selections = _repos()
    add_document(session, "doc", source_file_id="source-file")

    first = candidate_for("doc", "candidate-a", pages=1, nodes=2)
    second = candidate_for("doc", "candidate-b", pages=1, nodes=2)
    candidates.create_candidate(session, first)

    with pytest.raises(NoSelectedReaderContent):
        _build(session, candidates, selections)

    selections.set_selection(session, document_ref="doc", candidate_id="candidate-a", expected_version=0)
    selected = _build(session, candidates, selections)
    assert selected.candidate_id == first.candidate_id

    candidates.create_candidate(session, second)
    repeated = _build(session, candidates, selections)
    assert repeated == selected
    assert repeated.candidate_id == first.candidate_id
    assert selections.get_selection(session, "doc").candidate_id == "candidate-a"


def test_reader_service_is_deterministic_and_reselection_changes_only_explicit_selection():
    session, _ = sqlite_session()
    candidates, selections = _repos()
    add_document(session, "doc", source_file_id="source-file")

    first = candidate_for("doc", "candidate-a", pages=2, nodes=3)
    second = candidate_for("doc", "candidate-b", pages=2, nodes=3)
    second = replace(second, nodes=tuple(replace(node, text=f"B {index}") for index, node in enumerate(second.nodes)))
    candidates.create_candidate(session, first)
    candidates.create_candidate(session, second)

    selections.set_selection(session, document_ref="doc", candidate_id="candidate-a", expected_version=0)
    a_first = _build(session, candidates, selections)
    assert all(_build(session, candidates, selections) == a_first for _ in range(3))
    assert serialize_reader_contract(a_first) == serialize_reader_contract(_build(session, candidates, selections))

    selections.set_selection(session, document_ref="doc", candidate_id="candidate-b", expected_version=1)
    b_view = _build(session, candidates, selections)
    assert b_view.candidate_id == second.candidate_id
    assert [node.text for page in b_view.pages for node in page.nodes] == [f"B {i}" for i in range(6)]
    assert b_view != a_first


def test_reader_service_maps_hierarchy_heading_navigation_locations_and_assets():
    session, _ = sqlite_session()
    candidates, selections = _repos()
    add_document(session, "doc", source_file_id="source-file")

    candidate = _with_identity(make_wide_hierarchy(2), document_ref="doc", candidate_id="candidate-heading")
    root = replace(
        candidate.nodes[0],
        node_type=ContentNodeType.HEADING,
        attributes=HeadingAttributes(level=2),
        text="Chapter",
    )
    candidate = replace(candidate, nodes=(root,) + candidate.nodes[1:])
    candidates.create_candidate(session, candidate)
    selections.set_selection(session, document_ref="doc", candidate_id="candidate-heading", expected_version=0)

    view = _build(session, candidates, selections)
    assert validate_reader_document(view) is None
    assert view.processing_state is ReaderProcessingState.COMPLETED
    assert view.document_ref == candidate.document_ref
    assert view.candidate_id == candidate.candidate_id
    assert view.metadata.page_count == 1
    assert len(view.pages) == 1

    page = view.pages[0]
    assert [node.order for node in page.nodes] == [0, 1, 2]
    assert page.nodes[0].child_refs == (page.nodes[1].node_id, page.nodes[2].node_id)
    assert page.nodes[1].parent_ref == page.nodes[0].node_id
    assert page.nodes[0].location.page_id == page.page_id
    assert page.nodes[0].location.candidate_id == candidate.candidate_id

    assert len(view.navigation) == 1
    entry = view.navigation[0]
    assert entry.label == "Chapter"
    assert entry.heading_level == 2
    assert entry.location == page.nodes[0].location


@pytest.mark.parametrize("level", [1, 6])
def test_reader_service_preserves_reader_representable_heading_levels(level):
    session, _ = sqlite_session()
    candidates, selections = _repos()
    add_document(session, "doc", source_file_id="source-file")

    candidate = _with_identity(make_wide_hierarchy(1), document_ref="doc", candidate_id=f"candidate-heading-{level}")
    root = replace(
        candidate.nodes[0],
        node_type=ContentNodeType.HEADING,
        attributes=HeadingAttributes(level=level),
        text=f"Heading {level}",
    )
    candidate = replace(candidate, nodes=(root,) + candidate.nodes[1:])
    candidates.create_candidate(session, candidate)
    selections.set_selection(session, document_ref="doc", candidate_id=candidate.candidate_id, expected_version=0)

    view = _build(session, candidates, selections)
    assert view.pages[0].nodes[0].heading_level == level
    assert view.navigation[0].heading_level == level


def test_reader_service_rejects_heading_level_not_representable_by_reader_contract():
    session, _ = sqlite_session()
    candidates, selections = _repos()
    add_document(session, "doc", source_file_id="source-file")

    candidate = _with_identity(make_wide_hierarchy(1), document_ref="doc", candidate_id="candidate-heading-7")
    root = replace(
        candidate.nodes[0],
        node_type=ContentNodeType.HEADING,
        attributes=HeadingAttributes(level=7),
        text="Deep heading",
    )
    candidate = replace(candidate, nodes=(root,) + candidate.nodes[1:])
    candidates.create_candidate(session, candidate)
    selections.set_selection(session, document_ref="doc", candidate_id="candidate-heading-7", expected_version=0)

    with pytest.raises(ReaderServiceError, match="not representable"):
        _build(session, candidates, selections)


def test_reader_service_maps_partial_recovery_without_collapsing_it_to_degraded():
    session, _ = sqlite_session()
    candidates, selections = _repos()
    add_document(session, "doc", source_file_id="source-file")

    candidate = _with_identity(make_linear_candidate(1, 2), document_ref="doc", candidate_id="candidate-partial")
    page = replace(candidate.pages[0], recovery_state=PageRecoveryState.PARTIAL)
    nodes = tuple(replace(node, recovery_state=NodeRecoveryState.PARTIAL) for node in candidate.nodes)
    summary = ContentRecoverySummary(
        ContentRecoveryState.PARTIAL,
        total_pages=1,
        partial_pages=1,
    )
    candidate = replace(candidate, pages=(page,), nodes=nodes, recovery_summary=summary)
    candidates.create_candidate(session, candidate)
    selections.set_selection(session, document_ref="doc", candidate_id="candidate-partial", expected_version=0)

    view = _build(session, candidates, selections)
    assert view.content_state is ReaderContentState.PARTIAL
    assert view.pages[0].content_state is ReaderContentState.PARTIAL
    assert all(node.content_state is ReaderContentState.PARTIAL for node in view.pages[0].nodes)
    assert validate_reader_document(view) is None


def test_reader_service_rejects_selected_candidate_document_mismatch_before_assembly():
    source = _with_identity(make_linear_candidate(1, 1), document_ref="other-doc", candidate_id="candidate-x")

    class Selection:
        candidate_id = "candidate-x"

    class Selections:
        def get_selection(self, session, document_ref):
            return Selection()

    class Candidates:
        def get_candidate(self, session, candidate_id):
            return source

    with pytest.raises(SelectedReaderCandidateDocumentMismatch):
        build_selected_reader_document(
            session=object(),
            document_ref="doc",
            candidate_repository=Candidates(),  # type: ignore[arg-type]
            selection_repository=Selections(),  # type: ignore[arg-type]
        )


def test_reader_service_does_not_depend_on_legacy_projection_provider_routes_or_persistence():
    service = Path("app/reader/service.py").read_text(encoding="utf-8")
    forbidden = (
        "structured_document.projection",
        "ReaderContentStreamV2Projection",
        "MineruResult",
        "ContentBlock",
        "PdfPage",
        "BookImage",
        "FastAPI",
        "APIRouter",
        "app.routers",
        "modal",
        "paddle",
        "requests",
        "httpx",
        "boto3",
    )
    assert not any(token in service for token in forbidden)
