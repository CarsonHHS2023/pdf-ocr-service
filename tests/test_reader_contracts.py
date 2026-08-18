from __future__ import annotations

import copy
import json
from dataclasses import FrozenInstanceError
from enum import Enum
from pathlib import Path

import pytest

from app.reader import (
    READER_APPLICATION_CONTRACT_VERSION,
    ReaderContentChunk,
    ReaderContentState,
    ReaderContinuation,
    ReaderContractError,
    ReaderDocumentMetadata,
    ReaderDocumentView,
    ReaderLocation,
    ReaderNavigationEntry,
    ReaderNodeView,
    ReaderPageView,
    ReaderProcessingState,
    ReaderWarning,
    ReaderWarningCode,
    UnsupportedReaderContractVersion,
    serialize_reader_contract,
    to_reader_contract_dict,
    validate_navigation_entry,
    validate_reader_content_chunk,
    validate_reader_document,
    validate_reader_location,
    validate_reader_node,
    validate_reader_page,
)
from app.structured_content.enums import ContentNodeType, ContentRecoveryState
from app.structured_content.identity import AssetId, ContentCandidateId, ContentNodeId, ContentPageId, DocumentRef
from app.structured_content.model import SCHEMA_ID, SCHEMA_VERSION


def location(*, page: str | None = None, node: str | None = None, candidate: str = "candidate-1", segment: int | None = None) -> ReaderLocation:
    return ReaderLocation(
        document_ref=DocumentRef("document-1"),
        candidate_id=ContentCandidateId(candidate),
        candidate_schema_id=SCHEMA_ID,
        candidate_schema_version=SCHEMA_VERSION,
        page_id=ContentPageId(page) if page else None,
        node_id=ContentNodeId(node) if node else None,
        segment_index=segment,
    )


def page(number: int = 0, *, state: ReaderContentState = ReaderContentState.READY) -> ReaderPageView:
    page_id = f"page-{number}"
    node_id = f"node-{number}"
    node = ReaderNodeView(
        location=location(page=page_id, node=node_id),
        node_id=ContentNodeId(node_id),
        node_type=ContentNodeType.HEADING if number == 0 else ContentNodeType.PARAGRAPH,
        order=0,
        content_state=state,
        text="Heading" if number == 0 else "Text",
        heading_level=1 if number == 0 else None,
    )
    return ReaderPageView(location(page=page_id), ContentPageId(page_id), number, state, (node,))


def document(*pages: ReaderPageView, candidate: str = "candidate-1") -> ReaderDocumentView:
    navigation = ()
    if pages:
        navigation = (ReaderNavigationEntry(pages[0].nodes[0].location, "Heading", 0, 1),)
    return ReaderDocumentView(
        document_ref=DocumentRef("document-1"),
        candidate_id=ContentCandidateId(candidate),
        candidate_schema_id=SCHEMA_ID,
        candidate_schema_version=SCHEMA_VERSION,
        processing_state=ReaderProcessingState.COMPLETED,
        content_state=ReaderContentState.READY,
        metadata=ReaderDocumentMetadata(title="Document", page_count=len(pages)),
        pages=pages,
        navigation=navigation,
    )


def test_locations_are_immutable_version_bound_and_hierarchical() -> None:
    document_location = location()
    node_location = location(page="page-0", node="node-0")
    segment_location = location(page="page-0", node="node-0", segment=0)
    for value in (document_location, node_location, segment_location):
        assert validate_reader_location(value) is None
    with pytest.raises(FrozenInstanceError):
        node_location.node_id = ContentNodeId("other")  # type: ignore[misc]
    with pytest.raises(ReaderContractError, match="segment requires node"):
        validate_reader_location(location(page="page-0", segment=0))
    with pytest.raises(ReaderContractError, match="segment index must be nonnegative"):
        validate_reader_location(location(page="page-0", node="node-0", segment=-1))
    with pytest.raises(ReaderContractError, match="node requires page"):
        validate_reader_location(location(node="node-0"))
    with pytest.raises(UnsupportedReaderContractVersion):
        validate_reader_location(
            ReaderLocation(DocumentRef("document-1"), ContentCandidateId("candidate-1"), SCHEMA_ID, SCHEMA_VERSION, "2")
        )
    assert location(candidate="candidate-1") != location(candidate="candidate-2")
    assert hash(location(candidate="candidate-1")) == hash(copy.deepcopy(location(candidate="candidate-1")))
    assert not hasattr(document_location, "latest") and not hasattr(document_location, "current")


def test_document_page_node_navigation_and_collections_are_immutable() -> None:
    source_pages = [page(0), page(1, state=ReaderContentState.DEGRADED)]
    view = document(*source_pages)
    source_pages.clear()
    assert len(view.pages) == 2
    assert validate_reader_document(view) is None
    assert view.pages[1].content_state is ReaderContentState.DEGRADED
    for value, field, replacement in (
        (view, "pages", (),),
        (view.pages[0], "nodes", (),),
        (view.pages[0].nodes[0], "text", "changed"),
        (view.navigation[0], "label", "changed"),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(value, field, replacement)


def test_empty_document_and_processing_content_states_remain_independent() -> None:
    empty = ReaderDocumentView(
        DocumentRef("document-1"), ContentCandidateId("candidate-1"), SCHEMA_ID, SCHEMA_VERSION,
        ReaderProcessingState.COMPLETED, ReaderContentState.NO_USABLE_SEMANTIC_CONTENT,
    )
    assert validate_reader_document(empty) is None
    failed_with_degraded_content = ReaderDocumentView(
        DocumentRef("document-1"), ContentCandidateId("candidate-1"), SCHEMA_ID, SCHEMA_VERSION,
        ReaderProcessingState.FAILED, ReaderContentState.DEGRADED,
    )
    assert validate_reader_document(failed_with_degraded_content) is None
    assert failed_with_degraded_content.processing_state.value != failed_with_degraded_content.content_state.value
    assert tuple(ReaderWarning.__dataclass_fields__) == ("code",)
    assert ReaderWarning(ReaderWarningCode.CONTENT_DEGRADED).code is ReaderWarningCode.CONTENT_DEGRADED


def test_partial_recovery_is_distinct_valid_and_deterministically_serialized() -> None:
    partial_page = page(0, state=ReaderContentState.PARTIAL)
    object.__setattr__(partial_page.nodes[0], "content_state", ReaderContentState.PARTIAL)
    view = document(partial_page)
    object.__setattr__(view, "content_state", ReaderContentState.PARTIAL)
    assert validate_reader_document(view) is None
    assert ReaderContentState.PARTIAL is not ReaderContentState.DEGRADED
    assert ContentRecoveryState.PARTIAL.value == ReaderContentState.PARTIAL.value
    assert ContentRecoveryState.DEGRADED.value == ReaderContentState.DEGRADED.value
    assert json.loads(serialize_reader_contract(view))["content_state"] == "partial"
    assert json.loads(serialize_reader_contract(view))["pages"][0]["content_state"] == "partial"
    assert json.loads(serialize_reader_contract(view))["pages"][0]["nodes"][0]["content_state"] == "partial"

    object.__setattr__(view, "content_state", "partial")
    with pytest.raises(ReaderContractError, match="content state must be ReaderContentState"):
        validate_reader_document(view)


def test_no_usable_semantic_content_page_cannot_expose_reader_nodes() -> None:
    empty = ReaderPageView(
        location(page="page-0"), ContentPageId("page-0"), 0,
        ReaderContentState.NO_USABLE_SEMANTIC_CONTENT, (),
    )
    assert validate_reader_page(empty) is None

    for state in (ReaderContentState.READY, ReaderContentState.PARTIAL, ReaderContentState.DEGRADED):
        contradictory = page(0, state=ReaderContentState.NO_USABLE_SEMANTIC_CONTENT)
        object.__setattr__(contradictory.nodes[0], "content_state", state)
        with pytest.raises(ReaderContractError, match="must not contain nodes"):
            validate_reader_page(contradictory)

    for state in (ReaderContentState.READY, ReaderContentState.PARTIAL, ReaderContentState.DEGRADED):
        usable = page(0, state=state)
        object.__setattr__(usable.nodes[0], "content_state", state)
        assert validate_reader_page(usable) is None


def test_unavailable_page_cannot_expose_reader_nodes() -> None:
    empty = ReaderPageView(
        location(page="page-0"), ContentPageId("page-0"), 0,
        ReaderContentState.UNAVAILABLE, (),
    )
    assert validate_reader_page(empty) is None

    contradictory = page(0, state=ReaderContentState.UNAVAILABLE)
    with pytest.raises(ReaderContractError, match="non-content-bearing page must not contain nodes"):
        validate_reader_page(contradictory)


@pytest.mark.parametrize("malformed", ([], {}, 1, None, "999"))
@pytest.mark.parametrize("kind", ("location", "document", "chunk"))
def test_contract_version_failures_are_bounded_for_every_public_validator(
    malformed: object, kind: str
) -> None:
    if kind == "location":
        value = location()
        validator = validate_reader_location
    elif kind == "document":
        value = document()
        validator = validate_reader_document
    else:
        value = ReaderContentChunk(
            DocumentRef("document-1"), ContentCandidateId("candidate-1"), SCHEMA_ID, SCHEMA_VERSION, (), False
        )
        validator = validate_reader_content_chunk
    object.__setattr__(value, "contract_version", malformed)
    with pytest.raises(UnsupportedReaderContractVersion):
        validator(value)  # type: ignore[arg-type]

    supported = location()
    assert validate_reader_location(supported) is None


@pytest.mark.parametrize(
    "validator,error_code",
    (
        (validate_reader_document, "invalid_document"),
        (validate_reader_content_chunk, "invalid_chunk"),
        (validate_navigation_entry, "invalid_navigation"),
    ),
)
@pytest.mark.parametrize("malformed", (object(), None, 1, [], {}))
def test_public_root_validators_reject_malformed_values_before_dereference(
    validator: object, error_code: str, malformed: object
) -> None:
    with pytest.raises(ReaderContractError) as exc:
        validator(malformed)  # type: ignore[operator]
    assert exc.value.code.value == error_code


def test_document_validation_rejects_identity_order_and_navigation_conflicts() -> None:
    first = page(0)
    mismatched = ReaderPageView(location(page="page-1", candidate="other"), ContentPageId("page-1"), 1, ReaderContentState.READY)
    with pytest.raises(ReaderContractError, match="source identity mismatch"):
        validate_reader_document(document(first, mismatched))

    duplicate_nav = document(first)
    object.__setattr__(duplicate_nav, "navigation", duplicate_nav.navigation * 2)
    with pytest.raises(ReaderContractError, match="navigation order invalid"):
        validate_reader_document(duplicate_nav)

    invalid_level = document(first)
    object.__setattr__(invalid_level.navigation[0], "heading_level", 7)
    with pytest.raises(ReaderContractError, match="heading level"):
        validate_reader_document(invalid_level)


def test_document_metadata_page_count_allows_empty_and_bounded_page_views() -> None:
    metadata_only = document()
    object.__setattr__(metadata_only, "metadata", ReaderDocumentMetadata(title="Document", page_count=100))
    assert validate_reader_document(metadata_only) is None

    bounded_page = page(0)
    object.__setattr__(bounded_page, "page_order", 5)
    bounded = document(bounded_page)
    object.__setattr__(bounded, "metadata", ReaderDocumentMetadata(title="Document", page_count=100))
    assert validate_reader_document(bounded) is None

    impossible_page = page(0)
    object.__setattr__(impossible_page, "page_order", 5)
    impossible = document(impossible_page)
    object.__setattr__(impossible, "metadata", ReaderDocumentMetadata(title="Document", page_count=5))
    with pytest.raises(ReaderContractError, match="embedded page order exceeds document page count"):
        validate_reader_document(impossible)

    assert validate_reader_document(document(page(0), page(1))) is None


def test_navigation_target_must_exist_within_its_exact_page() -> None:
    pages = (page(0), page(1))
    assert validate_reader_document(document(*pages)) is None

    view = document(*pages)
    object.__setattr__(
        view,
        "navigation",
        (ReaderNavigationEntry(location(page="page-X", node="node-0"), "Remote", 0, 1),),
    )
    assert validate_reader_document(view) is None

    invalid_embedded_targets = (
        location(page="page-1", node="node-0"),
        location(page="page-0", node="node-X"),
    )
    for target in invalid_embedded_targets:
        view = document(*pages)
        object.__setattr__(view, "navigation", (ReaderNavigationEntry(target, "Heading", 0, 1),))
        with pytest.raises(ReaderContractError, match="navigation target invalid on embedded page"):
            validate_reader_document(view)

    duplicate = document(*pages)
    target = duplicate.navigation[0]
    object.__setattr__(duplicate, "navigation", (target, ReaderNavigationEntry(target.location, "Again", 1, 1)))
    with pytest.raises(ReaderContractError, match="duplicate navigation target"):
        validate_reader_document(duplicate)


def test_navigation_target_must_be_heading_with_matching_level() -> None:
    paragraph_page = page(0)
    object.__setattr__(paragraph_page.nodes[0], "node_type", ContentNodeType.PARAGRAPH)
    object.__setattr__(paragraph_page.nodes[0], "heading_level", None)
    paragraph_view = document(paragraph_page)
    object.__setattr__(
        paragraph_view,
        "navigation",
        (ReaderNavigationEntry(paragraph_page.nodes[0].location, "Paragraph", 0, 1),),
    )
    with pytest.raises(ReaderContractError, match="navigation target must be a heading"):
        validate_reader_document(paragraph_view)

    heading_page = page(0)
    mismatch = document(heading_page)
    object.__setattr__(mismatch.navigation[0], "heading_level", 2)
    with pytest.raises(ReaderContractError, match="navigation heading level mismatch"):
        validate_reader_document(mismatch)

    missing_level = document(page(0))
    object.__setattr__(missing_level.pages[0].nodes[0], "heading_level", None)
    with pytest.raises(ReaderContractError, match="heading node requires level"):
        validate_reader_document(missing_level)


def test_navigation_may_target_nonembedded_pages_in_bounded_views() -> None:
    navigation_only = document()
    object.__setattr__(navigation_only, "metadata", ReaderDocumentMetadata(title="Document", page_count=100))
    object.__setattr__(
        navigation_only,
        "navigation",
        (
            ReaderNavigationEntry(location(page="page-1", node="heading-1"), "One", 0, 1),
            ReaderNavigationEntry(location(page="page-80", node="heading-80"), "Eighty", 1, 2),
        ),
    )
    assert validate_reader_document(navigation_only) is None

    embedded_page = page(0)
    bounded = document(embedded_page)
    object.__setattr__(bounded, "metadata", ReaderDocumentMetadata(title="Document", page_count=100))
    object.__setattr__(
        bounded,
        "navigation",
        (
            ReaderNavigationEntry(embedded_page.nodes[0].location, "Embedded", 0, 1),
            ReaderNavigationEntry(location(page="page-20", node="heading-20"), "Remote", 1, 2),
        ),
    )
    assert validate_reader_document(bounded) is None

    object.__setattr__(
        bounded,
        "navigation",
        (ReaderNavigationEntry(location(page="page-0", node="missing"), "Missing", 0, 1),),
    )
    with pytest.raises(ReaderContractError, match="navigation target invalid on embedded page"):
        validate_reader_document(bounded)


def test_zero_page_document_requires_empty_navigation() -> None:
    empty = document()
    assert empty.metadata.page_count == 0
    assert validate_reader_document(empty) is None

    impossible = document()
    object.__setattr__(
        impossible,
        "navigation",
        (ReaderNavigationEntry(location(page="page-0", node="heading-0"), "Impossible", 0, 1),),
    )
    with pytest.raises(ReaderContractError, match="zero-page document must not contain navigation") as exc:
        validate_reader_document(impossible)
    assert exc.value.code.value == "invalid_navigation"

    nonempty = document()
    object.__setattr__(nonempty, "metadata", ReaderDocumentMetadata(page_count=1))
    object.__setattr__(
        nonempty,
        "navigation",
        (ReaderNavigationEntry(location(page="page-0", node="heading-0"), "Remote", 0, 1),),
    )
    assert validate_reader_document(nonempty) is None

    assert validate_reader_document(document(page(0))) is None


def test_document_no_usable_state_is_consistent_with_embedded_content_only() -> None:
    metadata_only = document()
    object.__setattr__(metadata_only, "metadata", ReaderDocumentMetadata(page_count=10))
    object.__setattr__(metadata_only, "content_state", ReaderContentState.NO_USABLE_SEMANTIC_CONTENT)
    assert validate_reader_document(metadata_only) is None

    unusable_page = ReaderPageView(
        location(page="page-0"), ContentPageId("page-0"), 0,
        ReaderContentState.NO_USABLE_SEMANTIC_CONTENT, (),
    )
    unusable = document()
    object.__setattr__(unusable, "metadata", ReaderDocumentMetadata(page_count=1))
    object.__setattr__(unusable, "pages", (unusable_page,))
    object.__setattr__(unusable, "content_state", ReaderContentState.NO_USABLE_SEMANTIC_CONTENT)
    assert validate_reader_document(unusable) is None

    contradictory = document(page(0))
    object.__setattr__(contradictory, "content_state", ReaderContentState.NO_USABLE_SEMANTIC_CONTENT)
    with pytest.raises(ReaderContractError, match="must not contain embedded nodes"):
        validate_reader_document(contradictory)

    assert validate_reader_document(document(page(0))) is None


def test_unavailable_document_cannot_expose_embedded_nodes() -> None:
    empty = document()
    object.__setattr__(empty, "metadata", ReaderDocumentMetadata(page_count=10))
    object.__setattr__(empty, "content_state", ReaderContentState.UNAVAILABLE)
    assert validate_reader_document(empty) is None

    unavailable_page = ReaderPageView(
        location(page="page-0"), ContentPageId("page-0"), 0,
        ReaderContentState.UNAVAILABLE, (),
    )
    bounded = document()
    object.__setattr__(bounded, "metadata", ReaderDocumentMetadata(page_count=1))
    object.__setattr__(bounded, "pages", (unavailable_page,))
    object.__setattr__(bounded, "content_state", ReaderContentState.UNAVAILABLE)
    assert validate_reader_document(bounded) is None

    contradictory = document(page(0))
    object.__setattr__(contradictory, "content_state", ReaderContentState.UNAVAILABLE)
    with pytest.raises(ReaderContractError, match="non-content-bearing document must not contain embedded nodes"):
        validate_reader_document(contradictory)


@pytest.mark.parametrize("malformed_metadata", (None, object(), 1, [], {}))
def test_document_metadata_type_is_bounded_before_field_access(malformed_metadata: object) -> None:
    view = document()
    object.__setattr__(view, "metadata", malformed_metadata)
    with pytest.raises(ReaderContractError, match="metadata must be ReaderDocumentMetadata") as exc:
        validate_reader_document(view)
    assert exc.value.code.value == "invalid_document"

    assert validate_reader_document(document()) is None


def test_heading_navigation_rejects_segment_scope_without_banning_segment_locations() -> None:
    segment_location = location(page="page-0", node="node-0", segment=0)
    assert validate_reader_location(segment_location) is None

    segment_heading = ReaderNavigationEntry(segment_location, "Heading", 0, 1)
    with pytest.raises(ReaderContractError, match="heading navigation must not be segment-scoped"):
        validate_navigation_entry(segment_heading)

    whole_heading = ReaderNavigationEntry(location(page="page-0", node="node-0"), "Heading", 0, 1)
    assert validate_navigation_entry(whole_heading) is None


@pytest.mark.parametrize("level", (True, False, "1", 1.0, 0, 7))
def test_node_heading_level_requires_bounded_non_boolean_integer(level: object) -> None:
    view = document(page(0))
    object.__setattr__(view.pages[0].nodes[0], "heading_level", level)
    with pytest.raises(ReaderContractError, match="heading node requires level"):
        validate_reader_document(view)


@pytest.mark.parametrize("level", range(1, 7))
def test_valid_heading_levels_are_accepted(level: int) -> None:
    view = document(page(0))
    object.__setattr__(view.pages[0].nodes[0], "heading_level", level)
    object.__setattr__(view.navigation[0], "heading_level", level)
    assert validate_reader_document(view) is None


def test_node_heading_level_is_intrinsically_required_and_heading_only() -> None:
    for level in (1, 6):
        heading = page(0).nodes[0]
        object.__setattr__(heading, "heading_level", level)
        assert validate_reader_node(heading) is None

    missing = page(0).nodes[0]
    object.__setattr__(missing, "heading_level", None)
    with pytest.raises(ReaderContractError, match="heading node requires level"):
        validate_reader_node(missing)

    paragraph = page(1).nodes[0]
    object.__setattr__(paragraph, "heading_level", 1)
    with pytest.raises(ReaderContractError, match="non-heading node must not have heading level"):
        validate_reader_node(paragraph)

    object.__setattr__(paragraph, "heading_level", None)
    assert validate_reader_node(paragraph) is None


def test_node_validator_rejects_self_parent_but_allows_external_parent_reference() -> None:
    self_parent = page(1).nodes[0]
    object.__setattr__(self_parent, "parent_ref", self_parent.node_id)
    with pytest.raises(ReaderContractError, match="node must not reference itself as parent"):
        validate_reader_node(self_parent)

    external_parent = page(1).nodes[0]
    object.__setattr__(external_parent, "parent_ref", ContentNodeId("parent"))
    assert validate_reader_node(external_parent) is None

    self_child = page(1).nodes[0]
    object.__setattr__(self_child, "child_refs", (self_child.node_id,))
    with pytest.raises(ReaderContractError, match="invalid child references"):
        validate_reader_node(self_child)


@pytest.mark.parametrize(
    "field,value,error",
    (
        ("document_ref", DocumentRef("other-document"), "location source identity mismatch"),
        ("candidate_id", ContentCandidateId("other-candidate"), "location source identity mismatch"),
        ("candidate_schema_id", "other-schema", "location source identity mismatch"),
        ("candidate_schema_version", 2, "location source identity mismatch"),
        ("contract_version", "999", "unsupported_version"),
    ),
)
def test_node_page_context_requires_full_location_source_identity(
    field: str, value: object, error: str
) -> None:
    context = page(0)
    node = page(0).nodes[0]
    object.__setattr__(node.location, field, value)
    with pytest.raises(ReaderContractError, match=error):
        validate_reader_node(node, context)

    assert validate_reader_node(page(0).nodes[0], page(0)) is None


def test_node_page_context_root_type_is_bounded() -> None:
    with pytest.raises(ReaderContractError, match="page context must be ReaderPageView"):
        validate_reader_node(page(0).nodes[0], object())  # type: ignore[arg-type]


def hierarchy_page(relations: tuple[tuple[str, str | None, tuple[str, ...]], ...]) -> ReaderPageView:
    nodes = tuple(
        ReaderNodeView(
            location=location(page="page-0", node=node_id),
            node_id=ContentNodeId(node_id),
            node_type=ContentNodeType.PARAGRAPH,
            order=index,
            content_state=ReaderContentState.READY,
            parent_ref=ContentNodeId(parent) if parent else None,
            child_refs=tuple(ContentNodeId(child) for child in children),
        )
        for index, (node_id, parent, children) in enumerate(relations)
    )
    return ReaderPageView(location(page="page-0"), ContentPageId("page-0"), 0, ReaderContentState.READY, nodes)


def test_valid_reciprocal_parent_child_hierarchy_is_accepted() -> None:
    valid = hierarchy_page((("A", None, ("B",)), ("B", "A", ())))
    view = document(valid)
    object.__setattr__(view, "navigation", ())
    assert validate_reader_document(view) is None


@pytest.mark.parametrize(
    "relations, reason",
    (
        ((("A", "A", ()),), "itself as parent"),
        ((("A", None, ("A",)),), "invalid child references"),
        ((("A", "B", ("B",)), ("B", "A", ("A",))), "cycle"),
        ((("A", "C", ("B",)), ("B", "A", ("C",)), ("C", "B", ("A",))), "cycle"),
        ((("A", None, ("B",)), ("B", "C", ()), ("C", None, ())), "relationship mismatch"),
        ((("A", None, ()), ("B", "A", ())), "relationship mismatch"),
        ((("A", "missing", ()),), "unknown parent reference"),
        ((("A", None, ("missing",)),), "unknown child reference"),
    ),
)
def test_invalid_node_hierarchies_fail_with_bounded_errors(
    relations: tuple[tuple[str, str | None, tuple[str, ...]], ...], reason: str
) -> None:
    with pytest.raises(ReaderContractError, match=reason):
        validate_reader_page(hierarchy_page(relations))


def test_runtime_bounded_types_are_enforced() -> None:
    mutations = (
        ("document processing", lambda view: object.__setattr__(view, "processing_state", "banana")),
        ("document content", lambda view: object.__setattr__(view, "content_state", "banana")),
        ("page content", lambda view: object.__setattr__(view.pages[0], "content_state", "banana")),
        ("node content", lambda view: object.__setattr__(view.pages[0].nodes[0], "content_state", "banana")),
        ("navigation kind", lambda view: object.__setattr__(view.navigation[0], "kind", "banana")),
        ("node type", lambda view: object.__setattr__(view.pages[0].nodes[0], "node_type", "banana")),
    )
    for _, mutate in mutations:
        view = document(page(0))
        mutate(view)
        with pytest.raises(ReaderContractError):
            validate_reader_document(view)

    for field, value in (("page_count", True), ("page_count", -1), ("title", 123)):
        view = document(page(0))
        object.__setattr__(view.metadata, field, value)
        with pytest.raises(ReaderContractError):
            validate_reader_document(view)


@pytest.mark.parametrize(
    "field,value,error",
    (
        ("text", 12, "node text must be a string"),
        ("text", True, "node text must be a string"),
        ("parent_ref", "node-1", "parent reference must be ContentNodeId"),
        ("child_refs", ("node-1",), "child references must be an immutable tuple"),
        ("child_refs", [ContentNodeId("node-1")], "child references must be an immutable tuple"),
        ("asset_refs", ("asset-1",), "asset references must be an immutable tuple"),
        ("asset_refs", [AssetId("asset-1")], "asset references must be an immutable tuple"),
    ),
)
def test_malformed_node_payload_fields_are_bounded(field: str, value: object, error: str) -> None:
    node = page(0).nodes[0]
    object.__setattr__(node, field, value)
    with pytest.raises(ReaderContractError, match=error):
        validate_reader_node(node)


def test_stable_node_and_asset_identity_payloads_are_accepted() -> None:
    valid = ReaderNodeView(
        location=location(page="page-0", node="parent"),
        node_id=ContentNodeId("parent"),
        node_type=ContentNodeType.PARAGRAPH,
        order=0,
        content_state=ReaderContentState.READY,
        text="Text",
        child_refs=(ContentNodeId("child"),),
        asset_refs=(AssetId("asset-1"),),
    )
    assert validate_reader_node(valid) is None


def test_page_rejects_malformed_node_member_with_bounded_error() -> None:
    malformed = page(0)
    object.__setattr__(malformed, "nodes", (object(),))
    with pytest.raises(ReaderContractError, match="expected ReaderNodeView") as exc:
        validate_reader_page(malformed)
    assert exc.value.code.value == "invalid_node"


@pytest.mark.parametrize("malformed_page", (object(), None, 1, [], {}))
def test_document_rejects_malformed_page_member_with_bounded_error(malformed_page: object) -> None:
    malformed = document(page(0))
    object.__setattr__(malformed, "pages", (malformed_page,))
    with pytest.raises(ReaderContractError, match="expected ReaderPageView") as exc:
        validate_reader_document(malformed)
    assert exc.value.code.value == "invalid_page"


def test_chunk_rejects_malformed_page_member_with_bounded_error() -> None:
    malformed = ReaderContentChunk(
        DocumentRef("document-1"), ContentCandidateId("candidate-1"), SCHEMA_ID, SCHEMA_VERSION,
        (page(0),), False,
    )
    object.__setattr__(malformed, "pages", (object(),))
    with pytest.raises(ReaderContractError, match="expected ReaderPageView") as exc:
        validate_reader_content_chunk(malformed)
    assert exc.value.code.value == "invalid_page"


def test_whole_node_view_rejects_segment_scoped_location() -> None:
    segment_scoped = ReaderNodeView(
        location=location(page="page-0", node="node-0", segment=0),
        node_id=ContentNodeId("node-0"),
        node_type=ContentNodeType.PARAGRAPH,
        order=0,
        content_state=ReaderContentState.READY,
        text="Text",
    )
    with pytest.raises(ReaderContractError, match="node location must not be segment-scoped"):
        validate_reader_node(segment_scoped)

    whole_node = ReaderNodeView(
        location=location(page="page-0", node="node-0"),
        node_id=ContentNodeId("node-0"),
        node_type=ContentNodeType.PARAGRAPH,
        order=0,
        content_state=ReaderContentState.READY,
        text="Text",
    )
    assert validate_reader_node(whole_node) is None


@pytest.mark.parametrize("scope", ("document", "page", "node"))
def test_warning_codes_are_runtime_bounded_at_every_scope(scope: str) -> None:
    view = document(page(0))
    malformed = ReaderWarning(ReaderWarningCode.CONTENT_DEGRADED)
    object.__setattr__(malformed, "code", "banana")
    target = view if scope == "document" else view.pages[0] if scope == "page" else view.pages[0].nodes[0]
    object.__setattr__(target, "warnings", (malformed,))
    with pytest.raises(ReaderContractError, match="warning must use a supported warning code"):
        validate_reader_document(view)


def test_chunk_is_bounded_candidate_bound_and_requires_continuation_location() -> None:
    pages = [page(0)]
    chunk = ReaderContentChunk(DocumentRef("document-1"), ContentCandidateId("candidate-1"), SCHEMA_ID, SCHEMA_VERSION, pages, True, continuation=ReaderContinuation(location(page="page-1"), 1))
    pages.clear()
    assert chunk.pages == (page(0),)
    assert validate_reader_content_chunk(chunk) is None
    with pytest.raises(ReaderContractError, match="has_more requires"):
        validate_reader_content_chunk(ReaderContentChunk(DocumentRef("document-1"), ContentCandidateId("candidate-1"), SCHEMA_ID, SCHEMA_VERSION, (), True))
    with pytest.raises(ReaderContractError, match="source identity mismatch"):
        validate_reader_content_chunk(ReaderContentChunk(DocumentRef("document-1"), ContentCandidateId("candidate-1"), SCHEMA_ID, SCHEMA_VERSION, (), True, continuation=ReaderContinuation(location(candidate="other", page="page-1"), 1)))


def test_chunk_has_more_is_strict_boolean_with_explicit_continuation_semantics() -> None:
    complete = ReaderContentChunk(
        DocumentRef("document-1"), ContentCandidateId("candidate-1"), SCHEMA_ID, SCHEMA_VERSION, (), False
    )
    assert validate_reader_content_chunk(complete) is None

    with pytest.raises(ReaderContractError, match="continuation requires has_more"):
        validate_reader_content_chunk(
            ReaderContentChunk(
                DocumentRef("document-1"), ContentCandidateId("candidate-1"), SCHEMA_ID, SCHEMA_VERSION,
                (), False, continuation=ReaderContinuation(location(page="page-1"), 1),
            )
        )
    for malformed in (1, 0, "false", "true", None):
        chunk = ReaderContentChunk(
            DocumentRef("document-1"), ContentCandidateId("candidate-1"), SCHEMA_ID, SCHEMA_VERSION, (), False
        )
        object.__setattr__(chunk, "has_more", malformed)
        with pytest.raises(ReaderContractError, match="has_more must be boolean"):
            validate_reader_content_chunk(chunk)


def test_chunk_requires_unique_page_and_document_wide_node_identities() -> None:
    first, second = page(0), page(1)
    valid = ReaderContentChunk(
        DocumentRef("document-1"), ContentCandidateId("candidate-1"), SCHEMA_ID, SCHEMA_VERSION,
        (first, second), False,
    )
    assert validate_reader_content_chunk(valid) is None

    duplicate_page = page(1)
    object.__setattr__(duplicate_page, "page_id", ContentPageId("page-0"))
    object.__setattr__(duplicate_page.location, "page_id", ContentPageId("page-0"))
    object.__setattr__(duplicate_page.nodes[0].location, "page_id", ContentPageId("page-0"))
    with pytest.raises(ReaderContractError, match="chunk page identities must be unique"):
        validate_reader_content_chunk(
            ReaderContentChunk(
                DocumentRef("document-1"), ContentCandidateId("candidate-1"), SCHEMA_ID, SCHEMA_VERSION,
                (page(0), duplicate_page), False,
            )
        )

    duplicate_node = page(1)
    object.__setattr__(duplicate_node.nodes[0], "node_id", ContentNodeId("node-0"))
    object.__setattr__(duplicate_node.nodes[0].location, "node_id", ContentNodeId("node-0"))
    with pytest.raises(ReaderContractError, match="chunk node identities must be document-unique"):
        validate_reader_content_chunk(
            ReaderContentChunk(
                DocumentRef("document-1"), ContentCandidateId("candidate-1"), SCHEMA_ID, SCHEMA_VERSION,
                (page(0), duplicate_node), False,
            )
        )


def test_chunk_continuation_must_identify_page_progress() -> None:
    base = (DocumentRef("document-1"), ContentCandidateId("candidate-1"), SCHEMA_ID, SCHEMA_VERSION, ())
    with pytest.raises(ReaderContractError, match="continuation must identify page progress"):
        validate_reader_content_chunk(ReaderContentChunk(*base, True, continuation=ReaderContinuation(location(), 0)))

    assert validate_reader_content_chunk(
        ReaderContentChunk(*base, True, continuation=ReaderContinuation(location(page="page-1"), 1))
    ) is None
    assert validate_reader_content_chunk(
        ReaderContentChunk(*base, True, continuation=ReaderContinuation(location(page="page-1", node="node-1"), 1))
    ) is None


def test_chunk_continuation_cannot_repeat_complete_returned_pages() -> None:
    source = (DocumentRef("document-1"), ContentCandidateId("candidate-1"), SCHEMA_ID, SCHEMA_VERSION)
    first, second = page(0), page(1)
    repeated_locations = (
        location(page="page-0"),
        location(page="page-0", node="node-0"),
    )
    for continuation in repeated_locations:
        with pytest.raises(ReaderContractError, match="advance beyond returned pages"):
            validate_reader_content_chunk(
                ReaderContentChunk(*source, (first,), True, continuation=ReaderContinuation(continuation, 1))
            )

    for continuation in (location(page="page-0"), location(page="page-1")):
        with pytest.raises(ReaderContractError, match="advance beyond returned pages"):
            validate_reader_content_chunk(
                ReaderContentChunk(*source, (first, second), True, continuation=ReaderContinuation(continuation, 2))
            )

    assert validate_reader_content_chunk(
        ReaderContentChunk(*source, (first, second), True, continuation=ReaderContinuation(location(page="page-2"), 2))
    ) is None
    assert validate_reader_content_chunk(
        ReaderContentChunk(*source, (), True, continuation=ReaderContinuation(location(page="page-0"), 0))
    ) is None


def test_chunk_continuation_order_proves_forward_progress() -> None:
    source = (DocumentRef("document-1"), ContentCandidateId("candidate-1"), SCHEMA_ID, SCHEMA_VERSION)
    fifth = page(5)
    for order in (2, 5):
        with pytest.raises(ReaderContractError, match="page order must follow"):
            validate_reader_content_chunk(
                ReaderContentChunk(*source, (fifth,), True, continuation=ReaderContinuation(location(page="future"), order))
            )
    assert validate_reader_content_chunk(
        ReaderContentChunk(*source, (fifth,), True, continuation=ReaderContinuation(location(page="future"), 6))
    ) is None

    pages = (page(3), page(4), page(5))
    assert validate_reader_content_chunk(
        ReaderContentChunk(*source, pages, True, continuation=ReaderContinuation(location(page="future"), 6))
    ) is None
    with pytest.raises(ReaderContractError, match="page order must follow"):
        validate_reader_content_chunk(
            ReaderContentChunk(*source, pages, True, continuation=ReaderContinuation(location(page="opaque-other"), 4))
        )
    with pytest.raises(ReaderContractError, match="advance beyond returned pages"):
        validate_reader_content_chunk(
            ReaderContentChunk(*source, pages, True, continuation=ReaderContinuation(location(page="page-5"), 6))
        )


@pytest.mark.parametrize("order", (True, -1, 1.5, "1"))
def test_chunk_continuation_order_is_bounded(order: object) -> None:
    continuation = ReaderContinuation(location(page="page-0"), 0)
    object.__setattr__(continuation, "page_order", order)
    with pytest.raises(ReaderContractError, match="page order must be nonnegative"):
        validate_reader_content_chunk(
            ReaderContentChunk(
                DocumentRef("document-1"), ContentCandidateId("candidate-1"), SCHEMA_ID, SCHEMA_VERSION,
                (), True, continuation=continuation,
            )
        )


def test_continuation_serialization_is_deterministic() -> None:
    continuation = ReaderContinuation(location(page="page-3"), 3)
    assert serialize_reader_contract(continuation) == serialize_reader_contract(copy.deepcopy(continuation))
    assert json.loads(serialize_reader_contract(continuation))["page_order"] == 3


def test_application_serialization_is_deterministic_and_detached() -> None:
    view = document(page(0), page(1))
    first = serialize_reader_contract(view)
    assert first == serialize_reader_contract(copy.deepcopy(view))
    payload = json.loads(first)
    payload["pages"].clear()
    assert len(view.pages) == 2
    assert payload["contract_version"] == READER_APPLICATION_CONTRACT_VERSION
    assert b"ReaderDocumentView" not in first


def test_direct_contract_dict_normalizes_string_enums_to_plain_strings() -> None:
    payload = to_reader_contract_dict(document(page(0)))
    assert payload["processing_state"] == ReaderProcessingState.COMPLETED.value
    assert type(payload["processing_state"]) is str
    assert payload["content_state"] == ReaderContentState.READY.value
    assert type(payload["content_state"]) is str
    node_type = payload["pages"][0]["nodes"][0]["node_type"]  # type: ignore[index]
    assert node_type == ContentNodeType.HEADING.value
    assert type(node_type) is str
    assert not isinstance(node_type, Enum)


def test_reader_package_has_no_forbidden_provider_api_database_or_secret_surface() -> None:
    package_text = "\n".join(path.read_text() for path in sorted(Path("app/reader").glob("*.py")))
    forbidden = (
        "MineruResult", "ContentBlock", "PdfPage", "BookImage", "provider_json", "raw_payload",
        "signed_url", "processed_file_path", "FastAPI", "APIRouter", "Depends", "sqlalchemy",
        "Session", "filesystem", "auth_token", "traceback",
    )
    for token in forbidden:
        assert token not in package_text
