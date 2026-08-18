from __future__ import annotations

import copy

import pytest

from app.processing.structured_result import StructuredProcessingResult
from app.processing.structured_result.models import StructuredPageStatus
from app.structured_content.enums import AssetRecoveryState, AssetRenditionRole, ContentNodeType, ContentRecoveryState, NodeRecoveryState, PageRecoveryState
from app.structured_content.serialization import serialize_structured_content_candidate
from app.structured_content.transformation import CandidateIdentityInput, TransformationContext, TransformationInvariantViolation, transform_spr_to_candidate
from app.structured_content.validation import validate_content_candidate


def ctx(candidate_id: str = "candidate-ta", seed: str = "lineage-ta") -> TransformationContext:
    return TransformationContext("doc-ta", CandidateIdentityInput(candidate_id, seed), processing_run_ref="run-ta", source_file_ref="source-ta")


def base(nodes: list[dict], *, assets: list[dict] | None = None, pages: list[dict] | None = None) -> dict:
    if pages is None:
        roots = [n["node_id"] for n in nodes if not n.get("parent_id")]
        pages = [{"page_id": "page-1", "page_index": 0, "page_number": 1, "width": 100, "height": 200, "status": StructuredPageStatus.USABLE, "root_node_ids": roots}]
    observations = []
    evidence = []
    for i, n in enumerate(nodes):
        oid = f"obs-{n['node_id']}"
        eid = f"ev-{n['node_id']}"
        n.setdefault("page_ids", [pages[0]["page_id"]])
        n.setdefault("observation_ids", [oid])
        n.setdefault("evidence_link_ids", [eid])
        n.setdefault("ordinal", i)
        observations.append({"observation_id": oid, "page_id": n["page_ids"][0], "observation_type": n["node_type"], "content": {"text": n.get("text", n["node_id"])}, "evidence_link_ids": [eid]})
        evidence.append({"evidence_link_id": eid, "target_kind": "observation", "target_id": oid, "source_page_index": next(p["page_index"] for p in pages if p["page_id"] == n["page_ids"][0]), "geometry": n.get("geometry")})
    return StructuredProcessingResult({"schema_id": "atlas.structured-processing-result", "schema_version": 1, "result_id": "spr-ta", "state": "complete", "raw_result": {"raw_result_id": "raw-ta"}, "pages": pages, "nodes": nodes, "assets": assets or [], "normalized_observations": observations, "evidence_links": evidence, "warnings": [], "diagnostics": [], "quality_summary": {"page_coverage": {"mapped_page_indices": [0]}, "warning_counts": {}}}).to_dict()


def transform(data: dict, context: TransformationContext | None = None):
    return transform_spr_to_candidate(StructuredProcessingResult(copy.deepcopy(data)), context=context or ctx())


def table_node(cells: list[dict], **kw) -> dict:
    out = {"node_id": kw.pop("node_id", "tbl"), "node_type": "table", "text": kw.pop("text", "A | B"), "table": {"row_count": kw.pop("row_count", 2), "column_count": kw.pop("column_count", 2), "cells": cells}, "geometry": {"normalized_bbox": [0.1, 0.1, 0.9, 0.5]}, "extensions": kw.pop("extensions", {})}
    out.update(kw)
    return out


def test_2x2_table_header_cells_geometry_evidence_and_determinism() -> None:
    data = base([table_node([
        {"cell_id": "c00", "row_index": 0, "column_index": 0, "text": "H1", "header": True},
        {"cell_id": "c01", "row_index": 0, "column_index": 1, "text": "H2", "header": True},
        {"cell_id": "c10", "row_index": 1, "column_index": 0, "text": "A"},
        {"cell_id": "c11", "row_index": 1, "column_index": 1, "text": "B"},
    ])])
    first = transform(data); second = transform(data)
    table = first.nodes[0]
    assert table.node_type is ContentNodeType.TABLE
    assert table.attributes.structure.row_count == 2
    assert [(c.row_index, c.column_index, c.text) for c in table.attributes.structure.cells] == [(0, 0, "H1"), (0, 1, "H2"), (1, 0, "A"), (1, 1, "B")]
    assert table.attributes.structure.cells[0].extensions["org.atlas.transform.header"] is True
    assert table.source_locations[0].bounding_box is not None and table.evidence_ids
    assert first == second
    assert serialize_structured_content_candidate(first) == serialize_structured_content_candidate(second)
    assert validate_content_candidate(first).is_valid


def test_merged_row_and_column_spans_are_preserved_without_fabricated_cells() -> None:
    c = transform(base([table_node([
        {"cell_id": "rowspan", "row_index": 0, "column_index": 0, "row_span": 2, "text": "A"},
        {"cell_id": "colspan", "row_index": 0, "column_index": 1, "column_span": 2, "text": "B"},
    ], row_count=2, column_count=3)])).nodes[0].attributes.structure.cells
    assert [(x.row_span, x.column_span, x.text) for x in c] == [(2, 1, "A"), (1, 2, "B")]
    assert len(c) == 2


def test_sparse_table_is_valid_when_cells_do_not_overlap() -> None:
    c = transform(base([table_node([{"cell_id": "c00", "row_index": 0, "column_index": 0, "text": "A"}], row_count=3, column_count=3)]))
    assert c.nodes[0].attributes.structure.row_count == 3
    assert validate_content_candidate(c).is_valid


@pytest.mark.parametrize("cells", [
    [{"cell_id": "a", "row_index": 0, "column_index": 0}, {"cell_id": "b", "row_index": 0, "column_index": 0}],
    [{"cell_id": "a", "row_index": 0, "column_index": 0, "column_span": 2}, {"cell_id": "b", "row_index": 0, "column_index": 1}],
    [{"cell_id": "a", "row_index": -1, "column_index": 0}],
    [{"cell_id": "a", "row_index": 0, "column_index": 0, "row_span": 0}],
    [{"cell_id": "a", "row_index": 0, "column_index": 0}, {"cell_id": "a", "row_index": 0, "column_index": 1}],
])
def test_invalid_tables_fail_atomically_without_mutating_input(cells: list[dict]) -> None:
    data = base([table_node(cells)])
    before = copy.deepcopy(data)
    with pytest.raises(TransformationInvariantViolation):
        transform(data)
    assert data == before


def test_caption_to_table_and_figure_resolve_explicit_targets_only() -> None:
    data = base([
        table_node([{"cell_id": "c", "row_index": 0, "column_index": 0}], row_count=1, column_count=1, node_id="tbl"),
        {"node_id": "tbl-cap", "node_type": "caption", "text": "Table 1", "extensions": {"target_ref": "tbl"}},
        {"node_id": "fig", "node_type": "figure", "text": "", "extensions": {"asset_ref": "asset-1", "caption_ref": "fig-cap"}},
        {"node_id": "fig-cap", "node_type": "caption", "text": "Figure 1", "extensions": {"target_ref": "fig"}},
    ], assets=[{"asset_id": "asset-1", "kind": "figure", "media_type": "image/png", "width": 640, "height": 480, "checksum": "sha256:abc", "source_page_index": 0, "alt_text": "explicit alt", "renditions": [{"rendition_id": "orig", "role": "original", "artifact_ref": "src_0123456789abcdef0123456789abcdef", "media_type": "image/png", "width": 640, "height": 480}]}])
    c = transform(data)
    assert [n.node_type for n in c.nodes] == [ContentNodeType.TABLE, ContentNodeType.CAPTION, ContentNodeType.FIGURE, ContentNodeType.CAPTION]
    assert c.nodes[1].attributes.target_node_id == c.nodes[0].node_id
    assert c.nodes[2].attributes.caption_node_id == c.nodes[3].node_id
    assert c.nodes[3].attributes.target_node_id == c.nodes[2].node_id
    assert c.nodes[2].asset_ids == (c.assets[0].asset_id,)
    assert c.nodes[2].attributes.rendered_asset_id == c.assets[0].asset_id
    assert c.assets[0].alt_text == "explicit alt" and c.assets[0].media_type == "image/png"
    assert c.assets[0].recovery_state is AssetRecoveryState.AVAILABLE
    assert len(c.renditions) == 1
    assert c.assets[0].rendition_refs == (c.renditions[0].rendition_id,)
    assert c.renditions[0].asset_id == c.assets[0].asset_id
    assert c.renditions[0].role is AssetRenditionRole.ORIGINAL
    assert c.renditions[0].artifact_ref == "src_0123456789abcdef0123456789abcdef"
    assert not c.warnings
    assert validate_content_candidate(c).is_valid


def test_missing_asset_and_unresolved_caption_degrade_without_fake_asset() -> None:
    c = transform(base([
        {"node_id": "fig", "node_type": "image", "text": "", "extensions": {"asset_ref": "missing-asset"}},
        {"node_id": "cap", "node_type": "caption", "text": "Missing", "extensions": {"target_ref": "missing-node"}},
    ]))
    assert c.assets == ()
    assert c.renditions == ()
    assert sorted(w.code for w in c.warnings) == ["MISSING_ASSET_REFERENCE", "UNRESOLVED_CAPTION_ASSOCIATION"]
    assert c.nodes[0].recovery_state is NodeRecoveryState.DEGRADED
    assert c.pages[0].recovery_state is PageRecoveryState.DEGRADED
    assert c.recovery_summary.state is ContentRecoveryState.DEGRADED
    assert validate_content_candidate(c).is_valid


def test_asset_without_durable_rendition_is_degraded_and_transient_url_not_canonical() -> None:
    c = transform(base([{"node_id": "fig", "node_type": "figure", "text": "", "extensions": {"asset_ref": "asset-1"}}], assets=[{"asset_id": "asset-1", "kind": "figure", "media_type": "image/png", "renditions": [{"rendition_id": "signed", "artifact_ref": "https://example.test/a.png?X-Amz-Signature=secret"}]}]))
    assert len(c.assets) == 1
    assert c.assets[0].recovery_state is AssetRecoveryState.DEGRADED
    assert c.assets[0].rendition_refs == ()
    assert c.renditions == ()
    assert "example.test" not in serialize_structured_content_candidate(c).decode()
    assert validate_content_candidate(c).is_valid


def test_mixed_two_page_document_tables_assets_and_captions() -> None:
    pages = [{"page_id": "p1", "page_index": 0, "page_number": 1, "width": 100, "height": 200, "status": StructuredPageStatus.USABLE, "root_node_ids": ["title", "para", "list", "tbl", "tcap"]}, {"page_id": "p2", "page_index": 1, "page_number": 2, "width": 100, "height": 200, "status": StructuredPageStatus.USABLE, "root_node_ids": ["head", "p2para", "fig", "fcap", "footer"]}]
    data = base([
        {"node_id": "title", "node_type": "title", "text": "Report", "page_ids": ["p1"]}, {"node_id": "para", "node_type": "paragraph", "text": "Intro", "page_ids": ["p1"]}, {"node_id": "list", "node_type": "list", "text": "", "page_ids": ["p1"]}, table_node([{"cell_id": "c", "row_index": 0, "column_index": 0, "text": "A"}], row_count=1, column_count=1, node_id="tbl", extensions={"rendered_asset_ref": "tbl-img"}, page_ids=["p1"]), {"node_id": "tcap", "node_type": "caption", "text": "Table", "extensions": {"target_ref": "tbl"}, "page_ids": ["p1"]},
        {"node_id": "head", "node_type": "heading", "text": "Second", "page_ids": ["p2"]}, {"node_id": "p2para", "node_type": "paragraph", "text": "Body", "page_ids": ["p2"]}, {"node_id": "fig", "node_type": "figure", "text": "", "extensions": {"asset_ref": "fig-asset"}, "page_ids": ["p2"]}, {"node_id": "fcap", "node_type": "caption", "text": "Figure", "extensions": {"target_ref": "fig"}, "page_ids": ["p2"]}, {"node_id": "footer", "node_type": "footer", "text": "Footer", "page_ids": ["p2"]},
    ], assets=[{"asset_id": "fig-asset", "kind": "figure", "source_page_index": 1}, {"asset_id": "tbl-img", "kind": "rendered_table_image", "source_page_index": 0}], pages=pages)
    c = transform(data)
    assert [p.page_order for p in c.pages] == [0, 1]
    assert [n.node_type for n in c.nodes[:5]] == [ContentNodeType.HEADING, ContentNodeType.PARAGRAPH, ContentNodeType.LIST, ContentNodeType.TABLE, ContentNodeType.CAPTION]
    assert c.nodes[4].attributes.target_node_id == c.nodes[3].node_id
    assert c.nodes[8].attributes.target_node_id == c.nodes[7].node_id
    assert len(c.assets) == 2
    assert validate_content_candidate(c).is_valid
    assert serialize_structured_content_candidate(c) == serialize_structured_content_candidate(transform(data))
