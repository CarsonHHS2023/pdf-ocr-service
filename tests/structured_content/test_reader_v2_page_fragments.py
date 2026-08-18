from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Document, ProcessingRun
import app.models_v2  # noqa: F401
import app.models_v2_selection  # noqa: F401
from app.processing.normalized_observations import NormalizedObservationBundle
from app.processing.pdf_recovery import recover_pdf_observations_to_spr_v2
from app.processing.structured_result_v2.model import ProcessingEvidence, ProcessingObservation
from app.reader_v2.api_models import reader_v2_content_response
from app.reader_v2.contracts import ReaderContentChunkV2
from app.reader_v2.service import build_selected_reader_v2_document
from app.source_units import SourceUnit, SourceUnitDimensions, SourceUnitKind, SpatialAnchor
from app.structured_content_v2.repository import StructuredContentCandidateV2Repository
from app.structured_content_v2.selection import StructuredContentV2SelectionRepository
from app.structured_content_v2.transformation import TransformationContextV2, transform_spr_v2_to_candidate


def _unit(page: int) -> SourceUnit:
    return SourceUnit(
        source_unit_id=f"p{page}",
        kind=SourceUnitKind.PHYSICAL_PAGE,
        source_order=page - 1,
        source_ref="pdf",
        dimensions=SourceUnitDimensions(600, 800),
    )


def _observation(page: int, text: str, top: float, bottom: float):
    unit_id = f"p{page}"
    observation_id = f"obs-{page}"
    evidence_id = f"ev-{page}"
    anchor = SpatialAnchor(unit_id, 0.1, top, 0.9, bottom)
    return (
        ProcessingObservation(
            observation_id=observation_id,
            source_unit_id=unit_id,
            order=0,
            observed_kind="text",
            text=text,
            anchors=(anchor,),
            confidence=0.9,
            evidence_ids=(evidence_id,),
        ),
        ProcessingEvidence(
            evidence_id=evidence_id,
            source_unit_id=unit_id,
            anchors=(anchor,),
            observation_id=observation_id,
            processing_run_ref="run",
            raw_result_ref="raw",
        ),
    )


def test_cross_page_fragments_reach_reader_api_without_replacing_canonical_text() -> None:
    first, first_evidence = _observation(1, "First page fragment", 0.84, 0.96)
    second, second_evidence = _observation(2, "continues on page two.", 0.02, 0.14)
    bundle = NormalizedObservationBundle(
        document_ref="doc-fragments",
        source_ref="pdf",
        processing_run_ref="run",
        raw_result_ref="raw",
        source_units=(_unit(1), _unit(2)),
        observations=(first, second),
        evidence=(first_evidence, second_evidence),
    )

    spr = recover_pdf_observations_to_spr_v2(bundle)
    assert len(spr.nodes) == 1
    assert spr.nodes[0].text == "First page fragment continues on page two."
    fragments = spr.nodes[0].metadata["page_fragments"]
    assert [fragment["source_unit_id"] for fragment in fragments] == ["p1", "p2"]
    assert [fragment["text"] for fragment in fragments] == [
        "First page fragment",
        "continues on page two.",
    ]
    assert fragments[0]["source_anchor"]["normalized_bbox"] == (0.1, 0.84, 0.9, 0.96)

    candidate = transform_spr_v2_to_candidate(
        spr,
        context=TransformationContextV2(
            document_ref="doc-fragments",
            candidate_id="candidate-fragments",
            lineage_key="lineage-fragments",
            structured_processing_result_ref="spr-fragments",
        ),
    )
    assert candidate.nodes[0].metadata["page_fragments"] == fragments

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    candidates = StructuredContentCandidateV2Repository()
    selections = StructuredContentV2SelectionRepository(candidates)
    try:
        with factory.begin() as session:
            session.add(Document(id="doc-fragments", title="Fragments", file_type="pdf", status="completed"))
            session.add(
                ProcessingRun(
                    processing_run_id="run",
                    document_id="doc-fragments",
                    status="succeeded",
                    raw_result_ref="raw",
                    structured_processing_result_ref="spr-fragments",
                )
            )
            candidates.create_candidate(session, candidate)
            selections.set_selection(
                session,
                document_ref="doc-fragments",
                candidate_id="candidate-fragments",
                expected_version=0,
                selection_actor_ref="test",
            )

        with factory() as session:
            view = build_selected_reader_v2_document(session=session, document_ref="doc-fragments")

        assert view.nodes[0].text == "First page fragment continues on page two."
        assert view.nodes[0].metadata["page_fragments"] == fragments
        response = reader_v2_content_response(
            view,
            ReaderContentChunkV2(
                document_ref=view.document_ref,
                candidate_id=view.candidate_id,
                nodes=view.nodes,
                has_more=False,
            ),
        )
        payload = response.model_dump(mode="json")
        assert payload["nodes"][0]["text"] == "First page fragment continues on page two."
        assert payload["nodes"][0]["metadata"]["page_fragments"][0]["source_anchor"]["normalized_bbox"] == [0.1, 0.84, 0.9, 0.96]
        assert [fragment["text"] for fragment in payload["nodes"][0]["metadata"]["page_fragments"]] == [
            "First page fragment",
            "continues on page two.",
        ]
    finally:
        engine.dispose()
