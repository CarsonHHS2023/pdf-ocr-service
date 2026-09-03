"""Synthetic CPU contracts and disposable SQL only; no PDF/Provider requests."""
import asyncio
from concurrent.futures import ThreadPoolExecutor, Future
import copy
import inspect
import itertools
import threading
from types import SimpleNamespace as NS

import pytest

from app import s0_preprocessing_cpu_metrics as m
from app import s0_preprocessing_cpu_observability as o

REV = "a" * 40
RUN = "pdf-ingest-" + "b" * 32
DOC = "11111111-1111-4111-8111-111111111111"
SOURCE = "22222222-2222-4222-8222-222222222222"
KW = dict(descriptor=NS(document_id=DOC, source_file_id=SOURCE),
          document_id=DOC, processing_attempt_id=RUN)


def measurement(delta=100):
    return dict(operation_outcome="completed", clock_status="measured", cpu_delta_ns=delta,
                clock_resolution_ns=1, reason="none")


def evidence(count=1):
    root = o.Root(RUN, DOC, SOURCE, REV)
    rows = [(m.START, {**root.common(), "ordinal": 0})]
    for _ in range(count):
        s = root.register()
        rows.append((m.REGISTER, {**s.common(), "ordinal": 2 * s.index - 1}))
        root.settle(s, measurement())
    root.outcome = "completed"
    root.seal()
    return root, rows + root.claim()


def measured(rows, **kwargs):
    return m.measure_preprocessing_worker_cpu([NS(event_name=n, payload=p) for n, p in rows],
        expected_source_scope=m.source_scope_id(SOURCE), run_status=kwargs.pop("status", "succeeded"), **kwargs)


@pytest.fixture
def capture(monkeypatch):
    rows = []
    mutex = threading.Lock()
    def persist(root, records):
        with mutex:
            rows.extend(copy.deepcopy(records))
        return True
    monkeypatch.setattr(o, "_revision", lambda: REV)
    monkeypatch.setattr(o, "_persist", persist)
    ticks = itertools.count(100, 100)
    monkeypatch.setattr(o, "_clock_read", lambda: (threading.get_ident(), next(ticks)))
    monkeypatch.setattr(o, "_clock_resolution", lambda: 1)
    return rows


@pytest.mark.parametrize("count", [1, 2, 8])
def test_complete_disjoint_scopes_and_zero(count):
    root, rows = evidence(count)
    assert measured(list(reversed(rows)))["value"] == count * 100 / 1e9
    for name, p in rows:
        if name == m.SCOPE_END:
            p["cpu_delta_ns"] = 0
    assert measured(rows)["value"] == 0
    assert len(rows) <= 18


@pytest.mark.parametrize("change", [
    lambda r: r.pop(0), lambda r: r.pop(1), lambda r: r.pop(),
    lambda r: r.append(copy.deepcopy(r[0])), lambda r: r.append(copy.deepcopy(r[-2])),
    lambda r: r[-1][1].update(complete=False), lambda r: r[-1][1].update(scope_count=True),
    lambda r: r[-1][1].update(scope_count=9), lambda r: r[-1][1].update(logical_outcome="failed"),
    lambda r: r[-2][1].update(cpu_delta_ns=True), lambda r: r[-2][1].update(cpu_delta_ns=-1),
    lambda r: r[-2][1].update(cpu_delta_ns=float("nan")),
    lambda r: r[-2][1].update(clock_resolution_ns=0), lambda r: r[-2][1].update(ordinal=1),
    lambda r: r[-2][1].update(backend_revision="c" * 40),
    lambda r: r[-2][1].update(source_scope_id="source_" + "d" * 64),
    lambda r: r[-2][1].update(scope_id="pcpu_" + "d" * 32),
    lambda r: r[-2][1].update(operation_outcome=[]),
    lambda r: r[-1][1].update(issue={}),
])
def test_invalid_duplicate_missing_or_mixed_evidence(change):
    _, rows = evidence()
    change(rows)
    assert measured(rows)["status"] == "not_available"


@pytest.mark.parametrize("key", ["filename", "path", "url", "token", "raw_storage_reference", "extra"])
def test_privacy_exact_fields_rejected_at_every_event(key):
    for index in range(4):
        _, rows = evidence()
        rows[index][1][key] = "synthetic-private-value"
        assert measured(rows)["status"] == "not_available"


def test_empty_failed_truncated_oversized_and_overflow_evidence():
    assert measured([])["status"] == "not_instrumented"
    assert measured(evidence(0)[1])["status"] == "not_available"
    _, rows = evidence()
    for status in ("completed", "running", "failed", "cancelled"):
        assert measured(rows, status=status)["status"] == "not_available"
    assert measured(rows, evidence_incomplete=True)["status"] == "not_available"
    for name in m.EVENT_NAMES:
        assert measured(rows, uninspectable_event_names={name})["status"] == "not_available"
    root, rows = evidence(2)
    for name, p in rows:
        if name == m.SCOPE_END:
            p["cpu_delta_ns"] = m.MAX_NS
    assert measured(rows)["status"] == "not_available"
    root.register()  # post-seal invalidation is bounded and rejects an earlier good root
    invalid = root.claim()
    assert len(invalid) == 1 and invalid[0][0] == m.INVALID
    assert measured(evidence()[1] + invalid)["status"] == "not_available"
    assert root.claim() == []


async def pipeline(worker, *, count=1):
    with ThreadPoolExecutor(max_workers=1) as pool:
        async def request(**kwargs):
            f = pool.submit(o.run_preprocessing_worker, worker, cpu_scope=o.current_preprocessing_scope())
            o.note_preprocessing_future(f)
            return await asyncio.shield(asyncio.wrap_future(f))
        for _ in range(count):
            result = await o.observe_preprocessing_request(request, **KW)
    o.note_cpu_terminal(DOC, RUN, "completed")
    return result


def test_actual_producer_success_reused_thread_context_and_outcome(capture):
    sentinel = object()
    def worker():
        assert o._ROOT.get() is None and o._REQUEST.get() is None
        return o.measure_preprocessing_delegate(lambda: sentinel)
    async def delegate(*_):
        return await pipeline(worker, count=2)
    assert asyncio.run(o.observe_pdf_processing(delegate, DOC, SOURCE, NS(processing_attempt_id=RUN))) is sentinel
    assert measured(capture)["value"] == 200 / 1e9
    assert o._ROOT.get() is o._REQUEST.get() is o._WORKER.get() is None


@pytest.mark.parametrize("where", ["delegate", "source", "submit", "capacity"])
def test_failure_or_nonentry_preserves_original_exception(capture, where):
    failure = ValueError("synthetic-private-message")
    def fail():
        raise failure
    async def delegate(*_):
        if where in ("delegate", "source"):
            worker = lambda: o.measure_preprocessing_delegate(fail) if where == "delegate" else fail()
            return await pipeline(worker)
        async def request(**_):
            if where == "submit":
                o.note_preprocessing_submit_failed()
            raise failure
        return await o.observe_preprocessing_request(request, **KW)
    with pytest.raises(ValueError) as caught:
        asyncio.run(o.observe_pdf_processing(delegate, DOC, SOURCE, NS(processing_attempt_id=RUN)))
    assert caught.value is failure
    p = next(p for n, p in capture if n == m.SCOPE_END)
    assert p["operation_outcome"] == ("failed" if where == "delegate" else "not_started")
    if where != "delegate":
        assert p["cpu_delta_ns"] is None
    assert "synthetic-private-message" not in str(capture)
    assert measured(capture)["status"] == "not_available"


def test_running_cancellation_does_not_close_before_worker_or_need_event_loop(capture):
    entered, release = threading.Event(), threading.Event()
    pool = ThreadPoolExecutor(max_workers=1)
    future = None
    def work():
        entered.set()
        assert release.wait(5)
    async def request(**_):
        nonlocal future
        future = pool.submit(o.run_preprocessing_worker,
            lambda: o.measure_preprocessing_delegate(work), cpu_scope=o.current_preprocessing_scope())
        o.note_preprocessing_future(future)
        return await asyncio.shield(asyncio.wrap_future(future))
    async def delegate(*_):
        return await o.observe_preprocessing_request(request, **KW)
    async def scenario():
        task = asyncio.create_task(o.observe_pdf_processing(delegate, DOC, SOURCE, NS(processing_attempt_id=RUN)))
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not any(n == m.END for n, _ in capture)
    try:
        asyncio.run(scenario())  # loop is now gone, worker still alive
        release.set()
        future.result(5)
    finally:
        release.set()
        pool.shutdown(wait=True)
    assert sum(n == m.END for n, _ in capture) == 1
    assert capture[-1][1]["logical_outcome"] == "cancelled"
    assert next(p for n, p in capture if n == m.SCOPE_END)["operation_outcome"] == "completed"


def test_queued_cancel_is_confirmed_nonentry(capture):
    async def request(**_):
        future = Future()
        o.note_preprocessing_future(future)
        assert future.cancel()
        return await asyncio.shield(asyncio.wrap_future(future))
    async def delegate(*_):
        return await o.observe_preprocessing_request(request, **KW)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(o.observe_pdf_processing(delegate, DOC, SOURCE, NS(processing_attempt_id=RUN)))
    p = next(p for n, p in capture if n == m.SCOPE_END)
    assert p == {**p, "reason": "cancelled_before_entry", "cpu_delta_ns": None}


@pytest.mark.parametrize("samples", [[(1, 10), (2, 20)], [(1, 20), (1, 10)], [(1, True), (1, 20)],
                                     [None, None], [(1, 2**60), (1, 2**60 + 10)]])
def test_clock_invalid_or_large_lifetime(monkeypatch, capture, samples):
    ticks = iter(samples)
    monkeypatch.setattr(o, "_clock_read", lambda: next(ticks))
    async def delegate(*_):
        return await pipeline(lambda: o.measure_preprocessing_delegate(lambda: 7))
    assert asyncio.run(o.observe_pdf_processing(delegate, DOC, SOURCE, NS(processing_attempt_id=RUN))) == 7
    assert measured(capture)["status"] == ("observed" if samples[0] == (1, 2**60) else "not_available")


def test_phase2_wall_process_measurement_precedes_cpu_publication(monkeypatch, capture):
    from app.processing import s0_phase2_stage_observability as stage
    if "measure_preprocessing_delegate" not in inspect.getsource(stage._wrap_preprocessing):
        pytest.skip("requires the Staging Phase 2 overlay")
    for fails in (False, True):
        order = []
        root = o.Root(RUN, DOC, SOURCE, REV)
        scope = root.register()
        root.outcome = "cancelled"
        root.seal()
        monkeypatch.setattr(stage, "_record", lambda **_: order.append("legacy"))
        monkeypatch.setattr(o, "_persist", lambda *_: order.append("publish") or True)
        def body(*, processing_attempt_id):
            order.append("delegate")
            if fails:
                raise ValueError("synthetic")
            return 7
        wrapped = stage._wrap_preprocessing(body)
        def outer():
            return wrapped(processing_attempt_id=RUN)
        if fails:
            with pytest.raises(ValueError):
                o.run_preprocessing_worker(outer, cpu_scope=scope)
        else:
            assert o.run_preprocessing_worker(outer, cpu_scope=scope) == 7
        assert order == ["delegate", "legacy", "publish"]


def test_overflow_and_publication_failure_do_not_change_work(monkeypatch, capture):
    calls = []
    async def delegate(*_):
        return await pipeline(lambda: o.measure_preprocessing_delegate(lambda: calls.append(1)), count=9)
    asyncio.run(o.observe_pdf_processing(delegate, DOC, SOURCE, NS(processing_attempt_id=RUN)))
    assert len(calls) == 9 and len(capture) == 18
    assert capture[-1][1]["issue"] == "scope_overflow" and not capture[-1][1]["complete"]
    capture.clear()
    monkeypatch.setattr(o, "_persist", lambda *_: False)
    asyncio.run(o.observe_pdf_processing(delegate, DOC, SOURCE, NS(processing_attempt_id=RUN)))
    assert len(calls) == 18


def test_missing_marker_is_noop(monkeypatch, tmp_path):
    from app.processing import processing_events
    marker = tmp_path / "staging-revision.txt"
    monkeypatch.setattr(processing_events, "_STAGING_REVISION_FILE", marker)
    assert o._revision() is None
    marker.write_text("invalid")
    assert o._revision() is None
    marker.write_text(REV)
    assert o._revision() == REV
    marker.unlink()
    def forbidden(*_):
        raise AssertionError("disabled observer touched persistence")
    monkeypatch.setattr(o, "_persist", forbidden)
    async def unchanged(*_):
        return 123
    assert asyncio.run(o.observe_pdf_processing(unchanged, DOC, SOURCE, NS(processing_attempt_id=RUN))) == 123


def test_setup_failure_and_final_publication_cancellation_preserve_delegate(monkeypatch, capture):
    async def success(*_):
        return 123
    with monkeypatch.context() as patch:
        def unavailable(*_):
            raise RuntimeError("synthetic observer setup error")
        patch.setattr(o, "Root", unavailable)
        assert asyncio.run(o.observe_pdf_processing(success, DOC, SOURCE, NS(processing_attempt_id=RUN))) == 123
    failure = ValueError("original synthetic failure")
    async def failed(*_):
        raise failure
    async def publication(root, rows):
        if rows and rows[-1][0] == m.END:
            raise asyncio.CancelledError()
    monkeypatch.setattr(o, "_publish_async", publication)
    with pytest.raises(ValueError) as caught:
        asyncio.run(o.observe_pdf_processing(failed, DOC, SOURCE, NS(processing_attempt_id=RUN)))
    assert caught.value is failure


def test_cancel_during_registration_does_not_dispatch(capture, monkeypatch):
    called = []
    async def publication(root, rows):
        capture.extend(copy.deepcopy(rows))
        if rows and rows[0][0] == m.REGISTER:
            root.problem("persistence_loss")
            raise asyncio.CancelledError()
    monkeypatch.setattr(o, "_publish_async", publication)
    async def request(**_):
        called.append(True)
    async def delegate(*_):
        return await o.observe_preprocessing_request(request, **KW)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(o.observe_pdf_processing(delegate, DOC, SOURCE, NS(processing_attempt_id=RUN)))
    assert not called
    assert capture[-1][1]["complete"] is False
    assert next(p for n, p in capture if n == m.SCOPE_END)["reason"] == "cancelled_before_entry"


def test_identity_mismatch_never_invents_coverage(capture):
    calls = []
    async def request(**_):
        calls.append(True)
    async def delegate(*_):
        await o.observe_preprocessing_request(request, **{**KW, "processing_attempt_id": "different"})
        o.note_cpu_terminal(DOC, RUN, "completed")
    asyncio.run(o.observe_pdf_processing(delegate, DOC, SOURCE, NS(processing_attempt_id=RUN)))
    assert calls == [True]
    assert capture[-1][1]["issue"] == "identity_mismatch"
    assert measured(capture)["status"] == "not_available"


def test_racing_seal_and_settlement_claims_exactly_once():
    root = o.Root(RUN, DOC, SOURCE, REV)
    scope = root.register()
    root.outcome = "cancelled"
    barrier = threading.Barrier(2)
    def seal():
        barrier.wait(5)
        root.seal()
        return root.claim()
    def finish():
        barrier.wait(5)
        root.settle(scope, measurement())
        return root.claim()
    with ThreadPoolExecutor(max_workers=2) as pool:
        left, right = pool.submit(seal), pool.submit(finish)
        batches = [v for v in (left.result(5), right.result(5)) if v]
    assert len(batches) == 1 and [n for n, _ in batches[0]] == [m.SCOPE_END, m.END]


@pytest.mark.parametrize("raw", ['{"ordinal":0,"ordinal":1}', '{"n":NaN}', '{"n":Infinity}', '[]', 'null', 'bad'])
def test_strict_cpu_json_decoder(raw):
    assert m.decode_worker_cpu_payload(raw) == ({}, False)


@pytest.fixture
def database(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.models import Base
    from tests.test_s0_provider_source_download_observability import _seed_base, RUN_ID, DOCUMENT_ID, SOURCE_FILE_ID
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        _seed_base(db)
    root, rows = evidence()
    root.run_id, root.document_id, root.source_id = RUN_ID, DOCUMENT_ID, SOURCE_FILE_ID
    for _, p in rows:
        p.update(root.common())
    monkeypatch.setattr(o, "_revision", lambda: REV)
    yield factory, root, rows
    engine.dispose()


def test_sql_duplicate_rollback_atomic_final_and_strict_mapping(database):
    from sqlalchemy import event
    from app.processing.processing_event_model import ProcessingEvent
    from app.processing import s0_baseline as baseline
    factory, root, rows = database
    assert o._persist(root, rows[:2], session_factory=factory)
    def fail(session):
        session.flush()
        raise RuntimeError("synthetic commit failure")
    event.listen(factory.class_, "before_commit", fail)
    try:
        assert not o._persist(root, rows[2:], session_factory=factory)
    finally:
        event.remove(factory.class_, "before_commit", fail)
    with factory() as db:
        assert db.query(ProcessingEvent).filter(ProcessingEvent.event_name.in_(m.EVENT_NAMES)).count() == 2
    assert o._persist(root, rows[2:], session_factory=factory)
    assert not o._persist(root, rows[2:], session_factory=factory)
    with factory() as db:
        saved = db.query(ProcessingEvent).filter(ProcessingEvent.event_name.in_(m.EVENT_NAMES)).all()
        assert len(saved) == 4
        assert all(len(r.payload_json.encode()) <= 8192 for r in saved)
        if hasattr(baseline, "measure_preprocessing_worker_cpu"):
            snapshot = baseline.collect_s0_run_snapshot(db, processing_run_id=root.run_id)
            required = {r.key: r for r in snapshot.required_metrics}
            auxiliary = {r.key: r for r in snapshot.auxiliary_metrics}
            assert required["preprocessing_cpu_seconds"].status == "not_instrumented"
            assert auxiliary["preprocessing_worker_thread_cpu_seconds"].status == "observed"
            assert auxiliary["preprocessing_worker_thread_cpu_seconds"].value == 100 / 1e9


def test_writer_identity_revision_privacy_and_sanitizer_equality(database, monkeypatch):
    from app.processing import processing_events
    from app.models import ProcessingRun
    factory, root, rows = database
    for field in ("run_id", "document_id", "source_id"):
        old = getattr(root, field)
        setattr(root, field, "wrong")
        # An unknown run is allowed before initialization; doc/source mismatch is not.
        if field != "run_id":
            assert not o._persist(root, rows, session_factory=factory)
        setattr(root, field, old)
    bad = copy.deepcopy(rows)
    bad[0][1]["filename"] = "synthetic-private"
    assert not o._persist(root, bad, session_factory=factory)
    with monkeypatch.context() as patch:
        patch.setattr(processing_events, "sanitize_processing_event_payload", lambda p: {})
        assert not o._persist(root, rows, session_factory=factory)
    with monkeypatch.context() as patch:
        patch.setattr(o, "_revision", lambda: "f" * 40)
        assert not o._persist(root, rows, session_factory=factory)
    with factory() as db:
        db.query(ProcessingRun).filter_by(processing_run_id=root.run_id).update({"source_file_id": None})
        db.commit()
    assert not o._persist(root, rows, session_factory=factory)


@pytest.mark.parametrize("payload", ["bad", "x" * 8193, '{"ordinal":0,"ordinal":1}'])
def test_collector_rejects_bad_durable_payload_or_truncated_window(database, payload):
    from app.processing import s0_baseline as baseline
    from app.processing.processing_event_model import ProcessingEvent
    if not hasattr(baseline, "measure_preprocessing_worker_cpu"):
        pytest.skip("requires Staging collector overlay")
    factory, root, rows = database
    assert o._persist(root, rows, session_factory=factory)
    with factory() as db:
        short = baseline.collect_s0_run_snapshot(db, processing_run_id=root.run_id, max_events=1)
        assert next(r for r in short.auxiliary_metrics if r.key == "preprocessing_worker_thread_cpu_seconds").status == "not_available"
        row = db.query(ProcessingEvent).filter_by(event_name=m.START).one()
        row.payload_json = payload
        db.commit()
        snapshot = baseline.collect_s0_run_snapshot(db, processing_run_id=root.run_id)
        assert next(r for r in snapshot.auxiliary_metrics if r.key == "preprocessing_worker_thread_cpu_seconds").status == "not_available"


def test_source_deletion_prevents_late_write(database):
    from app.models import SourceFile, ProcessingRun
    factory, root, rows = database
    with factory() as db:
        db.query(ProcessingRun).filter_by(processing_run_id=root.run_id).update({"source_file_id": None})
        db.query(SourceFile).filter_by(id=root.source_id).delete()
        db.commit()
    assert not o._persist(root, rows, session_factory=factory)
