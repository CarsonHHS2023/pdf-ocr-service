from __future__ import annotations

from app.structured_content.model import SCHEMA_ID as STRUCTURED_CONTENT_SCHEMA_ID
from app.structured_content.model import SCHEMA_VERSION as STRUCTURED_CONTENT_SCHEMA_VERSION
from app.structured_content.model import ContentNode, StructuredContentCandidate
from app.structured_content.validation import validate_content_candidate

from .errors import InvalidStructuredContentInput, StructuredDocumentAssemblyInvariantViolation, UnsupportedStructuredDocumentVersion
from .types import (
    DEFAULT_STRUCTURED_DOCUMENT_ASSEMBLY_POLICY,
    StructuredDocument,
    StructuredDocumentAssemblyPolicy,
    StructuredDocumentNodeView,
    StructuredDocumentPageView,
)
from .validation import validate_assembly_policy, validate_structured_document_contract


def assemble_structured_document(
    candidate: StructuredContentCandidate,
    *,
    policy: StructuredDocumentAssemblyPolicy = DEFAULT_STRUCTURED_DOCUMENT_ASSEMBLY_POLICY,
) -> StructuredDocument:
    if not isinstance(candidate, StructuredContentCandidate):
        raise InvalidStructuredContentInput("expected StructuredContentCandidate")
    validate_assembly_policy(policy)
    if candidate.schema_id != STRUCTURED_CONTENT_SCHEMA_ID or candidate.schema_version != STRUCTURED_CONTENT_SCHEMA_VERSION:
        raise UnsupportedStructuredDocumentVersion(
            schema_version=candidate.schema_version,
            supported_schema_version=STRUCTURED_CONTENT_SCHEMA_VERSION,
        )
    result = validate_content_candidate(candidate)
    if not result.is_valid:
        raise InvalidStructuredContentInput(
            f"structured content validation failed with {result.blocking_issue_count} blocking issue(s)"
        ) from ValueError("structured content candidate failed validation")
    if not candidate.document_ref.value.strip() or not candidate.candidate_id.value.strip() or not candidate.lineage_key.value.strip():
        raise InvalidStructuredContentInput("candidate identity fields are required")

    nodes_by_id = {node.node_id: node for node in candidate.nodes}
    children_by_parent: dict[object, list[ContentNode]] = {}
    for node in candidate.nodes:
        if node.parent_id is not None:
            children_by_parent.setdefault(node.parent_id, []).append(node)
    for siblings in children_by_parent.values():
        siblings.sort(key=lambda node: (node.sibling_order, node.node_id.value))

    page_views: list[StructuredDocumentPageView] = []
    node_views_by_id: dict[object, StructuredDocumentNodeView] = {}
    document_order: list[object] = []
    visited: set[object] = set()

    def traverse(node: ContentNode, page_id: object, active: set[object]) -> None:
        if node.node_id in active:
            raise StructuredDocumentAssemblyInvariantViolation("cycle in source node hierarchy")
        if node.node_id in visited:
            raise StructuredDocumentAssemblyInvariantViolation("duplicate source node traversal")
        if node.page_id != page_id:
            raise StructuredDocumentAssemblyInvariantViolation("cross-page source node traversal")
        active.add(node.node_id)
        child_refs = tuple(child.node_id for child in children_by_parent.get(node.node_id, ()))
        node_views_by_id[node.node_id] = StructuredDocumentNodeView(
            source_node_id=node.node_id,
            parent_ref=node.parent_id,
            child_refs=child_refs,
            traversal_index=len(document_order),
        )
        document_order.append(node.node_id)
        visited.add(node.node_id)
        for child in children_by_parent.get(node.node_id, ()):  # already sorted above
            traverse(child, page_id, active)
        active.remove(node.node_id)

    for page in sorted(candidate.pages, key=lambda page: (page.page_order, page.source_page_index, page.page_id.value)):
        page_start = len(document_order)
        for root_id in page.root_node_ids:
            root = nodes_by_id.get(root_id)
            if root is None:
                raise StructuredDocumentAssemblyInvariantViolation("dangling page root reference")
            if root.page_id != page.page_id:
                raise StructuredDocumentAssemblyInvariantViolation("page root belongs to different page")
            if root.parent_id is not None:
                raise StructuredDocumentAssemblyInvariantViolation("page root has parent")
            traverse(root, page.page_id, set())
        page_views.append(
            StructuredDocumentPageView(
                source_page_id=page.page_id,
                source_page_index=page.source_page_index,
                page_order=page.page_order,
                root_node_refs=page.root_node_ids,
                reading_order_node_refs=tuple(document_order[page_start:]),
                evidence_refs=page.evidence_ids,
                warning_refs=page.warning_ids,
            )
        )

    missing = tuple(node.node_id for node in candidate.nodes if node.node_id not in visited)
    if missing:
        raise StructuredDocumentAssemblyInvariantViolation("source nodes are not reachable from page roots")

    document = StructuredDocument.from_candidate_identity(candidate, policy=policy)
    object.__setattr__(document, "pages", tuple(page_views))
    object.__setattr__(document, "node_views", tuple(node_views_by_id[node_id] for node_id in document_order))
    object.__setattr__(document, "document_reading_order_refs", tuple(document_order))
    validate_structured_document_contract(document)
    return document
