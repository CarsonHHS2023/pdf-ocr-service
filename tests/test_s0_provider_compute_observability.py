from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from app import s0_provider_compute_observability as compute
from app.processing.s0_baseline import collect_s0_run_snapshot
from tests.test_s0_provider_source_download_observability import (
    RUN_ID, DOCUMENT_ID, PROVIDER_A, PROVIDER_B, SCOPE_A, SCOPE_B,
    _session, _seed_base, _event, _route, _terminal, _download, _metric, _aux, transport,
)


def _gpu():
    return {"measurement_scope": compute.GPU_SCOPE, "status": "observed", "sample_count": 4,
            "active_sample_count": 3, "utilization_sum_percent": 150, "sample_interval_seconds": 1.0}


def _contract(count=2):
    return {"measurement_scope": compute.DOCUMENT_SCOPE, "succeeded": True, "page_count": count,
            "batch_count": count, "raw_result_scope": compute.RAW_SCOPE, "raw_result_json_bytes": 1000,
            "batches": [{"ordinal": i, "page_start": i, "page_end": i, "predict_seconds": i * 1.25, "gpu": _gpu()} for i in range(1, count + 1)]}


def _events(scope=PROVIDER_A, contract=None):
    value = contract or _contract()
    common = {"provider_scope_id": scope, "succeeded": True, "measurement_scope": compute.DOCUMENT_SCOPE}
    rows = [SimpleNamespace(event_name=compute.BATCH_EVENT, payload={**common, **b}) for b in value["batches"]]
    rows.append(SimpleNamespace(event_name=compute.TERMINAL_EVENT, payload={**common, **{k: v for k, v in value.items() if k != "batches"}}))
    return rows


def _measure(events=None, pages=2, scopes=(PROVIDER_A,), **kwargs):
    rows = list(events if events is not None else _events())
    rows.append(SimpleNamespace(event_name="PDF_PROVIDER_TRANSPORT_SHARDING_DECISION", payload={"provider_input_page_count": pages}))
    return compute.measure_provider_compute(rows,
        download_breakdown={"downloads": [{"provider_scope_id": s} for s in scopes]},
        evidence_incomplete=kwargs.get("incomplete", False), uninspectable_event_names=kwargs.get("uninspectable", frozenset()))


def test_two_shards_and_out_of_order_events_close_independent_metrics():
    result = _measure(list(reversed(_events() + _events(PROVIDER_B))), pages=4, scopes=(PROVIDER_A, PROVIDER_B))
    assert result["status"] == result["gpu_status"] == "observed"
    assert result["ocr_seconds"] == 7.5 and result["raw_bytes"] == 2000
    assert result["gpu"]["sample_count"] == 16
    assert result["gpu"]["mean_utilization_percent"] == 37.5
    assert result["gpu"]["active_sample_fraction"] == 0.75
    assert len(result["breakdown"]["shards"]) == 2


@pytest.mark.parametrize("change", [
    lambda rows: rows.pop(),
    lambda rows: rows.pop(0),
    lambda rows: rows.append(copy.deepcopy(rows[0])),
    lambda rows: rows.append(copy.deepcopy(rows[-1])),
    lambda rows: rows[1].payload.update(ordinal=3),
    lambda rows: rows[1].payload.update(page_start=1),
    lambda rows: rows[0].payload.update(predict_seconds=float("nan")),
    lambda rows: rows[0].payload.update(predict_seconds=True),
    lambda rows: rows[0].payload.update(predict_seconds=10**400),
    lambda rows: rows[-1].payload.update(raw_result_json_bytes=0),
    lambda rows: rows[-1].payload.update(raw_result_scope="unknown"),
    lambda rows: rows[0].payload.update(provider_scope_id="unmatched"),
])
def test_incomplete_or_ambiguous_evidence_fails_closed(change):
    rows = _events(); change(rows)
    result = _measure(rows)
    assert result["status"] == "not_available"
    assert result["ocr_seconds"] is result["raw_bytes"] is result["gpu"] is None


def test_page_coverage_missing_shard_and_uninspectable_payloads_fail_closed():
    assert _measure(pages=3)["status"] == "not_available"
    assert _measure(scopes=(PROVIDER_A, PROVIDER_B))["status"] == "not_available"
    for name in (compute.BATCH_EVENT, compute.TERMINAL_EVENT, "PDF_PROVIDER_TRANSPORT_SHARDING_DECISION"):
        assert _measure(uninspectable=frozenset({name}))["status"] == "not_available"
    assert _measure(incomplete=True)["status"] == "partial"


@pytest.mark.parametrize("gpu", [None, {}, {"measurement_scope": compute.GPU_SCOPE, "status": "not_available", "reason": []},
    {**_gpu(), "sample_count": 1}, {**_gpu(), "active_sample_count": 0}, {**_gpu(), "sample_interval_seconds": True}])
def test_missing_gpu_preserves_independent_ocr_and_raw_size(gpu):
    rows = _events(); rows[0].payload["gpu"] = gpu
    result = _measure(rows)
    assert result["status"] == "observed" and result["ocr_seconds"] == 3.75
    assert result["gpu_status"] == "not_available" and result["gpu"] is None


def _request_result():
    request = SimpleNamespace(provider_job_id="synthetic-provider-job", processing_attempt_id=RUN_ID, document_id=DOCUMENT_ID)
    result = SimpleNamespace(raw_provider_payload={"documents": [{"document_id": DOCUMENT_ID, "status": "completed", "pages_completed": 2, "ocr_compute": _contract()}]})
    return request, result


@pytest.fixture
def writer_db(monkeypatch):
    from app.processing import processing_events
    db = _session(); _seed_base(db)
    monkeypatch.setattr(compute, "_enabled", lambda: True)
    monkeypatch.setattr(processing_events, "staging_processing_events_enabled", lambda: True)
    yield db
    db.close()


def _persisted_compute(db):
    from app.processing.processing_event_model import ProcessingEvent
    return db.query(ProcessingEvent).filter(ProcessingEvent.event_name.in_((compute.BATCH_EVENT, compute.TERMINAL_EVENT))).all()


def test_producer_persists_bounded_allowlist_then_terminal(writer_db):
    from sqlalchemy.orm import sessionmaker
    request, result = _request_result()
    value = result.raw_provider_payload["documents"][0]["ocr_compute"]
    value.update(filename="synthetic-private.pdf", url="https://private.invalid", token="secret")
    value["batches"][0]["gpu"]["path"] = "/private/synthetic"
    assert compute.record_provider_compute_from_result(request, result, session_factory=sessionmaker(bind=writer_db.get_bind()))
    rows = _persisted_compute(writer_db)
    assert sorted(r.event_name for r in rows) == [compute.BATCH_EVENT, compute.BATCH_EVENT, compute.TERMINAL_EVENT]
    payloads = json.dumps([json.loads(r.payload_json) for r in rows])
    assert not any(s in payloads for s in ("synthetic", "private", "filename", "url", "token", "path"))
    assert all(len(r.payload_json.encode()) < 8192 for r in rows)
    assert all(r.processing_run_id == RUN_ID and r.document_id == DOCUMENT_ID for r in rows)


@pytest.mark.parametrize("batch_count", [2, compute.MAX_BATCHES])
def test_one_transaction_preserves_all_batches_gpu_and_terminal(writer_db, batch_count):
    from sqlalchemy import event
    from sqlalchemy.orm import sessionmaker
    factory = sessionmaker(bind=writer_db.get_bind())
    commits = []
    event.listen(factory.class_, "after_commit", lambda session: commits.append(True))
    request, result = _request_result()
    result.raw_provider_payload["documents"][0].update(pages_completed=batch_count, ocr_compute=_contract(batch_count))
    assert compute.record_provider_compute_from_result(request, result, session_factory=factory)
    assert commits == [True]
    persisted = _persisted_compute(writer_db)
    assert len(persisted) == batch_count + 1
    decoded = [SimpleNamespace(event_name=e.event_name, payload=json.loads(e.payload_json)) for e in persisted]
    measured = _measure(decoded, pages=batch_count, scopes=(compute.provider_scope_id(request.provider_job_id),))
    assert measured["status"] == measured["gpu_status"] == "observed"
    assert measured["gpu"]["sample_count"] == batch_count * 4 and measured["raw_bytes"] == 1000


def test_failed_commit_rolls_back_batches_and_terminal(writer_db):
    from sqlalchemy import event
    from sqlalchemy.orm import sessionmaker
    factory = sessionmaker(bind=writer_db.get_bind())
    flushed = []
    def fail_commit(session):
        session.flush()
        flushed.append(len(_persisted_compute(session)))
        raise RuntimeError("synthetic commit failure")
    event.listen(factory.class_, "before_commit", fail_commit)
    request, result = _request_result()
    assert not compute.record_provider_compute_from_result(request, result, session_factory=factory)
    assert flushed == [3]
    assert _persisted_compute(writer_db) == []


def test_staging_gates_skip_database_and_thread_dispatch(monkeypatch):
    import asyncio
    from app.processing import processing_events
    def unexpected(*args, **kwargs):
        raise AssertionError("disabled telemetry touched the database or executor")
    request, result = _request_result()
    monkeypatch.setattr(compute, "_enabled", lambda: False)
    monkeypatch.setattr(compute.asyncio, "to_thread", unexpected)
    assert not asyncio.run(compute.record_provider_compute_from_result_async(request, result))
    assert not compute.record_provider_compute_from_result(request, result, session_factory=unexpected)
    monkeypatch.setattr(compute, "_enabled", lambda: True)
    monkeypatch.setattr(processing_events, "staging_processing_events_enabled", lambda: False)
    assert not compute.record_provider_compute_from_result(request, result, session_factory=unexpected)


@pytest.mark.parametrize("commit_fails", [False, True])
def test_retrieval_keeps_event_loop_live_during_database_commit(monkeypatch, tmp_path, commit_fails):
    import asyncio
    import threading
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker
    from app import database
    from app.models import Base
    from app.processing import processing_events
    from app.processing.models import ProviderResult, ProviderLifecycleStatus
    from app.processing.orchestration import ProcessingOrchestrator, PollingPolicy
    from app import s0_provider_source_download_observability as download
    from tests.test_processing_orchestration import FakeProvider, req, status
    engine = create_engine("sqlite:///" + str(tmp_path / "events.sqlite"))
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as seed:
        _seed_base(seed)
    factory = sessionmaker(bind=engine)
    entered, release = threading.Event(), threading.Event()
    commit_threads = []
    def blocked_commit(session):
        commit_threads.append(threading.get_ident()); entered.set()
        if not release.wait(timeout=2) or commit_fails:
            raise RuntimeError("synthetic commit failure")
    event.listen(factory.class_, "before_commit", blocked_commit)
    monkeypatch.setattr(database, "SessionLocal", factory)
    monkeypatch.setattr(compute, "_enabled", lambda: True)
    monkeypatch.setattr(download, "_enabled", lambda: False)
    monkeypatch.setattr(processing_events, "staging_processing_events_enabled", lambda: True)
    request = req(document_id=DOCUMENT_ID, processing_attempt_id=RUN_ID)
    document = {"document_id": DOCUMENT_ID, "status": "completed", "pages_completed": 2, "ocr_compute": _contract()}
    result = ProviderResult("job-1", "req-1", ProviderLifecycleStatus.PROVIDER_COMPLETED, "full", None, [document], {"documents": [document]})
    provider = FakeProvider(); provider.results = [result]
    async def exercise():
        orchestrator = ProcessingOrchestrator(provider=provider, storage=None)
        task = asyncio.create_task(orchestrator._retrieve_result(request, PollingPolicy(), orchestrator.monotonic(), 1, status(ProviderLifecycleStatus.PROVIDER_COMPLETED), 0))
        try:
            async def wait_until_blocked():
                while not entered.is_set():
                    await asyncio.sleep(0.001)
            await asyncio.wait_for(wait_until_blocked(), timeout=1)
            assert commit_threads[0] != threading.get_ident()
            await asyncio.sleep(0.01)  # Other event-loop work runs while SQL is blocked.
            assert not task.done()
        finally:
            release.set()
            outcome = await task
        assert outcome[0] is result
    try:
        asyncio.run(exercise())
        with sessionmaker(bind=engine)() as reader:
            assert len(_persisted_compute(reader)) == (0 if commit_fails else 3)
    finally:
        release.set(); engine.dispose()


def test_sampler_busy_reason_survives_collector_projection():
    rows = _events()
    rows[0].payload["gpu"] = {"measurement_scope": compute.GPU_SCOPE, "status": "not_available", "reason": "sampler_busy"}
    measured = _measure(rows)
    assert measured["status"] == "observed" and measured["gpu_status"] == "not_available"
    assert measured["breakdown"]["shards"][0]["batches"][0]["gpu"]["reason"] == "sampler_busy"


def test_overlay_rejects_legacy_hook_instead_of_recording_twice(monkeypatch, tmp_path):
    from scripts.apply_s0_provider_compute_observability import main
    path = tmp_path / "app/processing/orchestration.py"
    path.parent.mkdir(parents=True)
    path.write_text("record_provider_compute_from_result(request, result)\n")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(RuntimeError, match="Legacy synchronous"):
        main()


def test_actual_bounded_collector_maps_new_metrics_and_rejects_oversized_event():
    db = _session(); _seed_base(db)
    db.add_all([
        _event("decision", "PDF_PROVIDER_TRANSPORT_SHARDING_DECISION", {"succeeded": True, "sharding_required": True, "provider_input_size_bytes": 280, "provider_input_page_count": 4}, 2),
        _event("sharding-terminal", "PDF_PROVIDER_TRANSPORT_SHARDING_TERMINAL", {"succeeded": True, "shard_count": 2}, 3),
        _route(SCOPE_A, transport.ROUTE_PRESIGNED, 200, "route-a", 4),
        _route(SCOPE_B, transport.ROUTE_PRESIGNED, 81, "route-b", 5),
        _terminal(SCOPE_A, 0, "terminal-a", 6), _terminal(SCOPE_B, 0, "terminal-b", 7),
        _download(PROVIDER_A, 200, 2.2, "download-a", 8), _download(PROVIDER_B, 81, 2.3, "download-b", 9),
    ])
    for i, event in enumerate(_events() + _events(PROVIDER_B), 10):
        db.add(_event(f"compute-{i}", event.event_name, event.payload, i))
    db.commit()
    snapshot = collect_s0_run_snapshot(db, processing_run_id=RUN_ID)
    for key, value in (("ocr_batch_duration_seconds", 7.5), ("raw_result_shard_bytes", 2000)):
        reading = _metric(snapshot, key)
        assert reading.status == "observed" and reading.value == value
    assert _metric(snapshot, "gpu_busy_idle_proxy").status == "observed"
    assert _aux(snapshot, "provider_compute_breakdown").value["shards"][0]["batch_count"] == 2
    assert compute.BATCH_EVENT in snapshot.observed_event_names
    oversized = _event("oversized", compute.BATCH_EVENT, {"oversized": "x" * 9000}, 20)
    db.add(oversized); db.commit()
    assert _metric(collect_s0_run_snapshot(db, processing_run_id=RUN_ID), "ocr_batch_duration_seconds").status == "not_available"
    db.close()
