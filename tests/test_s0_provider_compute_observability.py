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


def test_producer_persists_bounded_allowlist_then_terminal(monkeypatch):
    from app.processing import processing_events
    request, result = _request_result()
    value = result.raw_provider_payload["documents"][0]["ocr_compute"]
    value.update(filename="synthetic-private.pdf", url="https://private.invalid", token="secret")
    value["batches"][0]["gpu"]["path"] = "/private/synthetic"
    rows = []
    monkeypatch.setattr(compute, "_enabled", lambda: True)
    monkeypatch.setattr(processing_events, "record_processing_event", lambda **kw: rows.append(kw) or True)
    assert compute.record_provider_compute_from_result(request, result)
    assert [r["event_name"] for r in rows] == [compute.BATCH_EVENT, compute.BATCH_EVENT, compute.TERMINAL_EVENT]
    payloads = json.dumps([r["payload"] for r in rows])
    assert not any(s in payloads for s in ("synthetic", "private", "filename", "url", "token", "path"))
    assert all(len(json.dumps(r["payload"]).encode()) < 8192 for r in rows)
    assert all(r["processing_run_id"] == RUN_ID and r["document_id"] == DOCUMENT_ID for r in rows)


def test_producer_never_emits_terminal_after_persistence_failure(monkeypatch):
    from app.processing import processing_events
    request, result = _request_result(); rows = []
    monkeypatch.setattr(compute, "_enabled", lambda: True)
    monkeypatch.setattr(processing_events, "record_processing_event", lambda **kw: rows.append(kw) and False)
    assert not compute.record_provider_compute_from_result(request, result)
    assert len(rows) == 1 and rows[0]["event_name"] == compute.BATCH_EVENT
    monkeypatch.setattr(compute, "_enabled", lambda: False)
    assert not compute.record_provider_compute_from_result(request, result)
    assert len(rows) == 1


def test_real_durable_serializer_preserves_nested_gpu_and_scope_terminal(monkeypatch):
    from app.processing import processing_events
    from app.processing.processing_event_model import ProcessingEvent
    from sqlalchemy.orm import sessionmaker
    db = _session(); _seed_base(db)
    record = processing_events.record_processing_event
    monkeypatch.setattr(compute, "_enabled", lambda: True)
    monkeypatch.setattr(processing_events, "staging_processing_events_enabled", lambda: True)
    monkeypatch.setattr(processing_events, "record_processing_event",
                        lambda **kwargs: record(**kwargs, session_factory=sessionmaker(bind=db.get_bind())))
    request, result = _request_result()
    assert compute.record_provider_compute_from_result(request, result)
    persisted = db.query(ProcessingEvent).filter(ProcessingEvent.event_name.in_((compute.BATCH_EVENT, compute.TERMINAL_EVENT))).all()
    decoded = [SimpleNamespace(event_name=e.event_name, payload=json.loads(e.payload_json)) for e in persisted]
    measured = _measure(decoded, scopes=(compute.provider_scope_id(request.provider_job_id),))
    assert measured["status"] == measured["gpu_status"] == "observed"
    assert measured["gpu"]["sample_count"] == 8 and measured["raw_bytes"] == 1000
    db.close()


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
