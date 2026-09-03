"""Final-publication cancellation: real writer/collector, local SQLite only."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import threading
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app import s0_preprocessing_cpu_metrics as m
from app import s0_preprocessing_cpu_observability as o
from app.models import Base
from app.processing import s0_baseline
from app.processing.processing_event_model import ProcessingEvent
from tests.test_s0_preprocessing_cpu_observability import REV, evidence, measured
from tests.test_s0_provider_source_download_observability import (
    _seed_base, RUN_ID, DOCUMENT_ID, SOURCE_FILE_ID,
)


@pytest.fixture
def local_database(tmp_path, monkeypatch):
    # Separate connections, unlike StaticPool: final and invalidation transactions
    # can overlap. Never read DATABASE_URL or connect to the application's engine.
    engine = create_engine(f"sqlite:///{tmp_path / 'cpu-publication.db'}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        _seed_base(db)
    monkeypatch.setattr(o, "_revision", lambda: REV)
    yield factory
    engine.dispose()


@pytest.mark.parametrize("pause", ["before_write", "in_transaction", "after_commit", "writer_returned"])
@pytest.mark.parametrize("cancel", [False, True])
def test_final_publication_cancellation_is_durably_invalidated(local_database, monkeypatch, pause, cancel):
    _publication_scenario(local_database, monkeypatch, pause=pause, cancel=cancel)


def test_late_writer_owns_invalidation_after_loop_shutdown(local_database, monkeypatch):
    _publication_scenario(local_database, monkeypatch, pause="before_write", cancel=True,
                          reject_followup=True)


def test_cancelled_publication_preserves_original_delegate_error(local_database, monkeypatch):
    _publication_scenario(local_database, monkeypatch, pause="after_commit", cancel=True,
                          delegate_error=True)


def _publication_scenario(factory, monkeypatch, *, pause, cancel, reject_followup=False,
                          delegate_error=False):
    entered, release = threading.Event(), threading.Event()
    primary_finished, invalid_finished = threading.Event(), threading.Event()
    real_persist, real_publish = o._persist, o._publish
    roots, writes = [], []
    failure = ValueError("synthetic delegate failure")

    def stop():
        entered.set()
        assert release.wait(5), "test publisher was not released"

    def before_commit(db):
        if pause == "in_transaction" and any(
                isinstance(row, ProcessingEvent) and row.event_name == m.END for row in db.new):
            db.flush()
            stop()

    def persist(root, records):
        roots.append(root)
        final = any(n == m.END for n, _ in records)
        if final and pause == "before_write":
            stop()
        result = real_persist(root, records, session_factory=factory)
        writes.append((tuple(n for n, _ in records), result))
        if final and pause == "after_commit":
            stop()
        if any(n == m.INVALID for n, _ in records):
            invalid_finished.set()
        return result

    def publish(root, records):
        try:
            real_publish(root, records)
        finally:
            if any(n == m.END for n, _ in records):
                primary_finished.set()

    monkeypatch.setattr(o, "_persist", persist)
    monkeypatch.setattr(o, "_publish", publish)
    event.listen(factory.class_, "before_commit", before_commit)
    pool = ThreadPoolExecutor(max_workers=1)
    loop = asyncio.new_event_loop()

    async def process(*_):
        async def request(**kwargs):
            future = pool.submit(o.run_preprocessing_worker,
                lambda: o.measure_preprocessing_delegate(lambda: 123),
                cpu_scope=o.current_preprocessing_scope())
            o.note_preprocessing_future(future)
            return await asyncio.shield(asyncio.wrap_future(future))
        assert await o.observe_preprocessing_request(request,
            descriptor=NS(document_id=DOCUMENT_ID, source_file_id=SOURCE_FILE_ID),
            document_id=DOCUMENT_ID, processing_attempt_id=RUN_ID) == 123
        if delegate_error:
            raise failure
        o.note_cpu_terminal(DOCUMENT_ID, RUN_ID, "completed")
        return 123

    async def scenario():
        task = asyncio.create_task(o.observe_pdf_processing(process, DOCUMENT_ID,
            SOURCE_FILE_ID, NS(processing_attempt_id=RUN_ID)))
        if pause == "writer_returned":
            # Wait until final publication is submitted, then deliberately hold
            # the test event loop until the synchronous publisher has returned.
            # Cancellation is delivered before the completed await can resume.
            original = loop.run_in_executor
            def submitted(executor, fn, *args):
                future = original(executor, fn, *args)
                if roots and roots[-1].claimed:
                    assert primary_finished.wait(5)
                    if cancel:
                        task.cancel()
                return future
            monkeypatch.setattr(loop, "run_in_executor", submitted)
        else:
            assert await asyncio.to_thread(entered.wait, 5)
            if reject_followup:
                original = loop.run_in_executor
                def refusing(executor, fn, *args):
                    if fn is o._publish_invalidation:
                        raise RuntimeError("synthetic executor shutdown")
                    return original(executor, fn, *args)
                monkeypatch.setattr(loop, "run_in_executor", refusing)
            if cancel:
                task.cancel()
                task.cancel()  # repeated cancellation still owns only one slot
            else:
                release.set()
        if delegate_error:
            with pytest.raises(ValueError) as caught:
                await task
            assert caught.value is failure
        elif cancel:
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            assert await task == 123

    try:
        loop.run_until_complete(scenario())
    finally:
        # No loop callback is needed to publish the pending invalidation.
        loop.close()
        release.set()
        pool.shutdown(wait=True)
        assert primary_finished.wait(5)
        if cancel:
            assert invalid_finished.wait(5)
        event.remove(factory.class_, "before_commit", before_commit)

    assert all(success for _, success in writes)
    with factory() as db:
        rows = db.query(ProcessingEvent).filter(ProcessingEvent.event_name.in_(m.EVENT_NAMES)).all()
        decoded = [(row.event_name, json.loads(row.payload_json)) for row in rows]
        status = m.measure_preprocessing_worker_cpu(
            [NS(event_name=n, payload=p) for n, p in decoded],
            expected_source_scope=m.source_scope_id(SOURCE_FILE_ID), run_status="succeeded")["status"]
        expected = "not_available" if cancel or delegate_error else "observed"
        assert status == expected
        assert len(rows) == (5 if cancel else 4)
        assert len({p["ordinal"] for _, p in decoded}) == len(rows)
        invalid = [p for n, p in decoded if n == m.INVALID]
        assert [p["issue"] for p in invalid] == (["persistence_loss"] if cancel else [])
        if hasattr(s0_baseline, "measure_preprocessing_worker_cpu"):
            snapshot = s0_baseline.collect_s0_run_snapshot(db, processing_run_id=RUN_ID)
            auxiliary = {r.key: r for r in snapshot.auxiliary_metrics}
            assert auxiliary["preprocessing_worker_thread_cpu_seconds"].status == expected
            assert auxiliary["preprocessing_worker_thread_cpu_breakdown"].status == expected
            assert next(r for r in snapshot.required_metrics
                        if r.key == "preprocessing_cpu_seconds").status == "not_instrumented"


def test_invalidation_loss_is_one_attempt_not_a_recursive_retry(monkeypatch):
    root, rows = evidence()
    root.problem("persistence_loss")
    attempts = []
    monkeypatch.setattr(o, "_persist", lambda _, batch: attempts.append(batch) or False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: o._publish_invalidation(root), range(4)))
    assert len(attempts) == 1
    assert attempts[0][0][1]["issue"] == "persistence_loss"
    # A failed invalidation cannot magically change an already-committed history.
    # Do not claim guaranteed rejection when the invalidation itself is lost.
    assert measured(rows)["status"] == "observed"


@pytest.mark.parametrize("issue", ["protocol_violation", "persistence_loss"])
def test_invalidation_reasons_share_one_bounded_slot(issue):
    root, rows = evidence(count=8)
    root.problem(issue)
    root.problem("persistence_loss")
    invalid = root.claim_invalidation()
    assert len(rows + invalid) == 19
    assert invalid[0][1]["issue"] == issue
    assert m.valid_payload(*invalid[0])
    assert measured(rows + invalid)["status"] == "not_available"
    assert root.claim_invalidation() == []
