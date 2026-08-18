from __future__ import annotations

from dataclasses import replace

import pytest
from pathlib import Path
from sqlalchemy import text

from app.models import ProcessingRun, StructuredContentCandidate as CandidateRow, StructuredContentSelection
from app.processing_runs import ProcessingRunCreate, ProcessingRunRepository
from app.structured_content.errors import StructuredContentCandidateConflict
from app.structured_content.identity import ContentCandidateId, ContentLineageKey, DocumentRef, ProcessingRunRef
from app.structured_content.repository import StructuredContentCandidateRepository
from app.structured_content.selection_repository import StructuredContentSelectionRepository
from app.structured_content.serialization import serialize_structured_content_candidate
from app.structured_document.service import NoSelectedStructuredContent, build_selected_document_projection
from tests.structured_content.candidate_factory import make_asset_evidence_warning_candidate, make_linear_candidate, make_table_candidate
from tests.structured_content.integration_factory import add_document, candidate_for, sqlite_session


def _repos():
    crepo = StructuredContentCandidateRepository()
    srepo = StructuredContentSelectionRepository(crepo)
    rrepo = ProcessingRunRepository()
    return crepo, srepo, rrepo


def _project(session, crepo, srepo, doc="doc"):
    return build_selected_document_projection(
        session=session,
        document_ref=doc,
        candidate_repository=crepo,
        selection_repository=srepo,
    )


def _counts(session):
    return {
        "candidates": session.query(CandidateRow).count(),
        "selections": session.query(StructuredContentSelection).count(),
        "runs": session.query(ProcessingRun).count(),
    }


def _with_identity(candidate, *, doc: str, candidate_id: str, run: str | None = None):
    return replace(
        candidate,
        document_ref=DocumentRef(doc),
        candidate_id=ContentCandidateId(candidate_id),
        lineage_key=ContentLineageKey(f"lineage-{candidate_id}"),
        processing_run_ref=ProcessingRunRef(run) if run else None,
    )


def test_service_requires_explicit_selection_and_never_auto_selects_latest_candidate():
    session, _ = sqlite_session()
    crepo, srepo, _ = _repos()
    add_document(session, "doc", source_file_id="source-file")
    a = candidate_for("doc", "candidate-a", pages=1, nodes=2)
    b = candidate_for("doc", "candidate-b", pages=1, nodes=2)

    crepo.create_candidate(session, a)
    assert srepo.get_selection(session, "doc") is None
    with pytest.raises(NoSelectedStructuredContent):
        _project(session, crepo, srepo)
    assert _counts(session) == {"candidates": 1, "selections": 0, "runs": 0}

    srepo.set_selection(session, document_ref="doc", candidate_id="candidate-a", expected_version=0)
    projection_a = _project(session, crepo, srepo)
    assert projection_a.source.source_candidate_id == a.candidate_id
    assert [entry.text for entry in projection_a.entries] == ["Text 0", "Text 1"]

    crepo.create_candidate(session, b)
    projection_after_b = _project(session, crepo, srepo)
    assert projection_after_b == projection_a
    assert projection_after_b.source.source_candidate_id == a.candidate_id
    assert srepo.get_selection(session, "doc").candidate_id == "candidate-a"
    assert _counts(session) == {"candidates": 2, "selections": 1, "runs": 0}


def test_explicit_selection_switch_and_rollback_rebuilds_deterministically_without_mutation():
    session, _ = sqlite_session()
    crepo, srepo, _ = _repos()
    add_document(session, "doc", source_file_id="source-file")
    a = candidate_for("doc", "candidate-a", pages=2, nodes=2)
    b = replace(candidate_for("doc", "candidate-b", pages=2, nodes=2), extensions={"org.atlas.fixture": "linear-b"})
    b = replace(b, nodes=tuple(replace(n, text=f"B {i}") for i, n in enumerate(b.nodes)))
    crepo.create_candidate(session, a)
    crepo.create_candidate(session, b)

    srepo.set_selection(session, document_ref="doc", candidate_id="candidate-a", expected_version=0, reason="select a")
    before = _counts(session)
    a_first = _project(session, crepo, srepo)
    repeated = tuple(_project(session, crepo, srepo) for _ in range(5))
    assert all(projection == a_first for projection in repeated)
    assert [entry.text for entry in a_first.entries] == ["Text 0", "Text 1", "Text 2", "Text 3"]
    assert _counts(session) == before

    srepo.set_selection(session, document_ref="doc", candidate_id="candidate-b", expected_version=1, reason="select b")
    b_projection = _project(session, crepo, srepo)
    assert b_projection.source.source_candidate_id == b.candidate_id
    assert [entry.text for entry in b_projection.entries] == ["B 0", "B 1", "B 2", "B 3"]

    assert serialize_structured_content_candidate(crepo.get_candidate(session, "candidate-a")) == serialize_structured_content_candidate(a)
    assert serialize_structured_content_candidate(crepo.get_candidate(session, "candidate-b")) == serialize_structured_content_candidate(b)

    srepo.rollback_selection(session, document_ref="doc", candidate_id="candidate-a", expected_version=2, reason="rollback a")
    a_rollback = _project(session, crepo, srepo)
    assert a_rollback == a_first
    assert srepo.get_selection(session, "doc").candidate_id == "candidate-a"
    assert _counts(session) == {"candidates": 2, "selections": 1, "runs": 0}


def test_repository_roundtrip_idempotency_conflict_and_provenance_are_preserved():
    session, _ = sqlite_session()
    crepo, srepo, rrepo = _repos()
    add_document(session, "doc", source_file_id="source-file")
    rrepo.create_run(session, ProcessingRunCreate("run-a", "doc", "source-file", raw_result_ref="raw-a", structured_processing_result_ref="spr-a"))
    candidate = _with_identity(make_linear_candidate(1, 3), doc="doc", candidate_id="candidate-a", run="run-a")
    candidate = replace(candidate, raw_result_ref=candidate.raw_result_ref, structured_processing_result_ref=candidate.structured_processing_result_ref)

    assert crepo.create_candidate(session, candidate) == candidate
    assert crepo.create_candidate(session, candidate) == candidate
    conflicting = replace(candidate, extensions={"org.atlas.conflict": "different"})
    with pytest.raises(StructuredContentCandidateConflict):
        crepo.create_candidate(session, conflicting)

    roundtrip = crepo.get_candidate(session, "candidate-a")
    assert serialize_structured_content_candidate(roundtrip) == serialize_structured_content_candidate(candidate)
    srepo.set_selection(session, document_ref="doc", candidate_id="candidate-a", expected_version=0)
    projection = _project(session, crepo, srepo)
    assert projection.source.source_candidate_id == candidate.candidate_id
    assert projection.source.document_ref == candidate.document_ref
    assert projection.source.source_candidate_lineage_key == candidate.lineage_key
    assert roundtrip.processing_run_ref.value == "run-a"
    assert roundtrip.raw_result_ref.value == "raw-result"
    assert roundtrip.structured_processing_result_ref.value == "spr"
    assert all(entry.evidence_refs for entry in projection.entries)
    assert _counts(session) == {"candidates": 1, "selections": 1, "runs": 1}


def test_recovery_evidence_table_and_asset_integration_survive_service_projection():
    session, _ = sqlite_session()
    crepo, srepo, _ = _repos()
    add_document(session, "doc", source_file_id="source-file")
    asset_candidate = _with_identity(make_asset_evidence_warning_candidate(5, 2, 2), doc="doc", candidate_id="candidate-assets")
    crepo.create_candidate(session, asset_candidate)
    srepo.set_selection(session, document_ref="doc", candidate_id="candidate-assets", expected_version=0)
    asset_projection = _project(session, crepo, srepo)
    assert asset_projection.entries[0].source_asset_ref == asset_candidate.assets[0].asset_id
    assert asset_projection.entries[0].evidence_refs == asset_candidate.nodes[0].evidence_ids
    assert asset_projection.recovery.warning_refs == asset_candidate.recovery_summary.warning_ids

    table_candidate = _with_identity(make_table_candidate(2, 2), doc="doc", candidate_id="candidate-table")
    table_asset = asset_candidate.assets[0]
    table_node = replace(
        table_candidate.nodes[0],
        asset_ids=(table_asset.asset_id,),
        attributes=replace(table_candidate.nodes[0].attributes, rendered_asset_id=table_asset.asset_id),
    )
    table_candidate = replace(table_candidate, nodes=(table_node,), assets=(table_asset,))
    crepo.create_candidate(session, table_candidate)
    srepo.set_selection(session, document_ref="doc", candidate_id="candidate-table", expected_version=1)
    table_projection = _project(session, crepo, srepo)
    assert table_projection.entries[0].source_asset_ref == table_asset.asset_id
    assert [loss.code.value for loss in table_projection.losses] == ["table_structure_dropped"]


def test_integrated_scale_regression_uses_selected_reconstructed_candidate():
    session, _ = sqlite_session()
    crepo, srepo, _ = _repos()
    add_document(session, "doc-scale", source_file_id="source-file")
    candidate = candidate_for("doc-scale", "candidate-scale", pages=100, nodes=100)
    crepo.create_candidate(session, candidate)
    srepo.set_selection(session, document_ref="doc-scale", candidate_id="candidate-scale", expected_version=0)

    projection = _project(session, crepo, srepo, doc="doc-scale")
    second = _project(session, crepo, srepo, doc="doc-scale")
    assert projection == second
    assert len(projection.entries) == 10_000
    assert projection.source.source_candidate_id.value == "candidate-scale"
    assert len({entry.source_node_ref for entry in projection.entries}) == 10_000
    assert all(entry.source_node_ref.value.startswith("node-") for entry in projection.entries)
    assert _counts(session) == {"candidates": 1, "selections": 1, "runs": 0}


def test_service_import_boundary_has_no_reader_or_provider_coupling():
    service = Path("app/structured_document/service.py").read_text(encoding="utf-8")
    forbidden = tuple("Mineru Result|Content Block|Pdf Page|Book Image|app .routers|fast api|mod al|pad dle|min eru|requ ests|htt px|bo to3".replace(" ", "").split("|"))
    assert not any(term in service for term in forbidden)
    assembler = Path("app/structured_document/assembler.py").read_text(encoding="utf-8")
    projector = Path("app/structured_document/projection/projector.py").read_text(encoding="utf-8")
    assert "StructuredContentCandidateRepository" not in assembler + projector
    assert "StructuredContentSelectionRepository" not in assembler + projector


def test_no_projection_or_structured_document_tables_are_persisted():
    session, engine = sqlite_session()
    crepo, srepo, _ = _repos()
    add_document(session, "doc", source_file_id="source-file")
    crepo.create_candidate(session, candidate_for("doc", "candidate-a"))
    srepo.set_selection(session, document_ref="doc", candidate_id="candidate-a", expected_version=0)
    tables_before = set(session.execute(text("select name from sqlite_master where type='table'")).scalars())
    before = _counts(session)
    _project(session, crepo, srepo)
    tables_after = set(session.execute(text("select name from sqlite_master where type='table'")).scalars())
    assert tables_after == tables_before
    assert not any("projection" in table or "structured_document" in table for table in tables_after)
    assert _counts(session) == before
