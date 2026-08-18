from __future__ import annotations

from app.structured_content.model import SCHEMA_ID as STRUCTURED_CONTENT_SCHEMA_ID
from app.structured_content.model import SCHEMA_VERSION as STRUCTURED_CONTENT_SCHEMA_VERSION

from .errors import InvalidAssemblyPolicy, StructuredDocumentValidationFailed, UnsupportedAssemblyPolicyVersion, UnsupportedStructuredDocumentVersion
from .types import (
    SUPPORTED_ASSEMBLY_POLICY_VERSION,
    SUPPORTED_STRUCTURED_DOCUMENT_SCHEMA_VERSION,
    StructuredDocument,
    StructuredDocumentAssemblyPolicy,
)


def validate_assembly_policy(policy: StructuredDocumentAssemblyPolicy) -> None:
    if not isinstance(policy, StructuredDocumentAssemblyPolicy):
        raise InvalidAssemblyPolicy("expected StructuredDocumentAssemblyPolicy")
    if policy.structured_document_schema_version != SUPPORTED_STRUCTURED_DOCUMENT_SCHEMA_VERSION:
        raise UnsupportedStructuredDocumentVersion(
            schema_version=policy.structured_document_schema_version,
            supported_schema_version=SUPPORTED_STRUCTURED_DOCUMENT_SCHEMA_VERSION,
        )
    if policy.assembly_policy_version != SUPPORTED_ASSEMBLY_POLICY_VERSION:
        raise UnsupportedAssemblyPolicyVersion(
            policy_version=policy.assembly_policy_version,
            supported_policy_version=SUPPORTED_ASSEMBLY_POLICY_VERSION,
        )


def _fail(reason: str) -> None:
    raise StructuredDocumentValidationFailed(reason)


def validate_structured_document_contract(document: StructuredDocument) -> None:
    if document.schema_version != SUPPORTED_STRUCTURED_DOCUMENT_SCHEMA_VERSION:
        raise UnsupportedStructuredDocumentVersion(
            schema_version=document.schema_version,
            supported_schema_version=SUPPORTED_STRUCTURED_DOCUMENT_SCHEMA_VERSION,
        )
    validate_assembly_policy(document.assembly_policy)
    if document.assembly_policy_version != document.assembly_policy.assembly_policy_version:
        raise InvalidAssemblyPolicy("document assembly policy version mismatch")
    if document.source_candidate_schema_id != STRUCTURED_CONTENT_SCHEMA_ID:
        raise InvalidAssemblyPolicy("unsupported source candidate schema id")
    if document.source_candidate_schema_version != STRUCTURED_CONTENT_SCHEMA_VERSION:
        raise InvalidAssemblyPolicy("unsupported source candidate schema version")

    page_ids = [page.source_page_id for page in document.pages]
    if len(set(page_ids)) != len(page_ids):
        raise InvalidAssemblyPolicy("duplicate structured document page reference")
    node_ids = [node.source_node_id for node in document.node_views]
    if len(set(node_ids)) != len(node_ids):
        raise InvalidAssemblyPolicy("duplicate structured document node reference")

    node_set = set(node_ids)
    page_by_node = {node_ref: page.source_page_id for page in document.pages for node_ref in page.reading_order_node_refs}
    node_views = {node.source_node_id: node for node in document.node_views}
    order = tuple(document.document_reading_order_refs)
    if any(ref not in node_set for ref in order):
        _fail("document reading order contains unknown node reference")
    if len(set(order)) != len(order):
        _fail("document reading order contains duplicate node reference")
    if set(order) != node_set:
        _fail("document reading order must cover exactly the node views")
    indexes = [node.traversal_index for node in document.node_views]
    if sorted(indexes) != list(range(len(indexes))):
        _fail("node traversal indexes must be unique and contiguous")
    for index, ref in enumerate(order):
        if node_views[ref].traversal_index != index:
            _fail("node traversal index must match document reading order")

    page_segments: list[object] = []
    for page in document.pages:
        if any(root not in node_set for root in page.root_node_refs):
            _fail("page root contains unknown node reference")
        if any(ref not in node_set for ref in page.reading_order_node_refs):
            _fail("page reading order contains unknown node reference")
        if len(set(page.reading_order_node_refs)) != len(page.reading_order_node_refs):
            _fail("page reading order contains duplicate node reference")
        if any(page_by_node.get(ref) != page.source_page_id for ref in page.root_node_refs):
            _fail("page root is not local to page reading order")
        page_segments.extend(page.reading_order_node_refs)
    if tuple(page_segments) != order:
        _fail("page reading-order segments must equal document reading order")

    for node in document.node_views:
        if node.parent_ref is not None and node.parent_ref not in node_set:
            _fail("node parent contains unknown node reference")
        for child_ref in node.child_refs:
            if child_ref not in node_set:
                _fail("node child contains unknown node reference")
            child = node_views[child_ref]
            if child.parent_ref != node.source_node_id:
                _fail("node child parent reference mismatch")
            if page_by_node.get(child_ref) != page_by_node.get(node.source_node_id):
                _fail("node child crosses page boundary")
        if node.parent_ref is not None:
            parent = node_views[node.parent_ref]
            if node.source_node_id not in parent.child_refs:
                _fail("node parent child reference mismatch")

    for node in document.node_views:
        seen = set()
        current = node
        while current.parent_ref is not None:
            if current.source_node_id in seen:
                _fail("node hierarchy contains cycle")
            seen.add(current.source_node_id)
            current = node_views[current.parent_ref]
