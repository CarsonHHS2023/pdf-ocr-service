from __future__ import annotations

import copy
import importlib
import pkgutil
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from app.structured_content.enums import ContentNodeType, ContentRecoveryState, NodeRecoveryState, PageRecoveryState
from app.structured_content.identity import ContentCandidateId, ContentLineageKey, ContentNodeId, ContentPageId, DocumentRef
from app.structured_content.model import (
    SCHEMA_ID as STRUCTURED_CONTENT_SCHEMA_ID,
    SCHEMA_VERSION as STRUCTURED_CONTENT_SCHEMA_VERSION,
    ContentNode,
    ContentPage,
    ContentRecoverySummary,
    StructuredContentCandidate,
)
from app.structured_document import (
    DEFAULT_STRUCTURED_DOCUMENT_ASSEMBLY_POLICY,
    SUPPORTED_ASSEMBLY_POLICY_VERSION,
    SUPPORTED_STRUCTURED_DOCUMENT_SCHEMA_VERSION,
    InvalidAssemblyPolicy,
    InvalidStructuredContentInput,
    StructuredDocument,
    StructuredDocumentAssemblyPolicy,
    StructuredDocumentNodeView,
    StructuredDocumentPageView,
    UnsupportedAssemblyPolicyVersion,
    UnsupportedStructuredDocumentVersion,
    assemble_structured_document,
)
from app.structured_document.validation import validate_structured_document_contract


def candidate(candidate_id: str = "candidate-1", document_ref: str = "doc-1") -> StructuredContentCandidate:
    page_id = ContentPageId("page-1")
    node_id = ContentNodeId("node-1")
    return StructuredContentCandidate(
        schema_id=STRUCTURED_CONTENT_SCHEMA_ID,
        schema_version=STRUCTURED_CONTENT_SCHEMA_VERSION,
        document_ref=DocumentRef(document_ref),
        candidate_id=ContentCandidateId(candidate_id),
        lineage_key=ContentLineageKey(f"lineage-{candidate_id}"),
        recovery_summary=ContentRecoverySummary(
            state=ContentRecoveryState.COMPLETE,
            total_pages=1,
            complete_pages=1,
        ),
        pages=(ContentPage(page_id, 0, 0, PageRecoveryState.COMPLETE, (node_id,)),),
        nodes=(ContentNode(node_id, ContentLineageKey("node-lineage-1"), ContentNodeType.PARAGRAPH, page_id, 0, NodeRecoveryState.COMPLETE, text="Hello"),),
        evidence=(),
        assets=(),
        warnings=(),
        extensions={},
        raw_result_ref=None,
        structured_processing_result_ref=None,
    )


def test_policy_and_contracts_are_immutable_and_equality_stable() -> None:
    policy = StructuredDocumentAssemblyPolicy()
    assert policy == DEFAULT_STRUCTURED_DOCUMENT_ASSEMBLY_POLICY
    with pytest.raises(FrozenInstanceError):
        policy.assembly_policy_version = 2  # type: ignore[misc]

    doc = StructuredDocument.from_candidate_identity(candidate(), policy=policy)
    assert doc == StructuredDocument.from_candidate_identity(candidate(), policy=policy)
    with pytest.raises(FrozenInstanceError):
        doc.source_candidate_id = ContentCandidateId("other")  # type: ignore[misc]


def test_version_bounds_are_validated() -> None:
    doc = StructuredDocument.from_candidate_identity(candidate())
    assert validate_structured_document_contract(doc) is None

    with pytest.raises(UnsupportedStructuredDocumentVersion):
        validate_structured_document_contract(
            StructuredDocument.from_candidate_identity(candidate(), schema_version=SUPPORTED_STRUCTURED_DOCUMENT_SCHEMA_VERSION + 1)
        )
    with pytest.raises(UnsupportedAssemblyPolicyVersion):
        validate_structured_document_contract(
            StructuredDocument.from_candidate_identity(candidate(), policy=StructuredDocumentAssemblyPolicy(assembly_policy_version=SUPPORTED_ASSEMBLY_POLICY_VERSION + 1))
        )


def test_assembler_rejects_wrong_candidate_type_and_invalid_candidate() -> None:
    with pytest.raises(InvalidStructuredContentInput, match="expected StructuredContentCandidate"):
        assemble_structured_document({"candidate_id": "candidate-1"})  # type: ignore[arg-type]

    invalid = candidate()
    object.__setattr__(invalid, "pages", ())
    with pytest.raises(InvalidStructuredContentInput, match="structured content validation failed") as exc:
        assemble_structured_document(invalid)
    assert exc.value.__cause__ is not None
    assert "Hello" not in str(exc.value)


def test_valid_candidate_assembles_deterministically_without_mutating_inputs() -> None:
    c = candidate()
    original_candidate = copy.deepcopy(c)
    policy = StructuredDocumentAssemblyPolicy()
    original_policy = copy.deepcopy(policy)
    first = assemble_structured_document(c, policy=policy)
    second = assemble_structured_document(c, policy=policy)
    assert first == second
    assert first.document_reading_order_refs == (ContentNodeId("node-1"),)
    assert c == original_candidate
    assert policy == original_policy


def test_invalid_policy_is_bounded() -> None:
    with pytest.raises(InvalidAssemblyPolicy):
        assemble_structured_document(candidate(), policy="policy")  # type: ignore[arg-type]
    with pytest.raises(UnsupportedAssemblyPolicyVersion):
        assemble_structured_document(candidate(), policy=StructuredDocumentAssemblyPolicy(assembly_policy_version=2))


def test_candidate_identity_binding_is_retained_without_document_id_fabrication() -> None:
    first = StructuredDocument.from_candidate_identity(candidate("candidate-a", "doc-a"))
    second = StructuredDocument.from_candidate_identity(candidate("candidate-b", "doc-a"))
    assert first.document_ref == DocumentRef("doc-a")
    assert first.source_candidate_id == ContentCandidateId("candidate-a")
    assert first.source_candidate_schema_id == STRUCTURED_CONTENT_SCHEMA_ID
    assert first.source_candidate_schema_version == STRUCTURED_CONTENT_SCHEMA_VERSION
    assert first.source_candidate_lineage_key == ContentLineageKey("lineage-candidate-a")
    assert not hasattr(first, "structured_document_id")
    assert first != second


def test_page_and_node_view_contracts_are_minimal_references() -> None:
    page_view = StructuredDocumentPageView(ContentPageId("page-1"), 0, 0, (ContentNodeId("node-1"),), (ContentNodeId("node-1"),))
    node_view = StructuredDocumentNodeView(ContentNodeId("node-1"), None, (), 0, None)
    assert page_view.source_page_id == ContentPageId("page-1")
    assert node_view.source_node_id == ContentNodeId("node-1")
    with pytest.raises(FrozenInstanceError):
        node_view.traversal_index = 1  # type: ignore[misc]


def test_structured_document_package_has_no_forbidden_runtime_imports() -> None:
    package = importlib.import_module("app.structured_document")
    package_path = Path(package.__file__).parent
    forbidden = (
        "sqlalchemy", "Session", "repository", "set_selection", "selection_repository", "create_candidate", "create_run",
        "fastapi", "modal", "paddle", "mineru", "reader", "ContentBlock", "MineruResult", "PdfPage", "BookImage",
        "requests", "httpx", "boto3", "open(",
    )
    for module in pkgutil.walk_packages([str(package_path)], prefix="app.structured_document."):
        importlib.import_module(module.name)
    production_text = "\n".join(path.read_text() for path in package_path.glob("*.py"))
    for token in forbidden:
        assert token not in production_text
