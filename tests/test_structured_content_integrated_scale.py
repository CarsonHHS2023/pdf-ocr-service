from __future__ import annotations

from dataclasses import replace
from time import perf_counter
from sqlalchemy import event

from app.processing_runs import ProcessingRunCreate, ProcessingRunRepository
from app.structured_content.identity import ContentCandidateId, ContentLineageKey, DocumentRef, ProcessingRunRef
from app.structured_content.repository import StructuredContentCandidateRepository
from app.structured_content.selection_repository import StructuredContentSelectionRepository
from app.structured_content.serialization import serialize_structured_content_candidate
from tests.structured_content.candidate_factory import make_asset_evidence_warning_candidate, make_linear_candidate, make_table_candidate
from tests.structured_content.integration_factory import add_document, candidate_for, sqlite_session


def _timed(limit, fn):
    start=perf_counter(); out=fn(); duration=perf_counter()-start
    assert duration < limit
    return out


def test_large_candidate_table_assets_many_runs_and_multi_document_scale_with_query_characterization():
    session, engine = sqlite_session(); crepo=StructuredContentCandidateRepository(); rrepo=ProcessingRunRepository(); srepo=StructuredContentSelectionRepository()
    counts=[]
    @event.listens_for(engine, "before_cursor_execute")
    def count(conn, cursor, statement, params, ctx, execmany): counts.append(statement)
    try:
        add_document(session,"doc", source_file_id="source-file")
        rrepo.create_run(session, ProcessingRunCreate("run-large","doc","source-file"))
        large = replace(make_linear_candidate(100,10), document_ref=DocumentRef("doc"), candidate_id=ContentCandidateId("large"), lineage_key=ContentLineageKey("lineage-large"), processing_run_ref=ProcessingRunRef("run-large"))
        _timed(20, lambda: crepo.create_candidate(session, large))
        before=len(counts); got=_timed(20, lambda: crepo.get_candidate(session,"large")); read_q=len(counts)-before
        assert got == large and serialize_structured_content_candidate(got) == serialize_structured_content_candidate(large)
        assert read_q < 80
        before=len(counts); _timed(5, lambda: srepo.set_selection(session, document_ref="doc", candidate_id="large", expected_version=0)); assert len(counts)-before < 30
        rrepo.create_run(session, ProcessingRunCreate("run-table","doc"))
        table = replace(make_table_candidate(50,10), document_ref=DocumentRef("doc"), candidate_id=ContentCandidateId("table"), lineage_key=ContentLineageKey("lineage-table"), processing_run_ref=ProcessingRunRef("run-table"))
        crepo.create_candidate(session, table); assert serialize_structured_content_candidate(crepo.get_candidate(session,"table")) == serialize_structured_content_candidate(table)
        rrepo.create_run(session, ProcessingRunCreate("run-assets","doc"))
        assets = replace(make_asset_evidence_warning_candidate(100,50,50), document_ref=DocumentRef("doc"), candidate_id=ContentCandidateId("assets"), lineage_key=ContentLineageKey("lineage-assets-scale"), processing_run_ref=ProcessingRunRef("run-assets"))
        crepo.create_candidate(session, assets); assert serialize_structured_content_candidate(crepo.get_candidate(session,"assets")) == serialize_structured_content_candidate(assets)
        add_document(session,"runs")
        for i in range(100):
            rrepo.create_run(session, ProcessingRunCreate(f"r{i:03}","runs"))
            if i < 20: crepo.create_candidate(session, candidate_for("runs", f"c{i:03}", run=f"r{i:03}"))
        before=len(counts); listed=_timed(15, lambda: rrepo.list_runs_for_document(session,"runs")); assert len(listed)==100 and len(counts)-before < 10
        assert srepo.get_selection(session,"runs") is None
        srepo.set_selection(session, document_ref="runs", candidate_id="c010", expected_version=0)
        before=len(counts); candidates=crepo.list_candidates_for_document(session,"runs"); assert len(candidates)==20 and len(counts)-before < 10
        for d in range(10):
            doc=f"md-{d}"; add_document(session,doc)
            for i in range(10): rrepo.create_run(session, ProcessingRunCreate(f"{doc}-run-{i}",doc))
            crepo.create_candidate(session, candidate_for(doc, f"{doc}-cand"))
        assert all(len(rrepo.list_runs_for_document(session, f"md-{d}")) == 10 for d in range(10))
        assert all([x.candidate_id for x in crepo.list_candidates_for_document(session, f"md-{d}")] == [f"md-{d}-cand"] for d in range(10))
    finally:
        session.close(); engine.dispose()
