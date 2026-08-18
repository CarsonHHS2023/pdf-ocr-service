from __future__ import annotations

from dataclasses import replace

from app.structured_content.enums import *
from app.structured_content.identity import *
from app.structured_content.model import *


def _require_positive(name: str, value: int) -> None:
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _summary(page_count: int) -> ContentRecoverySummary:
    return ContentRecoverySummary(ContentRecoveryState.COMPLETE, page_count, complete_pages=page_count)


def _ev(i: int, page: int = 0) -> EvidenceReference:
    return EvidenceReference(
        EvidenceReferenceId(f"ev-{i:04d}"),
        EvidenceKind.SOURCE_LOCATION,
        source_file_ref=SourceFileRef("source-file"),
        source_page_index=page,
        source_location=SourceLocation(page, NormalizedBoundingBox(0.1, 0.1, 0.9, 0.2)),
        raw_result_ref=RawResultRef("raw-result"),
        structured_processing_result_ref=StructuredProcessingResultRef("spr"),
        extensions={"org.atlas.kind": "fixture"},
    )


def make_empty_candidate(*, extensions: dict | None = None) -> StructuredContentCandidate:
    return StructuredContentCandidate(
        SCHEMA_ID,
        SCHEMA_VERSION,
        DocumentRef("doc-empty"),
        ContentCandidateId("candidate-empty"),
        ContentLineageKey("lineage-empty"),
        ContentRecoverySummary(ContentRecoveryState.COMPLETE, 0),
        (),
        (),
        (),
        (),
        (),
        dict(extensions or {"org.atlas.fixture": "empty"}),
        raw_result_ref=RawResultRef("raw-result"),
        structured_processing_result_ref=StructuredProcessingResultRef("spr"),
    )


def make_linear_candidate(page_count: int, nodes_per_page: int, *, extensions: dict | None = None) -> StructuredContentCandidate:
    _require_positive("page_count", page_count); _require_positive("nodes_per_page", nodes_per_page)
    pages, nodes, evidence = [], [], []
    for p in range(page_count):
        page_id = ContentPageId(f"page-{p:04d}")
        root_ids = []
        evidence.append(_ev(p, p))
        for n in range(nodes_per_page):
            idx = p * nodes_per_page + n
            node_id = ContentNodeId(f"node-{idx:05d}")
            root_ids.append(node_id)
            nodes.append(ContentNode(node_id, ContentLineageKey(f"lineage-node-{idx:05d}"), ContentNodeType.PARAGRAPH, page_id, n, NodeRecoveryState.COMPLETE, text=f"Text {idx}", source_locations=(SourceLocation(p),), evidence_ids=(EvidenceReferenceId(f"ev-{p:04d}"),), extensions={"org.atlas.order": idx}))
        pages.append(ContentPage(page_id, p, p, PageRecoveryState.COMPLETE, tuple(root_ids), page_label=str(p + 1), evidence_ids=(EvidenceReferenceId(f"ev-{p:04d}"),), extensions={"org.atlas.page": p}))
    return StructuredContentCandidate(SCHEMA_ID, SCHEMA_VERSION, DocumentRef("doc-linear"), ContentCandidateId("candidate-linear"), ContentLineageKey("lineage-linear"), _summary(page_count), tuple(pages), tuple(nodes), tuple(evidence), (), (), dict(extensions or {"org.atlas.fixture": "linear", "org.atlas.size": page_count * nodes_per_page}), raw_result_ref=RawResultRef("raw-result"), structured_processing_result_ref=StructuredProcessingResultRef("spr"))


def make_deep_hierarchy(depth: int, *, cycle: bool = False) -> StructuredContentCandidate:
    _require_positive("depth", depth)
    page_id = ContentPageId("page-deep")
    nodes = []
    for i in range(depth):
        parent = ContentNodeId(f"node-{i-1:05d}") if i else (ContentNodeId(f"node-{depth-1:05d}") if cycle else None)
        nodes.append(ContentNode(ContentNodeId(f"node-{i:05d}"), ContentLineageKey(f"lineage-{i:05d}"), ContentNodeType.SECTION if i == 0 else ContentNodeType.PARAGRAPH, page_id, i, NodeRecoveryState.COMPLETE, parent_id=parent, text=f"Deep {i}", evidence_ids=(EvidenceReferenceId("ev-0000"),)))
    page = ContentPage(page_id, 0, 0, PageRecoveryState.COMPLETE, (ContentNodeId("node-00000"),), evidence_ids=(EvidenceReferenceId("ev-0000"),))
    return StructuredContentCandidate(SCHEMA_ID, SCHEMA_VERSION, DocumentRef("doc-deep"), ContentCandidateId("candidate-deep"), ContentLineageKey("lineage-deep"), _summary(1), (page,), tuple(nodes), (_ev(0, 0),), (), (), {"org.atlas.fixture": "deep"}, raw_result_ref=RawResultRef("raw-result"), structured_processing_result_ref=StructuredProcessingResultRef("spr"))


def make_wide_hierarchy(child_count: int, *, duplicate_sibling: bool = False) -> StructuredContentCandidate:
    _require_positive("child_count", child_count)
    page_id = ContentPageId("page-wide"); root = ContentNodeId("node-root")
    nodes = [ContentNode(root, ContentLineageKey("lineage-root"), ContentNodeType.SECTION, page_id, 0, NodeRecoveryState.COMPLETE, text="Root", evidence_ids=(EvidenceReferenceId("ev-0000"),))]
    for i in range(child_count):
        order = 0 if duplicate_sibling and i == child_count - 1 else i
        nodes.append(ContentNode(ContentNodeId(f"node-child-{i:05d}"), ContentLineageKey(f"lineage-child-{i:05d}"), ContentNodeType.PARAGRAPH, page_id, order, NodeRecoveryState.COMPLETE, parent_id=root, text=f"Child {i}", evidence_ids=(EvidenceReferenceId("ev-0000"),)))
    page = ContentPage(page_id, 0, 0, PageRecoveryState.COMPLETE, (root,), evidence_ids=(EvidenceReferenceId("ev-0000"),))
    return StructuredContentCandidate(SCHEMA_ID, SCHEMA_VERSION, DocumentRef("doc-wide"), ContentCandidateId("candidate-wide"), ContentLineageKey("lineage-wide"), _summary(1), (page,), tuple(nodes), (_ev(0, 0),), (), (), {"org.atlas.fixture": "wide"}, raw_result_ref=RawResultRef("raw-result"), structured_processing_result_ref=StructuredProcessingResultRef("spr"))


def make_multi_page_candidate(page_count: int = 100, roots_per_page: int = 10, children_per_root: int = 0) -> StructuredContentCandidate:
    return make_linear_candidate(page_count, roots_per_page * (children_per_root + 1), extensions={"org.atlas.fixture": "multi_page"})


def make_table_candidate(rows: int = 50, columns: int = 10, *, swap_rows: bool = False) -> StructuredContentCandidate:
    _require_positive("rows", rows); _require_positive("columns", columns)
    cells = [TableCell(r, c, text=f"R{r}C{c}") for r in range(rows) for c in range(columns)]
    if swap_rows:
        row0, row1, rest = cells[:columns], cells[columns:2*columns], cells[2*columns:]
        cells = row1 + row0 + rest
    cand = make_linear_candidate(1, 1, extensions={"org.atlas.fixture": "table"})
    table_node = replace(cand.nodes[0], node_type=ContentNodeType.TABLE, attributes=TableAttributes(TableStructure(rows, columns, tuple(cells))))
    return replace(cand, nodes=(table_node,))


def make_asset_evidence_warning_candidate(evidence_count: int = 100, asset_count: int = 50, warning_count: int = 50) -> StructuredContentCandidate:
    evidence = tuple(_ev(i, 0) for i in range(evidence_count))
    warnings = tuple(ContentWarning(f"warn-{i:04d}", "RECOVERED", WarningSeverity.WARNING, f"$.nodes['node-00000']", f"Warning {i}", evidence_ids=(EvidenceReferenceId(f"ev-{i % evidence_count:04d}"),), details={"org.atlas.index": i}) for i in range(warning_count))
    assets = tuple(AssetReference(AssetId(f"asset-{i:04d}"), AssetRole.FIGURE, AssetRecoveryState.AVAILABLE, rendition_refs=(AssetRenditionId(f"asset-{i:04d}-original"), AssetRenditionId(f"asset-{i:04d}-thumb")), evidence_ids=(EvidenceReferenceId(f"ev-{i % evidence_count:04d}"),), media_type="image/png", checksum=f"sha256:{i:04d}") for i in range(asset_count))
    page = ContentPage(ContentPageId("page-0000"), 0, 0, PageRecoveryState.COMPLETE, (ContentNodeId("node-00000"),), evidence_ids=(EvidenceReferenceId("ev-0000"),), warning_ids=tuple(w.warning_id for w in warnings))
    node = ContentNode(ContentNodeId("node-00000"), ContentLineageKey("lineage-node-00000"), ContentNodeType.FIGURE, ContentPageId("page-0000"), 0, NodeRecoveryState.COMPLETE, text="Figure", evidence_ids=tuple(e.evidence_id for e in evidence), asset_ids=tuple(a.asset_id for a in assets), warning_ids=tuple(w.warning_id for w in warnings), attributes=FigureAttributes(rendered_asset_id=assets[0].asset_id))
    return StructuredContentCandidate(SCHEMA_ID, SCHEMA_VERSION, DocumentRef("doc-assets"), ContentCandidateId("candidate-assets"), ContentLineageKey("lineage-assets"), _summary(1), (page,), (node,), evidence, assets, warnings, {"org.atlas.fixture": "asset_evidence_warning"}, raw_result_ref=RawResultRef("raw-result"), structured_processing_result_ref=StructuredProcessingResultRef("spr"))


def permute_registries(candidate: StructuredContentCandidate) -> StructuredContentCandidate:
    return replace(candidate, nodes=tuple(reversed(candidate.nodes)), evidence=tuple(reversed(candidate.evidence)), assets=tuple(reversed(candidate.assets)), warnings=tuple(reversed(candidate.warnings)))
