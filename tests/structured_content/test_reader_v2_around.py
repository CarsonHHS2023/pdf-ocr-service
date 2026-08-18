from __future__ import annotations

from app.source_units import SourceUnit, SourceUnitKind, TextSpanAnchor
from app.structured_content_v2.model import (
    ContentNodeTypeV2,
    ContentNodeV2,
    ContentRecoveryStateV2,
    ContentRecoverySummaryV2,
    StructuredContentCandidateV2,
    StructuredSourceUnit,
)
from tests.structured_content.test_reader_v2_api import _client, _db, _persist_and_select


def _long_txt_candidate() -> StructuredContentCandidateV2:
    flow = SourceUnit("flow", SourceUnitKind.TEXT_FLOW, 0, "txt", source_span=TextSpanAnchor("flow", 0, 10000))
    nodes = tuple(
        ContentNodeV2(
            node_id=f"n{index:03d}",
            lineage_key=f"lineage-{index:03d}",
            node_type=ContentNodeTypeV2.PARAGRAPH,
            source_unit_ids=("flow",),
            sibling_order=index,
            text=f"Node {index}",
            source_anchors=(TextSpanAnchor("flow", index * 10, index * 10 + 6),),
        )
        for index in range(320)
    )
    return StructuredContentCandidateV2(
        document_ref="doc-long",
        candidate_id="c-long",
        lineage_key="l-long",
        recovery_summary=ContentRecoverySummaryV2(ContentRecoveryStateV2.COMPLETE, 1, complete_source_units=1),
        source_units=(StructuredSourceUnit(flow),),
        nodes=nodes,
    )


def test_content_around_returns_only_the_150_node_window_containing_target() -> None:
    engine, factory = _db("doc-long", "txt")
    try:
        _persist_and_select(factory, _long_txt_candidate())
        response = _client(factory).get(
            "/api/reader/v2/documents/doc-long/content/around",
            params={"node_id": "n217", "limit": 150, "candidate_id": "c-long"},
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["nodes"]) == 150
        assert body["nodes"][0]["node_id"] == "n150"
        assert body["nodes"][-1]["node_id"] == "n299"
        assert any(node["node_id"] == "n217" for node in body["nodes"])
        assert body["next_node_order"] == 300
    finally:
        engine.dispose()
