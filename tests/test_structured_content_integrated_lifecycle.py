from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest
from sqlalchemy import text

from app.models import ProcessingRun
from app.processing_runs import ProcessingRunCreate, ProcessingRunInvalidTransition, ProcessingRunRepository
from app.structured_content.errors import CandidateProcessingRunMismatch, CandidateSelectionDocumentMismatch, CandidateSelectionCorrupt
from app.structured_content.identity import ContentCandidateId, ContentLineageKey, DocumentRef, ProcessingRunRef
from app.structured_content.repository import StructuredContentCandidateRepository
from app.structured_content.selection_repository import StructuredContentSelectionRepository
from app.structured_content.serialization import serialize_structured_content_candidate
from app.structured_content.validation import validate_content_candidate
from tests.structured_content.candidate_factory import make_asset_evidence_warning_candidate, make_linear_candidate
from tests.structured_content.fixture_loader import load_candidate
from tests.structured_content.integration_assertions import assert_legacy_snapshot_unchanged, canonical, candidate_row_snapshot, legacy_counts, seed_representative_legacy_rows, selection_count, snapshot_legacy_rows
from tests.structured_content.integration_factory import add_document, candidate_for, sqlite_session, with_identity


def test_integrated_happy_path_lifecycle_preserves_explicit_selection_and_legacy_rows():
    session, engine = sqlite_session(); crepo=StructuredContentCandidateRepository(); rrepo=ProcessingRunRepository(); srepo=StructuredContentSelectionRepository()
    try:
        add_document(session, "doc", source_file_id="source-file")
        legacy_before = legacy_counts(session)
        run_created = rrepo.create_run(session, ProcessingRunCreate("run", "doc", "source-file", provider_ref="provider"))
        assert run_created.status == "created" and selection_count(session, "doc") == 0
        rrepo.mark_running(session, "run", started_at=datetime(2026, 1, 1))
        candidate = candidate_for("doc", "cand", pages=2, nodes=2, run="run")
        persisted = crepo.create_candidate(session, candidate)
        before_row = candidate_row_snapshot(session, "cand")
        assert persisted == candidate
        assert srepo.get_selection(session, "doc") is None
        succeeded = rrepo.mark_succeeded(session, "run", completed_at=datetime(2026, 1, 2), metrics={"pages": 2})
        assert succeeded.status == "succeeded" and srepo.get_selection(session, "doc") is None
        selected = srepo.set_selection(session, document_ref="doc", candidate_id="cand", expected_version=0, selected_by="tester", reason="manual")
        assert selected.selection_version == 1
        got = srepo.get_selected_candidate(session, "doc")
        assert got == candidate
        assert canonical(got) == canonical(candidate)
        assert rrepo.get_run(session, "run").status == "succeeded"
        assert candidate_row_snapshot(session, "cand") == before_row
        assert legacy_counts(session) == legacy_before
    finally:
        session.close(); engine.dispose()


def test_multiple_runs_candidates_explicit_replacement_and_rollback_only():
    session, engine = sqlite_session(); crepo=StructuredContentCandidateRepository(); rrepo=ProcessingRunRepository(); srepo=StructuredContentSelectionRepository()
    try:
        add_document(session, "doc", source_file_id="source-file")
        for run in ("run-a", "run-b", "run-c"):
            rrepo.create_run(session, ProcessingRunCreate(run, "doc", "source-file"))
        a = candidate_for("doc", "cand-a", run="run-a")
        b = candidate_for("doc", "cand-b", run="run-b")
        c = candidate_for("doc", "cand-c")
        crepo.create_candidate(session, a); crepo.create_candidate(session, b); crepo.create_candidate(session, c)
        rrepo.mark_running(session, "run-b"); rrepo.mark_succeeded(session, "run-b")
        assert srepo.get_selection(session, "doc") is None
        first = srepo.set_selection(session, document_ref="doc", candidate_id="cand-a", expected_version=0)
        assert first.selection_version == 1
        assert srepo.set_selection(session, document_ref="doc", candidate_id="cand-b", expected_version=1).selection_version == 2
        assert srepo.rollback_selection(session, document_ref="doc", candidate_id="cand-a", expected_version=2).selection_version == 3
        assert [x.candidate_id for x in crepo.list_candidates_for_document(session, "doc")] == ["cand-a", "cand-b", "cand-c"]
        assert [x.processing_run_ref for x in rrepo.list_runs_for_document(session, "doc")] == ["run-a", "run-b", "run-c"]
    finally:
        session.close(); engine.dispose()


def test_failed_cancelled_and_degraded_candidates_do_not_drive_selection_or_quality_truth():
    session, engine = sqlite_session(); crepo=StructuredContentCandidateRepository(); rrepo=ProcessingRunRepository(); srepo=StructuredContentSelectionRepository()
    try:
        add_document(session, "doc", source_file_id="source-file")
        rrepo.create_run(session, ProcessingRunCreate("run-ok", "doc", "source-file")); rrepo.mark_running(session,"run-ok")
        base = candidate_for("doc", "base", run="run-ok"); crepo.create_candidate(session, base)
        srepo.set_selection(session, document_ref="doc", candidate_id="base", expected_version=0)
        for run, terminal in (("failed", rrepo.mark_failed), ("cancelled", rrepo.mark_cancelled)):
            rrepo.create_run(session, ProcessingRunCreate(run, "doc", "source-file")); rrepo.mark_running(session, run); terminal(session, run)
            assert srepo.get_selection(session, "doc").candidate_id == "base"
        linked = candidate_for("doc", "linked-failed", run="failed"); crepo.create_candidate(session, linked)
        assert crepo.get_candidate(session, "linked-failed") == linked
        warning = replace(make_asset_evidence_warning_candidate(10, 5, 5), document_ref=DocumentRef("doc"), candidate_id=ContentCandidateId("warning"), lineage_key=ContentLineageKey("lineage-warning"), processing_run_ref=ProcessingRunRef("failed"))
        degraded = replace(base, candidate_id=ContentCandidateId("degraded"), lineage_key=ContentLineageKey("lineage-degraded"), recovery_summary=replace(base.recovery_summary, degraded_pages=1))
        for cand in (linked, warning, degraded):
            if not crepo.candidate_exists(session, cand.candidate_id): crepo.create_candidate(session, cand)
            before = serialize_structured_content_candidate(cand)
            state = srepo.set_selection(session, document_ref="doc", candidate_id=cand.candidate_id, expected_version=srepo.get_selection(session,"doc").selection_version)
            assert state.candidate_id == cand.candidate_id.value
            assert serialize_structured_content_candidate(crepo.get_candidate(session, cand.candidate_id)) == before
        assert rrepo.get_run(session, "failed").status == "failed"
    finally:
        session.close(); engine.dispose()


def test_cross_document_protection_and_corrupt_selection_detection():
    session, engine = sqlite_session(); crepo=StructuredContentCandidateRepository(); rrepo=ProcessingRunRepository(); srepo=StructuredContentSelectionRepository()
    try:
        add_document(session, "doc-a", source_file_id="sf-a"); add_document(session, "doc-b", source_file_id="sf-b")
        rrepo.create_run(session, ProcessingRunCreate("run-a", "doc-a", "sf-a")); rrepo.create_run(session, ProcessingRunCreate("run-b", "doc-b", "sf-b"))
        cand_a = candidate_for("doc-a", "cand-a", run="run-a"); cand_b = candidate_for("doc-b", "cand-b", run="run-b")
        crepo.create_candidate(session, cand_a); crepo.create_candidate(session, cand_b)
        before = (selection_count(session), len(crepo.list_candidates_for_document(session,"doc-a")), len(rrepo.list_runs_for_document(session,"doc-a")))
        with pytest.raises(CandidateSelectionDocumentMismatch): srepo.set_selection(session, document_ref="doc-b", candidate_id="cand-a", expected_version=0)
        with pytest.raises(CandidateProcessingRunMismatch): crepo.create_candidate(session, with_identity(cand_a, doc="doc-a", candidate_id="bad-run", run="run-b"))
        with pytest.raises(Exception): rrepo.create_run(session, ProcessingRunCreate("bad-source", "doc-a", "sf-b"))
        assert before == (selection_count(session), len(crepo.list_candidates_for_document(session,"doc-a")), len(rrepo.list_runs_for_document(session,"doc-a")))
        assert [x.candidate_id for x in crepo.list_candidates_for_document(session,"doc-a")] == ["cand-a"]
        assert [x.processing_run_ref for x in rrepo.list_runs_for_document(session,"doc-b")] == ["run-b"]
        srepo.set_selection(session, document_ref="doc-a", candidate_id="cand-a", expected_version=0)
        id_b = session.execute(text("select id from structured_content_candidates where candidate_id='cand-b'")).scalar_one()
        session.execute(text("update structured_content_selection set candidate_id=:cid, selection_version=1 where document_id='doc-a'"), {"cid": id_b}); session.flush()
        with pytest.raises(CandidateSelectionCorrupt): srepo.get_selection(session, "doc-a")
    finally:
        session.close(); engine.dispose()


def test_no_usable_but_valid_candidate_round_trips_and_can_be_explicitly_selected():
    session, engine = sqlite_session(); crepo=StructuredContentCandidateRepository(); rrepo=ProcessingRunRepository(); srepo=StructuredContentSelectionRepository()
    try:
        add_document(session, "doc-no-usable", source_file_id="source-file-001")
        run = rrepo.create_run(session, ProcessingRunCreate("run-no-usable", "doc-no-usable", "source-file-001"))
        assert run.status == "created" and srepo.get_selection(session, "doc-no-usable") is None
        rrepo.mark_running(session, "run-no-usable")
        fixture = load_candidate("tests/fixtures/structured_content/v1/valid/no_usable_page_without_nodes/candidate.json")
        candidate = replace(fixture, document_ref=DocumentRef("doc-no-usable"), candidate_id=ContentCandidateId("cand-no-usable"), lineage_key=ContentLineageKey("lineage-no-usable"), processing_run_ref=ProcessingRunRef("run-no-usable"))
        assert validate_content_candidate(candidate).is_valid
        persisted = crepo.create_candidate(session, candidate)
        assert persisted == candidate
        assert canonical(persisted) == canonical(candidate)
        assert persisted.recovery_summary == candidate.recovery_summary and persisted.warnings == candidate.warnings
        assert srepo.get_selection(session, "doc-no-usable") is None
        rrepo.mark_succeeded(session, "run-no-usable")
        assert srepo.get_selection(session, "doc-no-usable") is None
        selected = srepo.set_selection(session, document_ref="doc-no-usable", candidate_id="cand-no-usable", expected_version=0, reason="explicit-no-usable")
        assert selected.candidate_id == "cand-no-usable" and selected.selection_version == 1
        selected_candidate = srepo.get_selected_candidate(session, "doc-no-usable")
        assert selected_candidate == candidate
        assert canonical(selected_candidate) == canonical(candidate)
    finally:
        session.close(); engine.dispose()


def test_integrated_lifecycle_preserves_representative_legacy_values_not_only_counts():
    session, engine = sqlite_session(); crepo=StructuredContentCandidateRepository(); rrepo=ProcessingRunRepository(); srepo=StructuredContentSelectionRepository()
    try:
        seed_representative_legacy_rows(session)
        add_document(session, "doc-values", source_file_id="source-file")
        before_counts = legacy_counts(session)
        before_values = snapshot_legacy_rows(session)
        rrepo.create_run(session, ProcessingRunCreate("run-values", "doc-values", "source-file")); rrepo.mark_running(session, "run-values")
        a = candidate_for("doc-values", "values-a", run="run-values")
        b = candidate_for("doc-values", "values-b", run="run-values")
        crepo.create_candidate(session, a); crepo.create_candidate(session, b)
        srepo.set_selection(session, document_ref="doc-values", candidate_id="values-a", expected_version=0)
        srepo.set_selection(session, document_ref="doc-values", candidate_id="values-b", expected_version=1)
        srepo.rollback_selection(session, document_ref="doc-values", candidate_id="values-a", expected_version=2)
        rrepo.mark_succeeded(session, "run-values")
        assert crepo.get_candidate(session, "values-a") == a
        assert rrepo.list_runs_for_document(session, "doc-values")[0].processing_run_ref == "run-values"
        assert legacy_counts(session) == before_counts
        assert_legacy_snapshot_unchanged(session, before_values)
    finally:
        session.close(); engine.dispose()
