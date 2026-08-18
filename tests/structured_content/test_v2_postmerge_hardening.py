from __future__ import annotations

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Document
import app.models_v2  # noqa: F401
import app.models_v2_selection  # noqa: F401
from app.models_v2 import (
    StructuredContentCandidateV2Record as CandidateRow,
    StructuredContentNodeSourceUnitV2Record as NodeUnitRow,
    StructuredContentNodeV2Record as NodeRow,
)
from app.models_v2_selection import StructuredContentSelectionV2Record as SelectionRow
from app.source_units import SourceUnit, SourceUnitKind, TextSpanAnchor
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
    StructuredContentCandidateV2,
    StructuredSourceUnit,
)
from app.structured_content_v2.repository import StructuredContentCandidateV2Repository
from app.structured_content_v2.selection import (
    StructuredContentV2SelectionCandidateInvalid,
    StructuredContentV2SelectionRepository,
)
from app.structured_content_v2.validation import validate_candidate_v2


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def _summary() -> ContentRecoverySummaryV2:
    return ContentRecoverySummaryV2(
        state=ContentRecoveryStateV2.COMPLETE,
        total_source_units=1,
        complete_source_units=1,
    )


def _candidate_with_node() -> StructuredContentCandidateV2:
    unit = SourceUnit(
        "flow-1",
        SourceUnitKind.TEXT_FLOW,
        0,
        "source-txt",
        source_span=TextSpanAnchor("flow-1", 0, 100),
    )
    node = ContentNodeV2(
        node_id="node-1",
        lineage_key="lineage-node-1",
        node_type=ContentNodeTypeV2.PARAGRAPH,
        source_unit_ids=("flow-1",),
        sibling_order=0,
        text="Body",
        source_anchors=(TextSpanAnchor("flow-1", 0, 4),),
    )
    return StructuredContentCandidateV2(
        document_ref="doc-v2",
        candidate_id="candidate-v2",
        lineage_key="lineage-candidate-v2",
        recovery_summary=_summary(),
        source_units=(StructuredSourceUnit(unit),),
        nodes=(node,),
    )


def _asset_candidate(
    *,
    asset_a_renditions: tuple[str, ...],
    asset_b_renditions: tuple[str, ...] = (),
    rendition_owner: str = "asset-a",
) -> StructuredContentCandidateV2:
    unit = SourceUnit(
        "flow-1",
        SourceUnitKind.TEXT_FLOW,
        0,
        "source-txt",
        source_span=TextSpanAnchor("flow-1", 0, 10),
    )
    asset_a = AssetReferenceV2(
        asset_id="asset-a",
        role=AssetRoleV2.FIGURE,
        recovery_state=AssetRecoveryStateV2.AVAILABLE,
        source_unit_ids=("flow-1",),
        rendition_ids=asset_a_renditions,
    )
    asset_b = AssetReferenceV2(
        asset_id="asset-b",
        role=AssetRoleV2.FIGURE,
        recovery_state=AssetRecoveryStateV2.AVAILABLE,
        source_unit_ids=("flow-1",),
        rendition_ids=asset_b_renditions,
    )
    rendition = AssetRenditionReferenceV2(
        rendition_id="r1",
        asset_id=rendition_owner,
        role=AssetRenditionRoleV2.ORIGINAL,
        artifact_ref="artifact://assets/r1",
        recovery_state=AssetRecoveryStateV2.AVAILABLE,
    )
    return StructuredContentCandidateV2(
        document_ref="doc-v2",
        candidate_id="candidate-assets",
        lineage_key="lineage-assets",
        recovery_summary=_summary(),
        source_units=(StructuredSourceUnit(unit),),
        nodes=(),
        assets=(asset_a, asset_b),
        renditions=(rendition,),
    )


def test_selection_reconstructs_and_validates_candidate_before_mutation() -> None:
    engine, session = _session()
    try:
        session.add(Document(id="doc-v2", title="V2", file_type="txt", status="processing"))
        session.flush()
        candidates = StructuredContentCandidateV2Repository()
        selections = StructuredContentV2SelectionRepository(candidates)
        candidates.create_candidate(session, _candidate_with_node())

        candidate_row = session.execute(
            select(CandidateRow).where(CandidateRow.candidate_id == "candidate-v2")
        ).scalar_one()
        node_row = session.execute(
            select(NodeRow).where(
                NodeRow.candidate_id == candidate_row.id,
                NodeRow.node_id == "node-1",
            )
        ).scalar_one()
        session.execute(delete(NodeUnitRow).where(NodeUnitRow.node_record_id == node_row.id))
        session.flush()

        with pytest.raises(StructuredContentV2SelectionCandidateInvalid):
            selections.set_selection(
                session,
                document_ref="doc-v2",
                candidate_id="candidate-v2",
                expected_version=0,
            )

        assert session.get(SelectionRow, "doc-v2") is None
    finally:
        session.close()
        engine.dispose()


def test_validation_rejects_cross_asset_rendition_ownership() -> None:
    candidate = _asset_candidate(
        asset_a_renditions=("r1",),
        asset_b_renditions=(),
        rendition_owner="asset-b",
    )

    with pytest.raises(ValueError, match="rendition registry does not match rendition ownership"):
        validate_candidate_v2(candidate)


def test_validation_rejects_rendition_omitted_from_owning_asset_registry() -> None:
    candidate = _asset_candidate(asset_a_renditions=(), rendition_owner="asset-a")

    with pytest.raises(ValueError, match="missing owned renditions"):
        validate_candidate_v2(candidate)


def test_validation_rejects_duplicate_rendition_ids_inside_asset_registry() -> None:
    candidate = _asset_candidate(asset_a_renditions=("r1", "r1"), rendition_owner="asset-a")

    with pytest.raises(ValueError, match="duplicate rendition_id in asset asset-a"):
        validate_candidate_v2(candidate)
