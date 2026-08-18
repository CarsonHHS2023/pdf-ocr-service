from __future__ import annotations

from dataclasses import replace
import pytest

from app.processing_runs import ProcessingRunConflict, ProcessingRunCreate, ProcessingRunInvalidTransition, ProcessingRunRepository
from app.structured_content.errors import CandidateSelectionConflict, StructuredContentCandidateConflict
from app.structured_content.identity import ContentCandidateId, ContentLineageKey
from app.structured_content.repository import StructuredContentCandidateRepository
from app.structured_content.selection_repository import StructuredContentSelectionRepository
from tests.structured_content.integration_assertions import candidate_row_snapshot, selection_count
from tests.structured_content.integration_factory import add_document, candidate_for, sqlite_session


def test_selection_races_are_deterministic_under_sqlite_single_connection_simulation():
    session, engine = sqlite_session(); crepo=StructuredContentCandidateRepository(); srepo=StructuredContentSelectionRepository()
    try:
        add_document(session,"doc")
        for cid in ("a","b","c"):
            crepo.create_candidate(session, candidate_for("doc", cid))
        snap = candidate_row_snapshot(session,"a")
        assert srepo.set_selection(session, document_ref="doc", candidate_id="a", expected_version=0).selection_version == 1
        with pytest.raises(CandidateSelectionConflict): srepo.set_selection(session, document_ref="doc", candidate_id="b", expected_version=0)
        assert selection_count(session,"doc") == 1 and candidate_row_snapshot(session,"a") == snap
        assert srepo.set_selection(session, document_ref="doc", candidate_id="b", expected_version=1).selection_version == 2
        with pytest.raises(CandidateSelectionConflict): srepo.set_selection(session, document_ref="doc", candidate_id="c", expected_version=1)
        before = srepo.get_selection(session,"doc")
        assert srepo.set_selection(session, document_ref="doc", candidate_id="b", expected_version=2) == before
        with pytest.raises(CandidateSelectionConflict): srepo.set_selection(session, document_ref="doc", candidate_id="b", expected_version=1)
    finally:
        session.close(); engine.dispose()


def test_candidate_create_concurrency_idempotency_and_conflict_leave_one_graph_no_selection():
    session, engine = sqlite_session(); crepo=StructuredContentCandidateRepository()
    try:
        add_document(session,"doc")
        a = candidate_for("doc", "same")
        assert crepo.create_candidate(session, a) == a
        assert crepo.create_candidate(session, a) == a
        conflicting = replace(a, lineage_key=ContentLineageKey("different-lineage"))
        with pytest.raises(StructuredContentCandidateConflict): crepo.create_candidate(session, conflicting)
        assert [x.candidate_id for x in crepo.list_candidates_for_document(session,"doc")] == ["same"]
        assert selection_count(session,"doc") == 0
    finally:
        session.close(); engine.dispose()


def test_processing_run_create_and_transition_concurrency_contracts_do_not_select():
    session, engine = sqlite_session(); rrepo=ProcessingRunRepository()
    try:
        add_document(session,"doc")
        run = ProcessingRunCreate("run", "doc", idempotency_key="idem", provider_ref="p")
        assert rrepo.create_run(session, run) == rrepo.create_run(session, run)
        with pytest.raises(ProcessingRunConflict): rrepo.create_run(session, replace(run, provider_ref="different"))
        with pytest.raises(ProcessingRunConflict): rrepo.create_run(session, ProcessingRunCreate("run-2", "doc", idempotency_key="idem"))
        rrepo.mark_running(session,"run")
        rrepo.mark_succeeded(session,"run")
        with pytest.raises(ProcessingRunInvalidTransition): rrepo.mark_failed(session,"run")
        with pytest.raises(ProcessingRunInvalidTransition): rrepo.mark_running(session,"run")
        assert selection_count(session,"doc") == 0
    finally:
        session.close(); engine.dispose()
