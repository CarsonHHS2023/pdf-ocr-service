from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .enums import ContentNodeType, PageRecoveryState
from .identity import _StringRef
from .model import (
    CaptionAttributes,
    FigureAttributes,
    FormulaAttributes,
    HeadingAttributes,
    ListAttributes,
    ListItemAttributes,
    SCHEMA_ID,
    SCHEMA_VERSION,
    StructuredContentCandidate,
    TableAttributes,
)
from .serialization import serialize_structured_content_candidate


class ContentValidationSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ContentValidationCode(str, Enum):
    UNSUPPORTED_SCHEMA = "UNSUPPORTED_SCHEMA"
    EMPTY_CANDIDATE_ID = "EMPTY_CANDIDATE_ID"
    EMPTY_LINEAGE_KEY = "EMPTY_LINEAGE_KEY"
    DUPLICATE_PAGE_ID = "DUPLICATE_PAGE_ID"
    DUPLICATE_NODE_ID = "DUPLICATE_NODE_ID"
    DUPLICATE_EVIDENCE_ID = "DUPLICATE_EVIDENCE_ID"
    DUPLICATE_ASSET_ID = "DUPLICATE_ASSET_ID"
    DUPLICATE_RENDITION_ID = "DUPLICATE_RENDITION_ID"
    DUPLICATE_WARNING_ID = "DUPLICATE_WARNING_ID"
    DUPLICATE_PAGE_ORDER = "DUPLICATE_PAGE_ORDER"
    NEGATIVE_PAGE_ORDER = "NEGATIVE_PAGE_ORDER"
    NEGATIVE_SOURCE_PAGE_INDEX = "NEGATIVE_SOURCE_PAGE_INDEX"
    ROOT_NODE_NOT_FOUND = "ROOT_NODE_NOT_FOUND"
    ROOT_NODE_PAGE_MISMATCH = "ROOT_NODE_PAGE_MISMATCH"
    ROOT_NODE_HAS_PARENT = "ROOT_NODE_HAS_PARENT"
    DANGLING_PARENT = "DANGLING_PARENT"
    PARENT_PAGE_MISMATCH = "PARENT_PAGE_MISMATCH"
    HIERARCHY_CYCLE = "HIERARCHY_CYCLE"
    DUPLICATE_SIBLING_ORDER = "DUPLICATE_SIBLING_ORDER"
    DANGLING_EVIDENCE_REFERENCE = "DANGLING_EVIDENCE_REFERENCE"
    DANGLING_ASSET_REFERENCE = "DANGLING_ASSET_REFERENCE"
    DANGLING_WARNING_REFERENCE = "DANGLING_WARNING_REFERENCE"
    DANGLING_RENDITION_REFERENCE = "DANGLING_RENDITION_REFERENCE"
    RENDITION_ASSET_MISMATCH = "RENDITION_ASSET_MISMATCH"
    UNREFERENCED_RENDITION = "UNREFERENCED_RENDITION"
    INVALID_GEOMETRY_REFERENCE = "INVALID_GEOMETRY_REFERENCE"
    NODE_ATTRIBUTE_TYPE_MISMATCH = "NODE_ATTRIBUTE_TYPE_MISMATCH"
    NO_USABLE_PAGE_HAS_SEMANTIC_ROOTS = "NO_USABLE_PAGE_HAS_SEMANTIC_ROOTS"
    RECOVERY_SUMMARY_COUNT_MISMATCH = "RECOVERY_SUMMARY_COUNT_MISMATCH"
    UNSAFE_EXTENSION = "UNSAFE_EXTENSION"
    NONDETERMINISTIC_SERIALIZATION = "NONDETERMINISTIC_SERIALIZATION"
    NODE_PAGE_NOT_FOUND = "NODE_PAGE_NOT_FOUND"
    DUPLICATE_ROOT_NODE_REFERENCE = "DUPLICATE_ROOT_NODE_REFERENCE"


_SEVERITY_RANK = {
    ContentValidationSeverity.ERROR: 0,
    ContentValidationSeverity.WARNING: 1,
    ContentValidationSeverity.INFO: 2,
}


def _json(value: Any) -> Any:
    if isinstance(value, _StringRef):
        return value.value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_json(v) for v in value]
    if isinstance(value, list):
        return [_json(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json(value[k]) for k in sorted(value, key=str)}
    return value


def _details_sort_key(details: dict[str, Any]) -> str:
    return json.dumps(_json(details), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


@dataclass(frozen=True, slots=True)
class ContentValidationIssue:
    code: ContentValidationCode | str
    severity: ContentValidationSeverity = ContentValidationSeverity.ERROR
    scope_path: str = "$"
    safe_summary: str = "Structured content validation issue."
    blocking: bool = True
    evidence_ids: tuple[Any, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", self.code.value if isinstance(self.code, Enum) else str(self.code))
        object.__setattr__(self, "severity", self.severity if isinstance(self.severity, ContentValidationSeverity) else ContentValidationSeverity(str(self.severity)))
        object.__setattr__(self, "evidence_ids", tuple(_json(v) for v in self.evidence_ids))
        object.__setattr__(self, "details", _json(self.details))


@dataclass(frozen=True, slots=True)
class ContentValidationResult:
    is_valid: bool
    issues: tuple[ContentValidationIssue, ...] = ()
    blocking_issue_count: int = 0
    nonblocking_issue_count: int = 0
    schema_id: str = SCHEMA_ID
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        ordered = tuple(sorted(tuple(self.issues), key=_issue_sort_key))
        blocking = sum(1 for issue in ordered if issue.blocking)
        object.__setattr__(self, "issues", ordered)
        object.__setattr__(self, "blocking_issue_count", blocking)
        object.__setattr__(self, "nonblocking_issue_count", len(ordered) - blocking)
        object.__setattr__(self, "is_valid", blocking == 0)

    @classmethod
    def from_issues(cls, issues: list[ContentValidationIssue]) -> "ContentValidationResult":
        return cls(is_valid=True, issues=tuple(issues))

    @property
    def blocking_issues(self) -> tuple[ContentValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.blocking)

    @property
    def nonblocking_issues(self) -> tuple[ContentValidationIssue, ...]:
        return tuple(issue for issue in self.issues if not issue.blocking)

    def has_code(self, code: ContentValidationCode | str) -> bool:
        value = code.value if isinstance(code, Enum) else str(code)
        return any(issue.code == value for issue in self.issues)


def _issue_sort_key(issue: ContentValidationIssue) -> tuple[Any, ...]:
    return (not issue.blocking, _SEVERITY_RANK[issue.severity], issue.scope_path, issue.code, _details_sort_key(issue.details))


def _path(collection: str, identifier: Any) -> str:
    return f"$.{collection}[{_json(identifier)!r}]"


def _issue(code: ContentValidationCode, path: str, summary: str, **details: Any) -> ContentValidationIssue:
    return ContentValidationIssue(code=code, scope_path=path, safe_summary=summary, details=details)


def _duplicates(items: tuple[Any, ...], attr: str) -> set[Any]:
    seen, dup = set(), set()
    for item in items:
        value = getattr(item, attr)
        if value in seen:
            dup.add(value)
        seen.add(value)
    return dup


def _duplicate_values(values: tuple[Any, ...]) -> set[Any]:
    seen, dup = set(), set()
    for value in values:
        if value in seen:
            dup.add(value)
        seen.add(value)
    return dup


def _is_semantic_page_state(page_state: PageRecoveryState) -> bool:
    return page_state not in {PageRecoveryState.NO_USABLE_SEMANTIC_CONTENT, PageRecoveryState.UNAVAILABLE, PageRecoveryState.UNSUPPORTED}


def validate_content_candidate(candidate: StructuredContentCandidate) -> ContentValidationResult:
    issues: list[ContentValidationIssue] = []
    if candidate.schema_id != SCHEMA_ID or candidate.schema_version != SCHEMA_VERSION:
        issues.append(_issue(ContentValidationCode.UNSUPPORTED_SCHEMA, "$", "Unsupported structured content schema.", schema_id=candidate.schema_id, schema_version=candidate.schema_version))
    if not candidate.candidate_id.value.strip():
        issues.append(_issue(ContentValidationCode.EMPTY_CANDIDATE_ID, "$.candidate_id", "Candidate id must not be empty."))
    if not candidate.lineage_key.value.strip():
        issues.append(_issue(ContentValidationCode.EMPTY_LINEAGE_KEY, "$.lineage_key", "Lineage key must not be empty."))

    for attr, coll, code in (
        ("page_id", "pages", ContentValidationCode.DUPLICATE_PAGE_ID),
        ("node_id", "nodes", ContentValidationCode.DUPLICATE_NODE_ID),
        ("evidence_id", "evidence", ContentValidationCode.DUPLICATE_EVIDENCE_ID),
        ("asset_id", "assets", ContentValidationCode.DUPLICATE_ASSET_ID),
        ("rendition_id", "renditions", ContentValidationCode.DUPLICATE_RENDITION_ID),
        ("warning_id", "warnings", ContentValidationCode.DUPLICATE_WARNING_ID),
    ):
        for value in sorted(_duplicates(getattr(candidate, coll), attr), key=lambda v: _json(v)):
            issues.append(_issue(code, _path(coll, value), f"Duplicate {attr}.", **{attr: _json(value)}))

    pages = {page.page_id: page for page in candidate.pages}
    nodes = {node.node_id: node for node in candidate.nodes}
    evidence_ids = {evidence.evidence_id for evidence in candidate.evidence}
    asset_ids = {asset.asset_id for asset in candidate.assets}
    renditions = {rendition.rendition_id: rendition for rendition in candidate.renditions}
    registry_present = bool(candidate.renditions)
    warning_ids = {warning.warning_id for warning in candidate.warnings}
    page_source_indexes = {page.source_page_index for page in candidate.pages}

    for rendition in sorted(candidate.renditions, key=lambda r: r.rendition_id.value):
        rp = _path("renditions", rendition.rendition_id)
        if rendition.asset_id not in asset_ids:
            issues.append(_issue(ContentValidationCode.DANGLING_ASSET_REFERENCE, rp + ".asset_id", "Rendition asset reference was not found.", asset_id=rendition.asset_id))

    referenced_rendition_ids = set()
    for asset in sorted(candidate.assets, key=lambda a: a.asset_id.value):
        ap = _path("assets", asset.asset_id)
        if asset.source_location and asset.source_location.source_page_index not in page_source_indexes:
            issues.append(_issue(ContentValidationCode.INVALID_GEOMETRY_REFERENCE, ap + ".source_location", "Asset source location does not reference a candidate page.", source_page_index=asset.source_location.source_page_index))
        for evidence_id in asset.evidence_ids:
            if evidence_id not in evidence_ids:
                issues.append(_issue(ContentValidationCode.DANGLING_EVIDENCE_REFERENCE, ap + ".evidence_ids", "Evidence reference was not found.", evidence_id=evidence_id))
        for rendition_id in sorted(_duplicate_values(asset.rendition_refs), key=lambda v: v.value):
            issues.append(_issue(ContentValidationCode.DANGLING_RENDITION_REFERENCE, ap + ".rendition_refs", "Asset rendition reference is duplicated.", rendition_id=rendition_id))
        for rendition_id in asset.rendition_refs:
            referenced_rendition_ids.add(rendition_id)
            if registry_present:
                rendition = renditions.get(rendition_id)
                if rendition is None:
                    issues.append(_issue(ContentValidationCode.DANGLING_RENDITION_REFERENCE, ap + ".rendition_refs", "Asset rendition reference was not found.", rendition_id=rendition_id))
                elif rendition.asset_id != asset.asset_id:
                    issues.append(_issue(ContentValidationCode.RENDITION_ASSET_MISMATCH, ap + ".rendition_refs", "Rendition belongs to another asset.", rendition_id=rendition_id, expected_asset_id=asset.asset_id, actual_asset_id=rendition.asset_id))
    if registry_present:
        for rendition in candidate.renditions:
            if rendition.rendition_id not in referenced_rendition_ids:
                issues.append(_issue(ContentValidationCode.UNREFERENCED_RENDITION, _path("renditions", rendition.rendition_id), "Canonical rendition is not referenced by its asset.", rendition_id=rendition.rendition_id, asset_id=rendition.asset_id))

    for order in sorted(_duplicates(candidate.pages, "page_order")):
        issues.append(_issue(ContentValidationCode.DUPLICATE_PAGE_ORDER, f"$.pages[page_order={order}]", "Duplicate page order.", page_order=order))

    root_owners: dict[Any, list[Any]] = {}
    for page in sorted(candidate.pages, key=lambda p: p.page_id.value):
        pp = _path("pages", page.page_id)
        if page.page_order < 0:
            issues.append(_issue(ContentValidationCode.NEGATIVE_PAGE_ORDER, pp + ".page_order", "Page order must be nonnegative.", page_order=page.page_order))
        if page.source_page_index < 0:
            issues.append(_issue(ContentValidationCode.NEGATIVE_SOURCE_PAGE_INDEX, pp + ".source_page_index", "Source page index must be nonnegative.", source_page_index=page.source_page_index))
        for root_id in sorted(_duplicate_values(page.root_node_ids), key=lambda v: _json(v)):
            issues.append(_issue(ContentValidationCode.DUPLICATE_ROOT_NODE_REFERENCE, pp + ".root_node_ids", "Root node is repeated on the same page.", node_id=root_id))
        for root_id in page.root_node_ids:
            root_owners.setdefault(root_id, []).append(page.page_id)
            node = nodes.get(root_id)
            if node is None:
                issues.append(_issue(ContentValidationCode.ROOT_NODE_NOT_FOUND, pp + ".root_node_ids", "Page root node was not found.", node_id=_json(root_id)))
            else:
                if node.page_id != page.page_id:
                    issues.append(_issue(ContentValidationCode.ROOT_NODE_PAGE_MISMATCH, _path("nodes", root_id) + ".page_id", "Root node belongs to a different page.", expected_page_id=page.page_id, actual_page_id=node.page_id))
                if node.parent_id is not None:
                    issues.append(_issue(ContentValidationCode.ROOT_NODE_HAS_PARENT, _path("nodes", root_id) + ".parent_id", "Root node must not have a parent.", parent_id=node.parent_id))
        if page.recovery_state is PageRecoveryState.NO_USABLE_SEMANTIC_CONTENT and page.root_node_ids:
            issues.append(_issue(ContentValidationCode.NO_USABLE_PAGE_HAS_SEMANTIC_ROOTS, pp + ".root_node_ids", "No-usable-semantic-content page must not list semantic roots.", page_id=page.page_id))
        for evidence_id in page.evidence_ids:
            if evidence_id not in evidence_ids:
                issues.append(_issue(ContentValidationCode.DANGLING_EVIDENCE_REFERENCE, pp + ".evidence_ids", "Evidence reference was not found.", evidence_id=evidence_id))
        for warning_id in page.warning_ids:
            if warning_id not in warning_ids:
                issues.append(_issue(ContentValidationCode.DANGLING_WARNING_REFERENCE, pp + ".warning_ids", "Warning reference was not found.", warning_id=warning_id))
    for root_id, owner_page_ids in sorted(root_owners.items(), key=lambda kv: _json(kv[0])):
        if len(set(owner_page_ids)) > 1:
            issues.append(_issue(ContentValidationCode.DUPLICATE_ROOT_NODE_REFERENCE, _path("nodes", root_id), "Root node is listed by multiple pages.", page_ids=tuple(sorted(owner_page_ids, key=lambda v: v.value))))

    expected_attr = {
        ContentNodeType.HEADING: HeadingAttributes,
        ContentNodeType.LIST: ListAttributes,
        ContentNodeType.LIST_ITEM: ListItemAttributes,
        ContentNodeType.TABLE: TableAttributes,
        ContentNodeType.FIGURE: FigureAttributes,
        ContentNodeType.CAPTION: CaptionAttributes,
        ContentNodeType.FORMULA: FormulaAttributes,
    }
    specialized_attr_types = tuple(expected_attr.values())
    for node in sorted(candidate.nodes, key=lambda n: n.node_id.value):
        np = _path("nodes", node.node_id)
        page = pages.get(node.page_id)
        if page is None:
            issues.append(_issue(ContentValidationCode.NODE_PAGE_NOT_FOUND, np + ".page_id", "Node page was not found.", page_id=node.page_id))
        elif page.recovery_state is PageRecoveryState.NO_USABLE_SEMANTIC_CONTENT:
            issues.append(_issue(ContentValidationCode.NO_USABLE_PAGE_HAS_SEMANTIC_ROOTS, np + ".page_id", "No-usable-semantic-content page must not contain semantic nodes.", page_id=node.page_id))
        if node.sibling_order < 0:
            issues.append(_issue(ContentValidationCode.DUPLICATE_SIBLING_ORDER, np + ".sibling_order", "Sibling order must be nonnegative.", sibling_order=node.sibling_order))
        parent = nodes.get(node.parent_id) if node.parent_id is not None else None
        if node.parent_id is not None and parent is None:
            issues.append(_issue(ContentValidationCode.DANGLING_PARENT, np + ".parent_id", "Parent node was not found.", parent_id=node.parent_id))
        if parent is not None and parent.page_id != node.page_id:
            issues.append(_issue(ContentValidationCode.PARENT_PAGE_MISMATCH, np + ".parent_id", "Parent node belongs to a different page.", parent_id=node.parent_id, parent_page_id=parent.page_id, node_page_id=node.page_id))
        for loc in node.source_locations:
            if loc.source_page_index < 0 or loc.source_page_index not in page_source_indexes:
                issues.append(_issue(ContentValidationCode.INVALID_GEOMETRY_REFERENCE, np + ".source_locations", "Source location does not reference a candidate page.", source_page_index=loc.source_page_index))
        for evidence_id in node.evidence_ids:
            if evidence_id not in evidence_ids:
                issues.append(_issue(ContentValidationCode.DANGLING_EVIDENCE_REFERENCE, np + ".evidence_ids", "Evidence reference was not found.", evidence_id=evidence_id))
        for asset_id in node.asset_ids:
            if asset_id not in asset_ids:
                issues.append(_issue(ContentValidationCode.DANGLING_ASSET_REFERENCE, np + ".asset_ids", "Asset reference was not found.", asset_id=asset_id))
        for warning_id in node.warning_ids:
            if warning_id not in warning_ids:
                issues.append(_issue(ContentValidationCode.DANGLING_WARNING_REFERENCE, np + ".warning_ids", "Warning reference was not found.", warning_id=warning_id))
        expected_type = expected_attr.get(node.node_type)
        if expected_type is not None and node.attributes is not None and not isinstance(node.attributes, expected_type):
            issues.append(_issue(ContentValidationCode.NODE_ATTRIBUTE_TYPE_MISMATCH, np + ".attributes", "Node attributes do not match node type.", node_type=node.node_type, attribute_type=type(node.attributes).__name__))
        if expected_type is None and isinstance(node.attributes, specialized_attr_types):
            issues.append(_issue(ContentValidationCode.NODE_ATTRIBUTE_TYPE_MISMATCH, np + ".attributes", "Specialized attributes are not compatible with this node type.", node_type=node.node_type, attribute_type=type(node.attributes).__name__))
        if isinstance(node.attributes, (TableAttributes, FigureAttributes)) and node.attributes.rendered_asset_id and node.attributes.rendered_asset_id not in asset_ids:
            issues.append(_issue(ContentValidationCode.DANGLING_ASSET_REFERENCE, np + ".attributes.rendered_asset_id", "Rendered asset reference was not found.", asset_id=node.attributes.rendered_asset_id))
        if isinstance(node.attributes, CaptionAttributes) and node.attributes.target_asset_id and node.attributes.target_asset_id not in asset_ids:
            issues.append(_issue(ContentValidationCode.DANGLING_ASSET_REFERENCE, np + ".attributes.target_asset_id", "Target asset reference was not found.", asset_id=node.attributes.target_asset_id))

    sibling_groups: dict[tuple[Any, Any], list[Any]] = {}
    for node in candidate.nodes:
        if node.parent_id is not None:
            sibling_groups.setdefault((node.parent_id, node.sibling_order), []).append(node.node_id)
    for (parent_id, sibling_order), node_ids in sorted(sibling_groups.items(), key=lambda kv: (_json(kv[0][0]), kv[0][1])):
        if len(node_ids) > 1:
            issues.append(_issue(ContentValidationCode.DUPLICATE_SIBLING_ORDER, _path("nodes", parent_id) + f".children[sibling_order={sibling_order}]", "Duplicate sibling order under same parent.", parent_id=parent_id, sibling_order=sibling_order, node_ids=tuple(sorted(node_ids, key=lambda v: v.value))))

    cycle_keys: set[tuple[str, ...]] = set()
    for node in sorted(candidate.nodes, key=lambda n: n.node_id.value):
        position: dict[Any, int] = {}
        chain: list[Any] = []
        current = node
        while current.parent_id is not None and current.parent_id in nodes:
            if current.node_id in position:
                cycle_ids = chain[position[current.node_id]:]
                key = tuple(sorted(item.value for item in cycle_ids))
                cycle_keys.add(key)
                break
            position[current.node_id] = len(chain)
            chain.append(current.node_id)
            current = nodes[current.parent_id]
        else:
            if current.parent_id in position:
                cycle_ids = chain[position[current.parent_id]:]
                key = tuple(sorted(item.value for item in cycle_ids))
                cycle_keys.add(key)
    for key in sorted(cycle_keys):
        node_id = min(key)
        issues.append(_issue(ContentValidationCode.HIERARCHY_CYCLE, f"$.nodes['{node_id}'].parent_id", "Node hierarchy contains a cycle.", node_ids=key))

    for warning in sorted(candidate.warnings, key=lambda w: w.warning_id):
        for evidence_id in warning.evidence_ids:
            if evidence_id not in evidence_ids:
                issues.append(_issue(ContentValidationCode.DANGLING_EVIDENCE_REFERENCE, _path("warnings", warning.warning_id) + ".evidence_ids", "Evidence reference was not found.", evidence_id=evidence_id))

    usable_with_roots = any(_is_semantic_page_state(page.recovery_state) and page.root_node_ids for page in candidate.pages)
    if candidate.pages and not usable_with_roots:
        issues.append(_issue(ContentValidationCode.NO_USABLE_PAGE_HAS_SEMANTIC_ROOTS, "$.pages", "No usable page has semantic roots."))
    rs = candidate.recovery_summary
    actual = {
        "total_pages": len(candidate.pages),
        "complete_pages": sum(page.recovery_state == PageRecoveryState.COMPLETE for page in candidate.pages),
        "partial_pages": sum(page.recovery_state == PageRecoveryState.PARTIAL for page in candidate.pages),
        "degraded_pages": sum(page.recovery_state == PageRecoveryState.DEGRADED for page in candidate.pages),
        "unavailable_pages": sum(page.recovery_state in {PageRecoveryState.UNAVAILABLE, PageRecoveryState.UNSUPPORTED} for page in candidate.pages),
        "no_usable_semantic_content_pages": sum(page.recovery_state == PageRecoveryState.NO_USABLE_SEMANTIC_CONTENT for page in candidate.pages),
    }
    declared = {key: getattr(rs, key) for key in actual}
    if any(value < 0 for value in declared.values()) or actual != declared:
        issues.append(_issue(ContentValidationCode.RECOVERY_SUMMARY_COUNT_MISMATCH, "$.recovery_summary", "Recovery summary page counts do not match page registry.", expected=actual, actual=declared))
    try:
        first_serialization = serialize_structured_content_candidate(candidate)
        if first_serialization != serialize_structured_content_candidate(candidate):
            issues.append(_issue(ContentValidationCode.NONDETERMINISTIC_SERIALIZATION, "$", "Structured content serialization is nondeterministic."))
    except (TypeError, ValueError):
        issues.append(_issue(ContentValidationCode.NONDETERMINISTIC_SERIALIZATION, "$", "Structured content serialization failed determinism check."))
    return ContentValidationResult.from_issues(issues)


def validation_result_to_canonical_dict(result: ContentValidationResult) -> dict[str, Any]:
    return {
        "blocking_issue_count": result.blocking_issue_count,
        "is_valid": result.is_valid,
        "issues": [
            {"blocking": issue.blocking, "code": issue.code, "details": _json(issue.details), "evidence_ids": list(issue.evidence_ids), "safe_summary": issue.safe_summary, "scope_path": issue.scope_path, "severity": issue.severity.value}
            for issue in result.issues
        ],
        "nonblocking_issue_count": result.nonblocking_issue_count,
        "schema_id": result.schema_id,
        "schema_version": result.schema_version,
    }
