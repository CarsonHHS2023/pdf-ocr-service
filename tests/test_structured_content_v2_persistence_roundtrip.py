from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Document
import app.models_v2  # noqa: F401
import app.models_v2_selection  # noqa: F401
from app.source_units import (
    DomAnchor,
    SourceUnit,
    SourceUnitDimensions,
    SourceUnitKind,
    SpatialAnchor,
    TemporalAnchor,
    TextSpanAnchor,
)
from app.structured_content_v2.model import (
    AssetRecoveryStateV2,
    AssetReferenceV2,
    AssetRenditionReferenceV2,
    AssetRenditionRoleV2,
    AssetRoleV2,
    ContentNodeTypeV2,
    ContentNodeV2,
    ContentRecoveryStateV2,
    ContentRecoverySummaryV2,
    ContentWarningV2,
    EvidenceReferenceV2,
    StructuredContentCandidateV2,
    StructuredSourceUnit,
    WarningSeverityV2,
    normalize_candidate_v2,
)
from app.structured_content_v2.repository import (
    StructuredContentCandidateV2Repository,
    StructuredContentV2CandidateConflict,
)
from app.structured_content_v2.selection import (
    StructuredContentV2SelectionCandidateMismatch,
    StructuredContentV2SelectionNotFound,
    StructuredContentV2SelectionRepository,
    StructuredContentV2SelectionVersionConflict,
)


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def _add_documents(session) -> None:
    session.add_all([
        Document(id="doc-v2", title="V2", file_type="mixed", status="processing"),
        Document(id="doc-other", title="Other", file_type="txt", status="processing"),
    ])
    session.flush()


def _candidate(candidate_id: str = "candidate-v2", document_ref: str = "doc-v2", text: str = "Body") -> StructuredContentCandidateV2:
    page = SourceUnit("page-1", SourceUnitKind.PHYSICAL_PAGE, 0, "source-pdf", dimensions=SourceUnitDimensions(1000, 1400))
    flow1 = SourceUnit("flow-1", SourceUnitKind.TEXT_FLOW, 1, "source-txt", source_span=TextSpanAnchor("flow-1", 0, 100))
    flow2 = SourceUnit("flow-2", SourceUnitKind.TEXT_FLOW, 2, "source-txt", source_span=TextSpanAnchor("flow-2", 100, 200))
    html = SourceUnit("html-1", SourceUnitKind.HTML_SECTION, 3, "source-html")
    audio = SourceUnit("audio-1", SourceUnitKind.AUDIO_SEGMENT, 4, "source-audio", duration_ms=5000)

    spatial = SpatialAnchor("page-1", 0.1, 0.1, 0.8, 0.2)
    span1 = TextSpanAnchor("flow-1", 10, 90)
    span2 = TextSpanAnchor("flow-2", 100, 140)
    dom = DomAnchor("html-1", "body/main/p[1]", 0, 4)
    temporal = TemporalAnchor("audio-1", 100, 900)

    evidence = (
        EvidenceReferenceV2("ev-page", "page-1", (spatial,), raw_result_ref="raw-1"),
        EvidenceReferenceV2("ev-flow", None, (span1, span2), structured_processing_result_ref="spr-1"),
        EvidenceReferenceV2("ev-dom", "html-1", (dom,)),
        EvidenceReferenceV2("ev-time", "audio-1", (temporal,)),
    )
    warning = ContentWarningV2(
        "warn-1", "RECOVERED_BLOCK", WarningSeverityV2.WARNING, "node-body", "Recovered content",
        evidence_ids=("ev-flow",), recoverable=True, details={"strategy": "merge"},
    )
    asset = AssetReferenceV2(
        asset_id="asset-1", role=AssetRoleV2.FIGURE, recovery_state=AssetRecoveryStateV2.AVAILABLE,
        source_unit_ids=("page-1",), source_anchors=(spatial,), rendition_ids=("rendition-1",),
        evidence_ids=("ev-page",), caption="Figure", alt_text="Figure alt", metadata={"kind": "diagram"},
    )
    rendition = AssetRenditionReferenceV2(
        "rendition-1", "asset-1", AssetRenditionRoleV2.ORIGINAL,
        "artifact://figures/asset-1/original", media_type="image/png", checksum="sha256:abc",
        recovery_state=AssetRecoveryStateV2.AVAILABLE,
    )
    nodes = (
        ContentNodeV2(
            "node-heading", "lineage-heading", ContentNodeTypeV2.HEADING, ("page-1",), 0,
            text="Chapter 1", heading_level=1, source_anchors=(spatial,), evidence_ids=("ev-page",),
        ),
        ContentNodeV2(
            "node-body", "lineage-body", ContentNodeTypeV2.PARAGRAPH, ("flow-1", "flow-2"), 0,
            parent_id="node-heading", text=text, source_anchors=(span1, span2), evidence_ids=("ev-flow",),
            asset_ids=("asset-1",), warning_ids=("warn-1",), metadata={"source": "txt"},
        ),
        ContentNodeV2(
            "node-dom", "lineage-dom", ContentNodeTypeV2.PARAGRAPH, ("html-1",), 1,
            parent_id="node-heading", text="HTML", source_anchors=(dom,), evidence_ids=("ev-dom",),
        ),
        ContentNodeV2(
            "node-audio", "lineage-audio", ContentNodeTypeV2.QUOTE, ("audio-1",), 2,
            parent_id="node-heading", text="Audio quote", source_anchors=(temporal,), evidence_ids=("ev-time",),
        ),
    )
    units = (
        StructuredSourceUnit(page, evidence_ids=("ev-page",)),
        StructuredSourceUnit(flow1, evidence_ids=("ev-flow",), warning_ids=("warn-1",)),
        StructuredSourceUnit(flow2, evidence_ids=("ev-flow",)),
        StructuredSourceUnit(html, evidence_ids=("ev-dom",)),
        StructuredSourceUnit(audio, evidence_ids=("ev-time",)),
    )
    summary = ContentRecoverySummaryV2(
        ContentRecoveryStateV2.COMPLETE, 5, complete_source_units=5,
        warning_ids=("warn-1",), recovery_policy_ref="recovery-policy-v2",
    )
    return StructuredContentCandidateV2(
        document_ref=document_ref, candidate_id=candidate_id, lineage_key=f"lineage-{candidate_id}",
        recovery_summary=summary, source_units=units, nodes=nodes, evidence=evidence,
        assets=(asset,), warnings=(warning,), renditions=(rendition,),
        transformer_ref="transformer-v2", transformation_policy_ref="policy-v2",
        raw_result_ref="raw-1", structured_processing_result_ref="spr-1",
    )


def test_v2_candidate_round_trip_preserves_canonical_content_without_fake_pages() -> None:
    engine, session = _session()
    try:
        _add_documents(session)
        repo = StructuredContentCandidateV2Repository()
        original = _candidate()
        persisted = repo.create_candidate(session, original)
        reconstructed = repo.get_candidate(session, original.candidate_id)

        assert normalize_candidate_v2(persisted) == normalize_candidate_v2(original)
        assert normalize_candidate_v2(reconstructed) == normalize_candidate_v2(original)
        body = next(node for node in reconstructed.nodes if node.node_id == "node-body")
        assert body.source_unit_ids == ("flow-1", "flow-2")
        assert [anchor.source_unit_id for anchor in body.source_anchors] == ["flow-1", "flow-2"]
        assert not any(unit.source_unit.kind.value == "page" for unit in reconstructed.source_units)
        assert next(node for node in reconstructed.nodes if node.node_id == "node-dom").source_anchors[0].path == "body/main/p[1]"
        assert next(node for node in reconstructed.nodes if node.node_id == "node-audio").source_anchors[0].end_ms == 900
    finally:
        session.close(); engine.dispose()


def test_create_is_idempotent_but_same_id_different_content_conflicts() -> None:
    engine, session = _session()
    try:
        _add_documents(session)
        repo = StructuredContentCandidateV2Repository()
        candidate = _candidate()
        first = repo.create_candidate(session, candidate)
        second = repo.create_candidate(session, candidate)
        assert normalize_candidate_v2(first) == normalize_candidate_v2(second)
        with pytest.raises(StructuredContentV2CandidateConflict):
            repo.create_candidate(session, _candidate(text="Different body"))
    finally:
        session.close(); engine.dispose()


def test_candidate_create_does_not_auto_select_and_selection_is_explicit_versioned() -> None:
    engine, session = _session()
    try:
        _add_documents(session)
        repo = StructuredContentCandidateV2Repository()
        selection = StructuredContentV2SelectionRepository(repo)
        candidate = repo.create_candidate(session, _candidate())

        with pytest.raises(StructuredContentV2SelectionNotFound):
            selection.get_selected_candidate(session, "doc-v2")

        selected = selection.set_selection(
            session, document_ref="doc-v2", candidate_id=candidate.candidate_id,
            expected_version=0, selection_actor_ref="test", reason="initial",
        )
        assert selected.selection_version == 1
        assert selected.candidate_id == candidate.candidate_id
        assert normalize_candidate_v2(selection.get_selected_candidate(session, "doc-v2")) == normalize_candidate_v2(candidate)

        with pytest.raises(StructuredContentV2SelectionVersionConflict):
            selection.set_selection(session, document_ref="doc-v2", candidate_id=candidate.candidate_id, expected_version=0)

        selected2 = selection.set_selection(session, document_ref="doc-v2", candidate_id=candidate.candidate_id, expected_version=1)
        assert selected2.selection_version == 2
    finally:
        session.close(); engine.dispose()


def test_selection_rejects_candidate_from_another_document() -> None:
    engine, session = _session()
    try:
        _add_documents(session)
        repo = StructuredContentCandidateV2Repository()
        selection = StructuredContentV2SelectionRepository(repo)
        other = repo.create_candidate(session, _candidate(candidate_id="candidate-other", document_ref="doc-other"))
        with pytest.raises(StructuredContentV2SelectionCandidateMismatch):
            selection.set_selection(session, document_ref="doc-v2", candidate_id=other.candidate_id, expected_version=0)
    finally:
        session.close(); engine.dispose()
