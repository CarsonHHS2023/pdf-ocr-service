from __future__ import annotations

import pytest

from app.processing.normalized_observations import NormalizedObservationBundle
from app.processing.pdf_recovery import recover_pdf_observations_to_spr_v2
from app.processing.structured_result_v2.model import (
    ProcessingEvidence,
    ProcessingNodeKind,
    ProcessingObservation,
)
from app.source_units import SourceUnit, SourceUnitDimensions, SourceUnitKind, SpatialAnchor


def test_toc_items_split_one_provider_block_into_distinct_row_anchors() -> None:
    page = SourceUnit(
        source_unit_id="p1",
        kind=SourceUnitKind.PHYSICAL_PAGE,
        source_order=0,
        source_ref="pdf",
        dimensions=SourceUnitDimensions(600, 800),
    )
    block_anchor = SpatialAnchor("p1", 0.1, 0.2, 0.9, 0.5)
    observation = ProcessingObservation(
        observation_id="toc-observation",
        source_unit_id="p1",
        order=0,
        observed_kind="toc",
        text="第一章 ........ 1\n第二章 ........ 6\n第三章 ........ 12",
        anchors=(block_anchor,),
        confidence=0.95,
        evidence_ids=("toc-evidence",),
    )
    evidence = ProcessingEvidence(
        evidence_id="toc-evidence",
        source_unit_id="p1",
        anchors=(block_anchor,),
        observation_id="toc-observation",
        processing_run_ref="run",
        raw_result_ref="raw",
    )
    bundle = NormalizedObservationBundle(
        document_ref="doc-toc",
        source_ref="pdf",
        processing_run_ref="run",
        raw_result_ref="raw",
        source_units=(page,),
        observations=(observation,),
        evidence=(evidence,),
    )

    result = recover_pdf_observations_to_spr_v2(bundle)
    items = [node for node in result.nodes if node.kind is ProcessingNodeKind.LIST_ITEM]

    assert [item.text for item in items] == [
        "第一章 ........ 1",
        "第二章 ........ 6",
        "第三章 ........ 12",
    ]
    anchors = [next(anchor for anchor in item.anchors if isinstance(anchor, SpatialAnchor)) for item in items]
    assert [(anchor.top, anchor.bottom) for anchor in anchors] == pytest.approx(
        [(0.2, 0.3), (0.3, 0.4), (0.4, 0.5)]
    )
    assert len({(anchor.left, anchor.top, anchor.right, anchor.bottom) for anchor in anchors}) == 3
    assert all(item.metadata["presentation_anchor_rule"] == "split_toc_block_rows" for item in items)
    assert [item.metadata["presentation_row_index"] for item in items] == [0, 1, 2]
    assert all(item.metadata["presentation_row_count"] == 3 for item in items)
