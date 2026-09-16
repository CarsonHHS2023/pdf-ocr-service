"""Composed real TXT worker + durable evidence + read-only collector regression tests."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
import json
import os
import uuid
from threading import Event
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select, update, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app import s0_txt_worker_metrics as c
from app import s0_txt_worker_observability as obs
from app import s0_txt_worker_persistence as persistence
from app.models import Base, Document, ProcessingRun, SourceFile
from app.models_v2 import StructuredContentCandidateV2Record as Candidate, StructuredContentSourceUnitV2Record as Unit
import app.models_v2_selection  # noqa: F401
from app.processing.ingestion_dispatch import DispatchClaim, DispatchPayload, run_ingestion_dispatch
from app.processing.ingestion_dispatch_model import IngestionDispatch
from app.processing.processing_event_model import ProcessingEvent
from app.processing.txt import ingestion
from app.processing.txt.structure_recovery import TxtLineStructureAssignment, TxtStructureKind, TxtStructureWindowResult
from app.storage.local import LocalStorageProvider
from app.storage.models import StorageReference

RUN = "txt-ingest-" + "1" * 32


class Analyzer:
    def analyze(self, window):
        return TxtStructureWindowResult(window.window_id, tuple(
            TxtLineStructureAssignment(line.line_id, TxtStructureKind.PARAGRAPH, True, None)
            for line in window.lines if not line.is_empty))


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("S0_TXT_TEST_POSTGRESQL_URL") else []))
def runtime(tmp_path, monkeypatch, request):
    admin = None
    if request.param == "postgresql":
        url = make_url(os.environ["S0_TXT_TEST_POSTGRESQL_URL"]).set(drivername="postgresql+psycopg")
        admin = create_engine(url)
        schema = "txt_observer_test_" + uuid.uuid4().hex
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(url.update_query_dict({"options": "-c search_path=" + schema}))
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'worker.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    raw = b"Synthetic reading fixture\nSecond paragraph\n"
    storage = LocalStorageProvider(tmp_path / "storage")
    ref = StorageReference.parse("src_" + "3" * 32)
    digest = hashlib.sha256(raw).hexdigest()
    storage.put(raw, ref, expected_size=len(raw), expected_sha256=digest)
    claim = DispatchClaim("dispatch-test", "accept-test", "doc-test", "source-test", "claim-token", 1,
                          DispatchPayload(kind="txt", txt_processing_run_ref=RUN))
    with factory.begin() as db:
        db.add(Document(id=claim.document_id, title="Synthetic", file_type="txt", status="processing"))
        db.flush()
        db.add(SourceFile(id=claim.source_file_id, document_id=claim.document_id, original_filename="synthetic.txt",
            file_type="txt", byte_size=len(raw), checksum_sha256=digest, storage_reference=str(ref), retained=1))
        db.flush()
        db.add(IngestionDispatch(id=claim.dispatch_id, acceptance_key=claim.acceptance_key,
            document_id=claim.document_id, source_file_id=claim.source_file_id, kind="txt",
            txt_processing_run_ref=RUN, status="running", claim_token=claim.claim_token, attempt_count=1,
            claim_expires_at=datetime.utcnow()+timedelta(minutes=5)))
    revision = ["a" * 40]
    monkeypatch.setattr(persistence, "revision", lambda: revision[0])
    monkeypatch.setattr(obs, "revision", lambda: revision[0])
    monkeypatch.setattr(ingestion, "SessionLocal", factory)
    monkeypatch.setattr(ingestion, "get_storage_provider", lambda: storage)
    monkeypatch.setattr(ingestion, "build_production_txt_structure_analyzer", lambda: Analyzer())
    state = SimpleNamespace(engine=engine, factory=factory, claim=claim, revision=revision,
                            ids=ingestion.TxtIngestionIds(RUN))
    try:
        yield state
    finally:
        engine.dispose()
        if admin is not None:
            with admin.begin() as conn:
                conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()


def invoke(r):
    return obs.invoke(ingestion.process_txt_document_background, r.claim.document_id, r.claim.source_file_id,
                      r.ids, claim=r.claim, session_factory=r.factory)


def admit(r):
    return obs.invoke(obs.admit, r.claim.document_id, r.claim.source_file_id,
                      r.ids, claim=r.claim, session_factory=r.factory)


def rows(r):
    with r.engine.connect() as conn:
        return conn.execute(select(ProcessingEvent.event_name, ProcessingEvent.payload_json)).all()


def succeed(r):
    with r.factory.begin() as db:
        db.execute(update(IngestionDispatch).values(status="succeeded", claim_token=None))


def test_real_worker_freezes_clock_before_document_and_dispatch_finalization(runtime, monkeypatch):
    r = runtime
    samples = iter([10_000_000_000, 12_500_000_000])
    monkeypatch.setattr(obs, "perf_counter_ns", lambda: next(samples))
    original = ingestion._set_document_terminal_state
    def terminal(*args, **kwargs):
        assert len(rows(r)) == 2
        assert persistence.collect(r.engine, RUN).status == "not_available"
        return original(*args, **kwargs)
    monkeypatch.setattr(ingestion, "_set_document_terminal_state", terminal)
    invoke(r)
    assert persistence.collect(r.engine, RUN).status == "not_available"
    succeed(r)
    reading = persistence.collect(r.engine, RUN)
    assert (reading.status, reading.value) == ("observed", 2.5)
    from app.processing.s0_baseline import collect_s0_run_snapshot
    with r.factory() as db:
        snapshot = collect_s0_run_snapshot(db, processing_run_id=RUN)
        assert not any(m.key == c.METRIC_KEY for m in snapshot.required_metrics)
        metric = next(m for m in snapshot.auxiliary_metrics if m.key == c.METRIC_KEY)
        assert (metric.status, metric.value) == ("observed", 2.5)
    # Existing lifecycle timestamps are deliberately not repurposed or backfilled.
    with r.factory() as db:
        run = db.execute(select(ProcessingRun)).scalar_one()
        assert run.started_at == run.completed_at


@pytest.mark.parametrize("reason", ["configuration", "canonical", "unexpected", "interrupted"])
def test_worker_failures_never_create_fake_run_or_zero_success(runtime, monkeypatch, reason):
    error = {"configuration": ingestion.TxtIngestionConfigurationError("synthetic"),
             "canonical": ingestion.TxtCanonicalizationError("synthetic"),
             "unexpected": RuntimeError("synthetic"), "interrupted": KeyboardInterrupt()}[reason]
    def fail():
        raise error
    monkeypatch.setattr(ingestion, "build_production_txt_structure_analyzer", fail)
    if reason == "interrupted":
        with pytest.raises(KeyboardInterrupt):
            invoke(runtime)
    else:
        invoke(runtime)
    events = rows(runtime)
    assert len(events) == 2
    terminal = json.loads(events[1].payload_json)
    assert terminal["outcome"] == "failed" and terminal["duration_ns"] is None
    with runtime.factory() as db:
        assert db.execute(select(ProcessingRun)).first() is None
    assert persistence.collect(runtime.engine, RUN).status == "not_available"


@pytest.mark.parametrize("clock", [iter([9, 8]), iter([True, 10]), iter([0, c.MAX_NS + 1]), iter([])])
def test_clock_failure_preserves_success_but_withholds_duration(runtime, monkeypatch, clock):
    monkeypatch.setattr(obs, "perf_counter_ns", lambda: next(clock))
    invoke(runtime)
    succeed(runtime)
    assert persistence.collect(runtime.engine, RUN).status == "not_available"
    assert json.loads(rows(runtime)[1].payload_json)["outcome"] == "invalid"
    with runtime.factory() as db:
        assert db.get(Document, "doc-test").status == "completed"


def test_duplicate_workers_are_serialized_and_permanently_invalidated(runtime):
    with ThreadPoolExecutor(max_workers=2) as pool:
        observations = list(pool.map(lambda _: admit(runtime), range(2)))
    assert sum(item is not None for item in observations) == 1
    winner = next(item for item in observations if item)
    winner.start()
    winner.finish(reason="unexpected_error")
    for _ in range(4):
        assert admit(runtime) is None
    assert {row.event_name for row in rows(runtime)} == {c.START, c.INVALIDATED}


def test_publication_retry_is_idempotent_conflicting_terminal_invalidates(runtime):
    observation = admit(runtime)
    payload = dict(observation.common, ordinal=0)
    assert persistence.publish(runtime.engine, runtime.claim, c.START, payload)
    terminal = dict(observation.common, ordinal=1, outcome="failed", duration_ns=None,
                    candidate_scope_id=None, reason="unexpected_error")
    assert persistence.publish(runtime.engine, runtime.claim, c.TERMINAL, terminal)
    assert persistence.publish(runtime.engine, runtime.claim, c.TERMINAL, terminal)
    terminal["reason"] = "canonicalization_error"
    assert not persistence.publish(runtime.engine, runtime.claim, c.TERMINAL, terminal)
    assert len(rows(runtime)) == 3


def test_stale_claim_gate_and_observer_database_lock_fail_open(runtime):
    runtime.claim = replace(runtime.claim, claim_token="stale")
    invoke(runtime)
    assert not rows(runtime)
    with runtime.factory() as db:
        assert db.get(Document, "doc-test").status == "completed"


def test_observer_lock_contention_is_bounded(runtime):
    if runtime.engine.dialect.name != "sqlite":
        pytest.skip("SQLite-specific lock syntax")
    with runtime.engine.connect() as conn:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        assert admit(runtime) is None
        conn.rollback()
    assert not rows(runtime)


def test_terminal_write_failure_keeps_processing_success(runtime, monkeypatch):
    original = obs.publish
    monkeypatch.setattr(obs, "publish", lambda engine, claim, name, payload:
                        False if name == c.TERMINAL else original(engine, claim, name, payload))
    invoke(runtime)
    succeed(runtime)
    assert len(rows(runtime)) == 1
    assert persistence.collect(runtime.engine, RUN).status == "not_available"
    with runtime.factory() as db:
        assert db.get(Document, "doc-test").status == "completed"


@pytest.mark.parametrize("mutation", ["source", "candidate", "dispatch", "revision", "oversized", "foreign_doc", "extra_event", "running"])
def test_collector_rejects_inconsistent_or_ambiguous_evidence(runtime, mutation):
    invoke(runtime)
    succeed(runtime)
    assert persistence.collect(runtime.engine, RUN).status == "observed"
    with runtime.factory.begin() as db:
        if mutation == "source":
            db.execute(update(SourceFile).values(retained=0))
        elif mutation == "candidate":
            db.execute(update(Unit).values(source_ref="foreign-source"))
        elif mutation == "dispatch":
            db.add(IngestionDispatch(id="duplicate", acceptance_key="duplicate", document_id="doc-test",
                source_file_id="source-test", kind="txt", txt_processing_run_ref=RUN, status="succeeded"))
        elif mutation == "revision":
            runtime.revision[0] = "b" * 40
        elif mutation == "oversized":
            db.execute(update(ProcessingEvent).values(payload_json="中" * c.MAX_BYTES))
        elif mutation == "foreign_doc":
            db.add(Document(id="foreign", title="Synthetic", file_type="txt", status="completed"))
            db.flush()
            db.execute(update(ProcessingEvent).values(document_id="foreign"))
        elif mutation == "extra_event":
            db.add(ProcessingEvent(processing_run_id=RUN, document_id="doc-test", schema_version=c.SCHEMA,
                event_name=c.PREFIX+"UNKNOWN", payload_json="{}"))
        elif mutation == "running":
            db.execute(update(IngestionDispatch).values(status="running"))
    assert persistence.collect(runtime.engine, RUN).status == "not_available"


def test_revision_change_during_worker_invalidates(runtime, monkeypatch):
    original = ingestion.TxtCanonicalizationService.canonicalize
    def canonicalize(self, request):
        result = original(self, request)
        runtime.revision[0] = "b" * 40
        return result
    monkeypatch.setattr(ingestion.TxtCanonicalizationService, "canonicalize", canonicalize)
    invoke(runtime)
    assert {row.event_name for row in rows(runtime)} == {c.START, c.INVALIDATED}


def test_cancelled_dispatch_waiter_does_not_stop_actual_worker(runtime, monkeypatch):
    entered, release, finished = Event(), Event(), Event()
    class BlockingAnalyzer(Analyzer):
        def analyze(self, window):
            entered.set()
            assert release.wait(5)
            return super().analyze(window)
    monkeypatch.setattr(ingestion, "build_production_txt_structure_analyzer", lambda: BlockingAnalyzer())
    with runtime.factory.begin() as db:
        db.execute(update(IngestionDispatch).values(status="queued", claim_token=None, attempt_count=0))
    def processor(*args):
        try:
            return ingestion.process_txt_document_background(*args)
        finally:
            finished.set()
    async def scenario():
        task = asyncio.create_task(run_ingestion_dispatch("dispatch-test", session_factory=runtime.factory,
                                                         txt_processor=processor))
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(rows(runtime)) == 1
        release.set()
        assert await asyncio.to_thread(finished.wait, 5)
    try:
        asyncio.run(scenario())
    finally:
        release.set()
    assert len(rows(runtime)) == 2
    with runtime.factory() as db:
        assert db.get(Document, "doc-test").status == "completed"
        assert db.get(IngestionDispatch, "dispatch-test").status == "running"
    assert persistence.collect(runtime.engine, RUN).status == "not_available"


def test_uninstrumented_direct_call_and_missing_revision_do_not_emit(runtime):
    ingestion.process_txt_document_background("doc-test", "source-test", runtime.ids)
    assert not rows(runtime)
    runtime.revision[0] = None
    invoke(runtime)
    assert not rows(runtime)


def test_read_projection_is_read_only_and_does_not_commit_caller(runtime):
    from sqlalchemy.exc import DBAPIError
    with persistence.observer_connection(runtime.engine) as conn:
        with pytest.raises(DBAPIError):
            conn.execute(update(Document).values(status="failed"))
    with runtime.factory() as db:
        doc = db.get(Document, "doc-test")
        doc.title = "Uncommitted synthetic change"
        persistence.collect(runtime.engine, RUN)
        assert db.dirty
        db.rollback()
    with runtime.factory() as db:
        assert db.get(Document, "doc-test").title == "Synthetic"


def test_postgresql_projection_uses_repeatable_read(runtime):
    if runtime.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL MVCC regression")
    with persistence.observer_connection(runtime.engine) as conn:
        assert conn.exec_driver_sql("SHOW transaction_isolation").scalar_one() == "repeatable read"
        assert conn.exec_driver_sql("SHOW transaction_read_only").scalar_one() == "on"
        assert conn.execute(select(IngestionDispatch.status)).scalar_one() == "running"
        with runtime.factory.begin() as db:
            db.execute(update(IngestionDispatch).values(status="failed"))
        assert conn.execute(select(IngestionDispatch.status)).scalar_one() == "running"
    with runtime.engine.connect() as conn:
        assert conn.execute(select(IngestionDispatch.status)).scalar_one() == "failed"


def test_real_dispatch_success_admits_after_durable_finalization(runtime):
    with runtime.factory.begin() as db:
        db.execute(update(IngestionDispatch).values(status="queued", claim_token=None, attempt_count=0))
    assert asyncio.run(run_ingestion_dispatch("dispatch-test", session_factory=runtime.factory,
                                              txt_processor=ingestion.process_txt_document_background))
    assert persistence.collect(runtime.engine, RUN).status == "observed"
    assert not asyncio.run(run_ingestion_dispatch("dispatch-test", session_factory=runtime.factory,
                                                  txt_processor=ingestion.process_txt_document_background))
    assert len(rows(runtime)) == 2


def test_candidate_outcome_mismatch_withholds_duration(runtime, monkeypatch):
    original = ingestion.TxtCanonicalizationService.canonicalize
    def wrong(self, request):
        return replace(original(self, request), source_file_ref="foreign-source")
    monkeypatch.setattr(ingestion.TxtCanonicalizationService, "canonicalize", wrong)
    invoke(runtime)
    succeed(runtime)
    assert persistence.collect(runtime.engine, RUN).status == "not_available"
    assert json.loads(rows(runtime)[1].payload_json)["reason"] == "candidate_mismatch"


def test_terminal_evidence_absent_after_canonical_commit_failure(runtime, monkeypatch):
    original = ingestion.TxtCanonicalizationService.canonicalize
    # A real worker exception propagates through the existing failure boundary.
    # Failure evidence cannot turn a durable run/candidate into measured success.
    def failed(self, request):
        original(self, request)
        raise ingestion.TxtCanonicalizationError("synthetic post-commit failure")
    monkeypatch.setattr(ingestion.TxtCanonicalizationService, "canonicalize", failed)
    invoke(runtime)
    succeed(runtime)
    assert persistence.collect(runtime.engine, RUN).status == "not_available"
    assert json.loads(rows(runtime)[1].payload_json)["outcome"] == "failed"
