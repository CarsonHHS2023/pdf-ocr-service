from __future__ import annotations

import pytest
from sqlalchemy import event, text

from app.models import ProcessingRun, StructuredContentCandidate as CandidateRow, StructuredContentNode, StructuredContentSelection
from app.processing_runs import PersistedProcessingRunCorrupt, ProcessingRunCreate, ProcessingRunPersistenceError, ProcessingRunRepository
from app.structured_content.errors import CandidatePersistenceError, CandidateSelectionConflict, CandidateSelectionCorrupt, CandidateSelectionPersistenceError, PersistedCandidateCorrupt
from app.structured_content.repository import StructuredContentCandidateRepository
from app.structured_content.selection_repository import StructuredContentSelectionRepository
from tests.structured_content.integration_assertions import candidate_row_snapshot, legacy_counts, selection_count
from tests.structured_content.integration_factory import add_document, candidate_for, sqlite_session


def test_entire_lifecycle_outer_rollback_and_session_reuse():
    session, engine = sqlite_session(); crepo=StructuredContentCandidateRepository(); rrepo=ProcessingRunRepository(); srepo=StructuredContentSelectionRepository()
    try:
        add_document(session, "doc", source_file_id="source-file"); session.commit(); legacy_before=legacy_counts(session)
        rrepo.create_run(session, ProcessingRunCreate("run", "doc", "source-file")); rrepo.mark_running(session,"run")
        crepo.create_candidate(session, candidate_for("doc", "cand", run="run"))
        srepo.set_selection(session, document_ref="doc", candidate_id="cand", expected_version=0)
        rrepo.mark_succeeded(session,"run")
        assert selection_count(session,"doc") == 1 and rrepo.run_exists(session,"run")
        session.rollback()
        assert not rrepo.run_exists(session,"run")
        assert session.query(CandidateRow).count() == 0 and selection_count(session,"doc") == 0
        assert legacy_counts(session) == legacy_before
        rrepo.create_run(session, ProcessingRunCreate("after", "doc")); assert rrepo.run_exists(session,"after")
    finally:
        session.close(); engine.dispose()


def test_committed_candidate_survives_selection_rollback_and_failed_replacement_preserves_prior_selection():
    session, engine = sqlite_session(); crepo=StructuredContentCandidateRepository(); rrepo=ProcessingRunRepository(); srepo=StructuredContentSelectionRepository()
    try:
        add_document(session, "doc", source_file_id="source-file")
        rrepo.create_run(session, ProcessingRunCreate("run", "doc", "source-file"))
        a = candidate_for("doc", "a", run="run"); b = candidate_for("doc", "b", run="run")
        crepo.create_candidate(session, a); crepo.create_candidate(session, b); session.commit()
        srepo.set_selection(session, document_ref="doc", candidate_id="a", expected_version=0); session.rollback()
        assert crepo.candidate_exists(session,"a") and rrepo.run_exists(session,"run") and srepo.get_selection(session,"doc") is None
        first = srepo.set_selection(session, document_ref="doc", candidate_id="a", expected_version=0, selected_by="one", reason="first"); session.commit()
        snap = candidate_row_snapshot(session, "a")
        with pytest.raises(CandidateSelectionConflict): srepo.set_selection(session, document_ref="doc", candidate_id="b", expected_version=0)
        session.rollback()
        assert srepo.get_selection(session,"doc") == first
        assert candidate_row_snapshot(session, "a") == snap
    finally:
        session.close(); engine.dispose()


def test_failure_injection_rolls_back_candidate_selection_and_run_boundaries():
    session, engine = sqlite_session(); crepo=StructuredContentCandidateRepository(); rrepo=ProcessingRunRepository(); srepo=StructuredContentSelectionRepository()
    try:
        add_document(session, "doc", source_file_id="source-file")
        @event.listens_for(session, "before_flush")
        def fail_run(sess, ctx, instances):
            if any(isinstance(o, ProcessingRun) and o.processing_run_id == "fail-run" for o in sess.new):
                raise RuntimeError("run flush boom")
        with pytest.raises(RuntimeError): rrepo.create_run(session, ProcessingRunCreate("fail-run", "doc"))
        event.remove(session, "before_flush", fail_run); session.rollback(); assert not rrepo.run_exists(session,"fail-run")
        rrepo.create_run(session, ProcessingRunCreate("run", "doc", "source-file")); session.commit()
        @event.listens_for(session, "before_flush")
        def fail_candidate(sess, ctx, instances):
            if any(isinstance(o, StructuredContentNode) for o in sess.new):
                raise RuntimeError("candidate graph boom")
        with pytest.raises(RuntimeError): crepo.create_candidate(session, candidate_for("doc", "bad", run="run"))
        event.remove(session, "before_flush", fail_candidate); session.rollback(); assert session.query(CandidateRow).filter_by(candidate_id="bad").count() == 0
        good = candidate_for("doc", "good", run="run"); crepo.create_candidate(session, good); session.commit()
        @event.listens_for(session, "before_flush")
        def fail_selection(sess, ctx, instances):
            if any(isinstance(o, StructuredContentSelection) for o in sess.new):
                raise RuntimeError("selection boom")
        with pytest.raises(RuntimeError): srepo.set_selection(session, document_ref="doc", candidate_id="good", expected_version=0)
        event.remove(session, "before_flush", fail_selection); session.rollback(); assert srepo.get_selection(session,"doc") is None
        srepo.set_selection(session, document_ref="doc", candidate_id="good", expected_version=0); session.commit(); before=srepo.get_selection(session,"doc")
        session.execute(text("update structured_content_selection set selection_version=99 where document_id='doc'")); session.flush()
        with pytest.raises(CandidateSelectionConflict): srepo.set_selection(session, document_ref="doc", candidate_id="good", expected_version=1)
        session.rollback(); assert srepo.get_selection(session,"doc") == before
        rrepo.mark_running(session,"run"); session.commit()
        @event.listens_for(session, "before_flush")
        def fail_transition(sess, ctx, instances):
            if sess.dirty: raise RuntimeError("transition boom")
        with pytest.raises(RuntimeError): rrepo.mark_succeeded(session,"run")
        event.remove(session, "before_flush", fail_transition); session.rollback(); assert rrepo.get_run(session,"run").status == "running"
    finally:
        session.close(); engine.dispose()


def test_candidate_malformed_json_corruption_is_bounded_and_does_not_fallback_or_repair():
    session, engine = sqlite_session(); crepo=StructuredContentCandidateRepository(); srepo=StructuredContentSelectionRepository()
    try:
        add_document(session, "doc")
        a = candidate_for("doc", "selected")
        b = candidate_for("doc", "latest")
        crepo.create_candidate(session, a); crepo.create_candidate(session, b)
        selected = srepo.set_selection(session, document_ref="doc", candidate_id="selected", expected_version=0)
        row_before = candidate_row_snapshot(session, "selected")
        session.execute(text("update structured_content_nodes set extensions_json='{' where candidate_id=(select id from structured_content_candidates where candidate_id='selected')")); session.flush()
        with pytest.raises(PersistedCandidateCorrupt) as excinfo:
            crepo.get_candidate(session, "selected")
        assert "provider_payload" not in str(excinfo.value) and "Text 0" not in str(excinfo.value)
        with pytest.raises(CandidateSelectionCorrupt):
            srepo.get_selected_candidate(session, "doc")
        assert srepo.get_selection(session, "doc") == selected
        assert srepo.get_selection(session, "doc").candidate_id != "latest"
        assert candidate_row_snapshot(session, "selected") == row_before
    finally:
        session.close(); engine.dispose()


def test_candidate_semantic_corruption_is_detected_without_repair_or_latest_fallback():
    session, engine = sqlite_session(); crepo=StructuredContentCandidateRepository(); srepo=StructuredContentSelectionRepository()
    try:
        add_document(session, "doc")
        corrupt = candidate_for("doc", "semantic")
        latest = candidate_for("doc", "latest")
        crepo.create_candidate(session, corrupt); crepo.create_candidate(session, latest)
        srepo.set_selection(session, document_ref="doc", candidate_id="latest", expected_version=0)
        before = candidate_row_snapshot(session, "semantic")
        session.execute(text("update structured_content_candidates set no_usable_page_count=7 where candidate_id='semantic'")); session.flush()
        with pytest.raises(PersistedCandidateCorrupt):
            crepo.get_candidate(session, "semantic")
        assert candidate_row_snapshot(session, "semantic") == before
        assert srepo.get_selection(session, "doc").candidate_id == "latest"
    finally:
        session.close(); engine.dispose()


def test_processing_run_malformed_json_corruption_is_bounded_and_selection_unchanged():
    session, engine = sqlite_session(); crepo=StructuredContentCandidateRepository(); rrepo=ProcessingRunRepository(); srepo=StructuredContentSelectionRepository()
    try:
        add_document(session, "doc")
        rrepo.create_run(session, ProcessingRunCreate("run", "doc", metrics={"ok": True}))
        candidate = candidate_for("doc", "cand", run="run")
        crepo.create_candidate(session, candidate)
        selected = srepo.set_selection(session, document_ref="doc", candidate_id="cand", expected_version=0)
        run_before = session.execute(text("select processing_run_id, status, metrics_json, extensions_json from processing_runs where processing_run_id='run'" )).one()
        session.execute(text("update processing_runs set metrics_json='{' where processing_run_id='run'")); session.flush()
        with pytest.raises(PersistedProcessingRunCorrupt) as excinfo:
            rrepo.get_run(session, "run")
        assert "provider_payload" not in str(excinfo.value) and "ok" not in str(excinfo.value)
        assert srepo.get_selection(session, "doc") == selected
        assert crepo.get_candidate(session, "cand") == candidate
        repaired = session.execute(text("select processing_run_id, status, metrics_json, extensions_json from processing_runs where processing_run_id='run'" )).one()
        assert repaired[0] == run_before[0] and repaired[1] == run_before[1] and repaired[2] == "{"
    finally:
        session.close(); engine.dispose()


def test_processing_run_unsupported_status_corruption_is_bounded_without_selection_or_candidate_mutation():
    session, engine = sqlite_session(); crepo=StructuredContentCandidateRepository(); rrepo=ProcessingRunRepository(); srepo=StructuredContentSelectionRepository()
    try:
        add_document(session, "doc")
        rrepo.create_run(session, ProcessingRunCreate("run", "doc"))
        candidate = candidate_for("doc", "cand", run="run")
        crepo.create_candidate(session, candidate)
        selected = srepo.set_selection(session, document_ref="doc", candidate_id="cand", expected_version=0)
        snap = candidate_row_snapshot(session, "cand")
        session.execute(text("PRAGMA ignore_check_constraints=ON"))
        session.execute(text("update processing_runs set status='alien' where processing_run_id='run'")); session.flush()
        with pytest.raises(PersistedProcessingRunCorrupt) as excinfo:
            rrepo.get_run(session, "run")
        assert "alien" in str(excinfo.value) and "provider_payload" not in str(excinfo.value)
        assert srepo.get_selection(session, "doc") == selected
        assert candidate_row_snapshot(session, "cand") == snap
    finally:
        session.close(); engine.dispose()
