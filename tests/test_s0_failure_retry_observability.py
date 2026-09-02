"""Synthetic-only S0.3.6 contracts; never contact a Provider or real database."""
import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from app import s0_failure_retry_observability as obs
from app import s0_failure_retry_metrics as metrics
from app.processing.orchestration import ProcessingOrchestrator, PollingPolicy, OrchestrationError
from app.processing.errors import ProviderClientError, ProviderErrorCategory as Category, ProviderErrorDetail
from app.processing.models import ProviderLifecycleStatus as State
from app.storage.local import LocalStorageProvider
from tests.test_processing_orchestration import FakeProvider, RecordingClock, req, status, inline_result

REVISION = "a" * 40
SOURCE = "sf-1"
COMPOSED = hasattr(ProcessingOrchestrator, "_run_once_without_s036")


def _scope(ordinal=1):
    return {"ordinal": ordinal, "provider_scope_id": obs.provider_scope_id(f"synthetic-job-{ordinal}"),
            "outcome": "completed", "provider_terminal_status": "provider_completed",
            "operations": {op: dict.fromkeys(metrics.COUNTERS, 0) for op in metrics.OPERATIONS}}


def _run(count=1):
    run = obs.Run("attempt-1", "doc-1", SOURCE, REVISION)
    run.scopes = [_scope(i) for i in range(1, count + 1)]
    for scope in run.scopes:
        for op in ("submit", "status", "result"):
            scope["operations"][op].update(attempts=1, succeeded=1)
    run.outcome = "completed"
    return run


def _events(run=None):
    run = run or _run()
    return [NS(event_name=n, payload=p) for n, p in [(metrics.START_EVENT, run.common()), *run.closed_events()]]


def _measure(events, **kwargs):
    return metrics.measure_failure_retry(events, source_scope_id=obs.source_scope_id(SOURCE),
        evidence_incomplete=kwargs.get("incomplete", False), uninspectable_event_names=kwargs.get("bad", frozenset()))


@pytest.mark.parametrize("count", [0, 1, 2, metrics.MAX_SCOPES])
def test_complete_manifest_including_explicit_zero_and_multiple_shards(count):
    value = _measure(list(reversed(_events(_run(count)))))
    assert value["status"] == "observed"
    assert value["value"]["backend_provider_calls"]["attempts"] == 3 * count
    assert value["value"]["backend_provider_calls"]["failed"] == value["value"]["backend_provider_calls"]["retries"] == 0
    assert value["value"]["orchestration_invocations"]["completed"] == count


@pytest.mark.parametrize("change", [
    lambda rows: rows.pop(0), lambda rows: rows.pop(), lambda rows: rows.pop(1),
    lambda rows: rows.append(copy.deepcopy(rows[0])), lambda rows: rows.append(copy.deepcopy(rows[1])),
    lambda rows: rows.append(copy.deepcopy(rows[-1])),
    lambda rows: rows[-1].payload.update(scope_count=2),
    lambda rows: rows[-1].payload.update(complete=False),
    lambda rows: rows[-1].payload.update(scope_count=True),
    lambda rows: rows[-1].payload.update(scope_count=metrics.MAX_SCOPES + 1),
    lambda rows: rows[-1].payload.update(outcome="unknown"),
    lambda rows: rows[1].payload.update(ordinal=2),
    lambda rows: rows[1].payload.update(ordinal=True),
    lambda rows: rows[1].payload.update(backend_revision="b" * 40),
    lambda rows: rows[1].payload.update(provider_scope_id="synthetic-raw-job"),
    lambda rows: rows[1].payload.update(source_scope_id=obs.source_scope_id("wrong-source")),
    lambda rows: rows[1].payload["operations"]["submit"].update(attempts=-1),
    lambda rows: rows[1].payload["operations"]["submit"].update(attempts=True),
    lambda rows: rows[1].payload["operations"]["status"].update(failed=float("nan")),
    lambda rows: rows[1].payload["operations"]["result"].update(retries=1),
    lambda rows: rows[1].payload["operations"]["submit"].update(not_ready=1, succeeded=0),
])
def test_missing_duplicate_invalid_or_incomplete_evidence_fails_closed(change):
    rows = _events(); change(rows)
    assert _measure(rows)["status"] == "not_available"


@pytest.mark.parametrize("key", ["filename", "path", "url", "token", "storage_reference", "raw_payload"])
def test_unexpected_fields_rejected_at_every_nested_level(key):
    for target in (0, 1, 2, "operations", "counts"):
        rows = _events()
        field = rows[target].payload if isinstance(target, int) else rows[1].payload["operations"]
        if target == "counts":
            field = field["result"]
        field[key] = "synthetic-private-value"
        assert _measure(rows)["status"] == "not_available"


def test_entire_missing_shard_duplicate_provider_and_mixed_run_are_unavailable():
    rows = _events(_run(2)); rows.pop(2)
    assert _measure(rows)["status"] == "not_available"
    rows = _events(_run(2)); rows[2].payload["provider_scope_id"] = rows[1].payload["provider_scope_id"]
    assert _measure(rows)["status"] == "not_available"
    assert _measure(_events() + _events())["status"] == "not_available"
    assert _measure([])["status"] == "not_available"
    assert _measure(_events(), incomplete=True)["status"] == "partial"
    for name in metrics.EVENT_NAMES:
        assert _measure(_events(), bad={name})["status"] == "not_available"


def _error(category=Category.UNAVAILABLE, retryable=True):
    return ProviderClientError(ProviderErrorDetail(category, "synthetic-private-error", retryable=retryable))


@pytest.fixture
def capture(monkeypatch):
    rows = []
    monkeypatch.setattr(obs, "_revision", lambda: REVISION)
    async def publish(run, events):
        rows.extend(NS(event_name=n, payload=copy.deepcopy(p)) for n, p in events)
        return True
    monkeypatch.setattr(obs, "_publish", publish)
    return rows


async def _execute(provider, tmp_path, *, clock=None, policy=None):
    clock = clock or RecordingClock()
    orchestrator = ProcessingOrchestrator(provider=provider, storage=LocalStorageProvider(tmp_path), sleep=clock.sleep, monotonic=clock)
    async def delegate(document, source, ids):
        result = await orchestrator.run_once(req(), policy)
        obs.note_pdf_terminal(document, "completed" if result.succeeded else "failed")
        return result
    return await obs.observe_pdf_processing(delegate, "doc-1", SOURCE, NS(processing_attempt_id="attempt-1"))


@pytest.mark.skipif(not COMPOSED, reason="Requires tested Staging overlay")
@pytest.mark.parametrize("phase", ["status", "result"])
def test_actual_retry_success_and_result_not_ready_are_distinct(capture, tmp_path, phase):
    provider = FakeProvider()
    provider.statuses = [status(State.QUEUED), status(State.RUNNING), status(State.PROVIDER_COMPLETED)]
    provider.results = [inline_result()]
    if phase == "status":
        provider.statuses.insert(0, _error())
    else:
        provider.results = [_error(), _error(Category.RESULT_NOT_READY), inline_result()]
    result = asyncio.run(_execute(provider, tmp_path))
    assert result.succeeded and len(provider.submitted) == 1
    measured = _measure(capture)
    assert measured["status"] == "observed"
    counts = measured["value"]["backend_provider_calls"]
    assert counts["failed"] == counts["retryable_failures"] == counts["retries"] == 1
    assert counts["not_ready"] == (1 if phase == "result" else 0)
    assert counts["succeeded"] == 5
    assert obs._ROOT.get() is obs._SCOPE.get() is None


@pytest.mark.skipif(not COMPOSED, reason="Requires tested Staging overlay")
@pytest.mark.parametrize("boundary", ["cancel", "deadline", "request_limit", "nonretryable", "uncertain_submit"])
def test_failure_without_actual_dispatch_never_counts_a_retry(capture, tmp_path, boundary):
    provider = FakeProvider(); clock = RecordingClock()
    provider.statuses = [_error(retryable=boundary != "nonretryable"), status(State.PROVIDER_COMPLETED)]
    provider.results = [inline_result()]
    policy = PollingPolicy(timeout_seconds=1) if boundary == "deadline" else PollingPolicy(max_status_requests=1) if boundary == "request_limit" else None
    if boundary == "cancel":
        async def cancel(seconds):
            raise asyncio.CancelledError()
        clock.sleep = cancel
    if boundary == "uncertain_submit":
        provider.submission = _error(Category.TIMEOUT)
    with pytest.raises(asyncio.CancelledError if boundary == "cancel" else OrchestrationError):
        asyncio.run(_execute(provider, tmp_path, clock=clock, policy=policy))
    value = _measure(capture)
    assert value["status"] == "observed"
    assert value["value"]["backend_provider_calls"]["failed"] == 1
    assert value["value"]["backend_provider_calls"]["retries"] == 0
    assert value["value"]["logical_pdf_invocation"]["outcome"] == ("cancelled" if boundary == "cancel" else "failed")
    assert len(provider.submitted) == 1


@pytest.mark.skipif(not COMPOSED, reason="Requires tested Staging overlay")
def test_provider_job_failure_is_not_a_failed_rpc(capture, tmp_path):
    provider = FakeProvider(); provider.statuses = [status(State.FAILED)]
    assert not asyncio.run(_execute(provider, tmp_path)).succeeded
    value = _measure(capture)["value"]
    assert value["backend_provider_calls"]["failed"] == 0
    assert value["provider_terminal_observations"]["failed"] == 1
    assert value["orchestration_invocations"]["failed"] == 1
    assert value["logical_pdf_invocation"]["outcome"] == "failed"


@pytest.mark.skipif(not COMPOSED, reason="Requires tested Staging overlay")
def test_retry_limit_and_cancellation_of_dispatched_retry(capture, tmp_path):
    provider = FakeProvider(); provider.statuses = [_error()] * 4
    with pytest.raises(OrchestrationError):
        asyncio.run(_execute(provider, tmp_path))
    counts = _measure(capture)["value"]["backend_provider_calls"]
    assert (counts["failed"], counts["retries"]) == (4, 3)
    capture.clear()
    calls = []
    async def status_call(job):
        calls.append(job)
        if len(calls) == 1:
            raise _error()
        raise asyncio.CancelledError()
    provider = FakeProvider(); provider.get_job_status = status_call
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_execute(provider, tmp_path))
    counts = _measure(capture)["value"]["backend_provider_calls"]
    assert (counts["failed"], counts["retries"], counts["cancelled"]) == (1, 1, 1)


def test_root_missing_terminal_disabled_gate_and_failed_start(monkeypatch, capture):
    calls = []
    async def delegate(*args):
        calls.append(True)
        return "unchanged"
    args = (delegate, "doc-1", SOURCE, NS(processing_attempt_id="attempt-1"))
    assert asyncio.run(obs.observe_pdf_processing(*args)) == "unchanged"
    assert _measure(capture)["status"] == "not_available"
    capture.clear()
    monkeypatch.setattr(obs, "_revision", lambda: None)
    assert asyncio.run(obs.observe_pdf_processing(*args)) == "unchanged" and not capture
    monkeypatch.setattr(obs, "_revision", lambda: REVISION)
    async def failed(*args):
        calls.append("failed-start")
        return False
    monkeypatch.setattr(obs, "_publish", failed)
    assert asyncio.run(obs.observe_pdf_processing(*args)) == "unchanged"
    assert calls.count("failed-start") == 1


def test_concurrent_shard_contexts_are_independent(capture):
    async def scenario(document, source, ids):
        async def job(request, policy):
            tries = 0
            async def provider(job_id):
                nonlocal tries
                tries += 1
                await asyncio.sleep(0)
                if tries == 1:
                    raise _error()
                return NS(job_id=job_id, status=State.PROVIDER_COMPLETED)
            for _ in range(2):
                try:
                    await obs.observe_provider_call("status", provider, request.provider_job_id)
                except ProviderClientError:
                    continue
            return NS(succeeded=True)
        await asyncio.gather(*(obs.observe_orchestration(job, req(provider_job_id=f"shard-{i}"), None) for i in range(3)))
        obs.note_pdf_terminal(document, "completed")
    asyncio.run(obs.observe_pdf_processing(scenario, "doc-1", SOURCE, NS(processing_attempt_id="attempt-1")))
    measured = _measure(capture)
    assert measured["status"] == "observed"
    assert len(measured["breakdown"]["scopes"]) == 3
    assert measured["value"]["backend_provider_calls"]["failed"] == measured["value"]["backend_provider_calls"]["retries"] == 3
    assert all(s["operations"]["status"]["retries"] == 1 for s in measured["breakdown"]["scopes"])


@pytest.mark.parametrize("cause", ["scope_limit", "association_mismatch"])
def test_incomplete_scope_tracking_never_blocks_work_or_reports_zero(capture, monkeypatch, cause):
    if cause == "scope_limit":
        monkeypatch.setattr(obs, "MAX_SCOPES", 1)
    calls = []
    async def scenario(document, source, ids):
        async def job(request, policy):
            calls.append(request.provider_job_id)
            return NS(succeeded=True)
        for i in range(2):
            request = req(provider_job_id=f"job-{i}", source_file_id="wrong" if cause == "association_mismatch" else SOURCE)
            await obs.observe_orchestration(job, request, None)
        obs.note_pdf_terminal(document, "completed")
    asyncio.run(obs.observe_pdf_processing(scenario, "doc-1", SOURCE, NS(processing_attempt_id="attempt-1")))
    assert len(calls) == 2 and _measure(capture)["status"] == "not_available"


@pytest.mark.skipif(not COMPOSED, reason="Requires tested Staging overlay")
def test_observability_does_not_change_calls_sleep_policy_or_outcome(capture, tmp_path):
    def setup():
        provider = FakeProvider()
        provider.statuses = [_error(), status(State.RUNNING), status(State.PROVIDER_COMPLETED)]
        provider.results = [_error(Category.RESULT_NOT_READY), _error(Category.TIMEOUT), inline_result()]
        return provider, RecordingClock()
    first, clock = setup()
    observed = asyncio.run(_execute(first, tmp_path / "observed", clock=clock))
    second, reference_clock = setup()
    reference = asyncio.run(ProcessingOrchestrator(provider=second, storage=LocalStorageProvider(tmp_path / "reference"),
        sleep=reference_clock.sleep, monotonic=reference_clock).run_once(req()))
    assert clock.sleeps == reference_clock.sleeps
    assert (observed.succeeded, observed.final_phase, observed.poll_count) == (reference.succeeded, reference.final_phase, reference.poll_count)
    assert len(first.submitted) == len(second.submitted) == 1
    assert first.statuses == second.statuses == first.results == second.results == []


def test_real_staging_gate_and_wrapper_installation(monkeypatch, tmp_path):
    from app import processing, s0_object_store_io_observability as io
    from app.processing import processing_events
    revision = tmp_path / "staging-revision.txt"
    monkeypatch.setattr(io, "_STAGING_REVISION_FILE", revision)
    monkeypatch.setattr(processing_events, "_STAGING_REVISION_FILE", revision)
    assert obs._revision() is None
    revision.write_text("malformed")
    assert obs._revision() is None
    revision.write_text(REVISION)
    assert obs._revision() == REVISION
    calls = []
    async def delegate(*args):
        calls.append(args)
        return "unchanged"
    fake = NS(process_pdf_document_background=delegate)
    monkeypatch.setattr(processing, "pdf_ingestion", fake, raising=False)
    obs.install_pdf_observability(); first = fake.process_pdf_document_background
    obs.install_pdf_observability()
    assert first is fake.process_pdf_document_background
    revision.unlink()
    def no_io(*args):
        raise AssertionError("Production gate touched persistence")
    monkeypatch.setattr(obs, "_publish", no_io)
    assert asyncio.run(first("doc", "source", NS(processing_attempt_id="run"))) == "unchanged"
    assert len(calls) == 1
    invalid = _run(); invalid.revision = None
    assert not obs._persist(invalid, [], session_factory=no_io)


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
    with factory() as session:
        _seed_base(session)
    monkeypatch.setattr(obs, "_revision", lambda: REVISION)
    run = _run(2); run.run_id, run.document_id, run.source_id = RUN_ID, DOCUMENT_ID, SOURCE_FILE_ID
    yield factory, run
    engine.dispose()


def test_atomic_persistence_privacy_and_real_collector(database):
    from app.processing.s0_baseline import collect_s0_run_snapshot
    from app.processing.processing_event_model import ProcessingEvent
    factory, run = database
    events = [(e.event_name, e.payload) for e in _events(run)]
    assert obs._persist(run, events, session_factory=factory)
    with factory() as session:
        rows = session.query(ProcessingEvent).filter(ProcessingEvent.event_name.in_(metrics.EVENT_NAMES)).all()
        assert len(rows) == 4
        assert all(len(r.payload_json.encode()) < 8192 for r in rows)
        payloads = " ".join(r.payload_json for r in rows)
        assert not any(v in payloads for v in ("synthetic-job", "private", "http", "filename", "token", "storage_reference"))
        if COMPOSED:
            snapshot = collect_s0_run_snapshot(session, processing_run_id=run.run_id)
            metric = next(m for m in snapshot.required_metrics if m.key == "failure_retry_counts")
            assert metric.status == "observed" and metric.value["backend_provider_calls"]["retries"] == 0


def test_rollback_association_and_sanitization_loss_fail_open(database):
    from sqlalchemy import event
    from app.models import ProcessingRun
    from app.processing.processing_event_model import ProcessingEvent
    factory, run = database
    start = [(metrics.START_EVENT, run.common())]
    wrong = copy.deepcopy(run); wrong.document_id = "wrong-document"
    assert not obs._persist(wrong, start, session_factory=factory)
    wrong = copy.deepcopy(run); wrong.source_id = "wrong-source"
    assert not obs._persist(wrong, start, session_factory=factory)
    invalid = [(metrics.START_EVENT, {**run.common(), "token": "never-persist"})]
    assert not obs._persist(run, invalid, session_factory=factory)
    assert obs._persist(run, start, session_factory=factory)
    def fail_commit(session):
        session.flush()
        raise RuntimeError("synthetic commit failure")
    event.listen(factory.class_, "before_commit", fail_commit)
    try:
        assert not obs._persist(run, run.closed_events(), session_factory=factory)
    finally:
        event.remove(factory.class_, "before_commit", fail_commit)
    with factory() as session:
        rows = session.query(ProcessingEvent).filter(ProcessingEvent.event_name.in_(metrics.EVENT_NAMES)).all()
        assert len(rows) == 1 and rows[0].event_name == metrics.START_EVENT
        session.query(ProcessingRun).filter(ProcessingRun.processing_run_id == run.run_id).update({"source_file_id": None})
        session.commit()
    assert not obs._persist(run, run.closed_events(), session_factory=factory)


def test_thread_owned_persistence_keeps_event_loop_live(database, monkeypatch):
    import threading
    from app import database as db_module
    factory, run = database
    entered, release = threading.Event(), threading.Event()
    original = obs._persist
    threads = []
    def persist(*args):
        threads.append(threading.get_ident()); entered.set()
        assert release.wait(5)
        return original(*args)
    monkeypatch.setattr(obs, "_persist", persist)
    monkeypatch.setattr(db_module, "SessionLocal", factory)
    async def scenario():
        task = asyncio.create_task(obs._publish(run, [(metrics.START_EVENT, run.common())]))
        for _ in range(1000):
            if entered.is_set():
                break
            await asyncio.sleep(.001)
        assert entered.is_set() and threads != [threading.get_ident()]
        release.set()
        assert await task
    asyncio.run(scenario())


@pytest.mark.skipif(not COMPOSED, reason="Requires tested Staging overlay")
def test_overlay_idempotent_and_fails_on_partial_install(tmp_path, monkeypatch):
    import shutil
    from scripts.apply_s0_failure_retry_observability import main
    root = Path(__file__).resolve().parents[1]
    paths = ("app/processing/orchestration.py", "app/processing/pdf_ingestion.py", "app/processing/s0_baseline.py")
    for name in paths:
        target = tmp_path / name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(root / name, target)
    monkeypatch.chdir(tmp_path)
    before = {name: Path(name).read_bytes() for name in paths}
    main(); main()
    assert before == {name: Path(name).read_bytes() for name in paths}
    path = Path(paths[0])
    path.write_text(path.read_text().replace('await observe_provider_call("status", self.provider.get_job_status, ', 'await self.provider.get_job_status('))
    with pytest.raises(RuntimeError, match="partially installed"):
        main()
