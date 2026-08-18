from __future__ import annotations

import pytest

from app.source_units import SourceUnit, SourceUnitKind, TextSpanAnchor
from app.structured_content_v2 import (
    AssetRecoveryStateV2,
    AssetReferenceV2,
    AssetRenditionReferenceV2,
    AssetRenditionRoleV2,
    AssetRoleV2,
    ContentNodeTypeV2,
    ContentNodeV2,
    ContentRecoveryStateV2,
    ContentRecoverySummaryV2,
    EvidenceReferenceV2,
    StructuredContentCandidateV2,
    StructuredSourceUnit,
    validate_candidate_v2,
)


def _unit(unit_id: str = "u1", order: int = 0) -> SourceUnit:
    return SourceUnit(unit_id, SourceUnitKind.TEXT_FLOW, order, "src", source_span=TextSpanAnchor(unit_id, order * 10, order * 10 + 10))


def _summary(total: int = 1) -> ContentRecoverySummaryV2:
    return ContentRecoverySummaryV2(ContentRecoveryStateV2.COMPLETE, total, complete_source_units=total)


def _candidate(*, units=None, nodes=(), evidence=(), assets=(), renditions=(), summary=None):
    units = units or (_unit(),)
    return StructuredContentCandidateV2(
        document_ref="doc",
        candidate_id="cand",
        lineage_key="lineage",
        recovery_summary=summary or _summary(len(units)),
        source_units=tuple(StructuredSourceUnit(unit) for unit in units),
        nodes=tuple(nodes),
        evidence=tuple(evidence),
        assets=tuple(assets),
        renditions=tuple(renditions),
    )


def test_rejects_duplicate_source_order() -> None:
    with pytest.raises(ValueError, match="source_order values must be unique"):
        validate_candidate_v2(_candidate(units=(_unit("u1", 0), _unit("u2", 0)), summary=_summary(2)))


def test_rejects_missing_source_unit_and_wrong_anchor_owner() -> None:
    missing = ContentNodeV2("n", "l", ContentNodeTypeV2.PARAGRAPH, ("missing",), 0)
    with pytest.raises(ValueError, match="missing source units"):
        validate_candidate_v2(_candidate(nodes=(missing,)))

    wrong_anchor = ContentNodeV2(
        "n",
        "l",
        ContentNodeTypeV2.PARAGRAPH,
        ("u1",),
        0,
        source_anchors=(TextSpanAnchor("u2", 0, 1),),
    )
    with pytest.raises(ValueError, match="anchor references missing source unit"):
        validate_candidate_v2(_candidate(nodes=(wrong_anchor,)))


def test_rejects_missing_parent_and_cycles_but_not_cross_source_parentage() -> None:
    missing_parent = ContentNodeV2("n", "l", ContentNodeTypeV2.PARAGRAPH, ("u1",), 0, parent_id="absent")
    with pytest.raises(ValueError, match="missing parent"):
        validate_candidate_v2(_candidate(nodes=(missing_parent,)))

    a = ContentNodeV2("a", "la", ContentNodeTypeV2.PARAGRAPH, ("u1",), 0, parent_id="b")
    b = ContentNodeV2("b", "lb", ContentNodeTypeV2.PARAGRAPH, ("u1",), 0, parent_id="a")
    with pytest.raises(ValueError, match="cycle"):
        validate_candidate_v2(_candidate(nodes=(a, b)))

    u1, u2 = _unit("u1", 0), _unit("u2", 1)
    parent = ContentNodeV2("h", "lh", ContentNodeTypeV2.HEADING, ("u1",), 0, text="H", heading_level=1)
    child = ContentNodeV2("p", "lp", ContentNodeTypeV2.PARAGRAPH, ("u2",), 0, parent_id="h", text="P")
    validate_candidate_v2(_candidate(units=(u1, u2), nodes=(parent, child), summary=_summary(2)))


def test_rejects_duplicate_sibling_order_under_same_parent() -> None:
    a = ContentNodeV2("a", "la", ContentNodeTypeV2.PARAGRAPH, ("u1",), 0)
    b = ContentNodeV2("b", "lb", ContentNodeTypeV2.PARAGRAPH, ("u1",), 0)
    with pytest.raises(ValueError, match="duplicate sibling_order"):
        validate_candidate_v2(_candidate(nodes=(a, b)))


def test_rejects_missing_evidence_asset_and_rendition_references() -> None:
    node = ContentNodeV2("n", "l", ContentNodeTypeV2.PARAGRAPH, ("u1",), 0, evidence_ids=("missing",))
    with pytest.raises(ValueError, match="missing evidence"):
        validate_candidate_v2(_candidate(nodes=(node,)))

    asset = AssetReferenceV2(
        "a1",
        AssetRoleV2.FIGURE,
        AssetRecoveryStateV2.AVAILABLE,
        ("u1",),
        rendition_ids=("missing-rendition",),
    )
    with pytest.raises(ValueError, match="missing renditions"):
        validate_candidate_v2(_candidate(assets=(asset,)))


def test_rejects_transient_or_local_rendition_locator() -> None:
    asset = AssetReferenceV2(
        "a1",
        AssetRoleV2.FIGURE,
        AssetRecoveryStateV2.AVAILABLE,
        ("u1",),
        rendition_ids=("r1",),
    )
    rendition = AssetRenditionReferenceV2(
        "r1",
        "a1",
        AssetRenditionRoleV2.ORIGINAL,
        "https://example.test/file.png?token=secret",
    )
    with pytest.raises(ValueError, match="transient or local"):
        validate_candidate_v2(_candidate(assets=(asset,), renditions=(rendition,)))


def test_rejects_inconsistent_recovery_summary() -> None:
    bad = ContentRecoverySummaryV2(ContentRecoveryStateV2.COMPLETE, 2, complete_source_units=2)
    with pytest.raises(ValueError, match="total_source_units must be 1"):
        validate_candidate_v2(_candidate(summary=bad))


def test_valid_evidence_reference_uses_source_anchor_without_page_fields() -> None:
    evidence = EvidenceReferenceV2(
        "e1",
        source_unit_id="u1",
        source_anchors=(TextSpanAnchor("u1", 0, 5),),
        processing_run_ref="run-1",
        structured_processing_result_ref="spr-v2-1",
    )
    node = ContentNodeV2("n", "l", ContentNodeTypeV2.PARAGRAPH, ("u1",), 0, evidence_ids=("e1",))
    validate_candidate_v2(_candidate(nodes=(node,), evidence=(evidence,)))
