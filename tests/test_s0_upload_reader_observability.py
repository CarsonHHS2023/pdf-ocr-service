from __future__ import annotations

import asyncio
import copy
import json
import os
from types import SimpleNamespace as NS

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import s0_upload_reader_metrics as c
from app import s0_upload_reader_persistence as p
from app import s0_upload_reader_observability as http
from app.models_v2 import StructuredContentCandidateV2Record as Candidate
from app.processing.ingestion_dispatch_model import IngestionDispatch
from app.processing.processing_event_model import ProcessingEvent
from tests.test_s0_baseline import _seed_run, _session
from tests.test_s0_reader_open_observability import evidence

ROOT = "upr_" + "1" * 32
SHA = "a" * 40
FRONT = "b" * 40


def request():
    return dict(protocol_version=c.VERSION, measurement_scope=c.SCOPE, measurement_method=c.METHOD,
        upload_scope_id=ROOT, open_scope_id="reader_" + "1" * 32, candidate_id="candidate-test",
        frontend_revision=FRONT, backend_revision=SHA, duration_seconds=120.25)


def seed(db):
    run = _seed_run(db, with_events=False)
    db.add(IngestionDispatch(id="dispatch-test", acceptance_key="test-acceptance", document_id="doc-s0",
        source_file_id="source-s0", kind="pdf", processing_attempt_id=run,
        provider_job_id="job-test", provider_request_id="request-test"))
    db.add(Candidate(candidate_id="candidate-test", document_id="doc-s0", lineage_key="test-lineage",
        schema_id="atlas.structured-content.v2", schema_version=2, processing_run_ref=run, recovery_state="complete"))
    db.commit()
    return run


def rows():
    common = c.common(ROOT, "source-s0", FRONT, SHA)
    result = [NS(event_name=c.ACCEPTED, payload={**common, "ordinal": 0, "succeeded": True, "upload_route": "POST /api/v1/upload"}),
        NS(event_name=c.TERMINAL, payload={**common, "ordinal": 1, "succeeded": True, "open_scope_id": request()["open_scope_id"],
            "candidate_scope_id": c.candidate_scope_id("candidate-test"), "duration_seconds": 120.25})]
    reader = evidence()
    for e in reader:
        e.payload["candidate_scope_id"] = c.candidate_scope_id("candidate-test")
    return result + reader


def measure(events, **kwargs):
    return c.measure_upload_reader(events, expected_source_scope=c.source_scope_id("source-s0"), run_status="succeeded", **kwargs)


def test_exact_open_join_is_order_independent_and_never_uses_another_open():
    assert measure(list(reversed(rows())))["value"] == 120.25
    for i in range(6):
        incomplete = rows(); incomplete.pop(i)
        assert measure(incomplete)["status"] == "not_available"
    extra = evidence(scope="reader_" + "2" * 32)
    assert measure(rows() + extra)["status"] == "observed"
    assert measure(rows()[:2] + extra)["status"] == "not_available"
    assert measure(rows(), evidence_incomplete=True)["value"] is None


@pytest.mark.parametrize("upload_seconds, expected", [
    (0.0, "not_available"),
    (1.499999, "not_available"),
    (1.5, "observed"),
    (1.500001, "observed"),
])
def test_upload_duration_contains_its_exact_reader_open(upload_seconds, expected):
    events = rows()  # The matching Reader interval is 1.5 seconds.
    events[1].payload["duration_seconds"] = upload_seconds
    result = measure(events)
    assert result["status"] == expected
    assert result["value"] == (upload_seconds if expected == "observed" else None)


@pytest.mark.parametrize("change", [
    lambda r: r.append(copy.deepcopy(r[0])), lambda r: r[1].payload.update(ordinal=True),
    lambda r: r[1].payload.update(duration_seconds=True), lambda r: r[1].payload.update(duration_seconds=float("inf")),
    lambda r: r[1].payload.update(duration_seconds=10**400), lambda r: r[1].payload.update(source_scope_id="source_" + "0"*64),
    lambda r: r[1].payload.update(frontend_revision="c"*40), lambda r: r[1].payload.update(filename="test.pdf"),
    lambda r: r[-1].payload.update(mode="reopen"), lambda r: r[-1].payload.update(candidate_scope_id="candidate_" + "0"*16),
])
def test_conflicting_malformed_or_private_evidence_is_not_observed(change):
    events = rows(); change(events)
    assert measure(events)["status"] == "not_available"


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'[]', b'\xff', b'x'*8193])
def test_strict_decoder(raw):
    assert c.decode_payload(raw)[1] is False


def test_durable_exact_identity_idempotency_and_conflict_cap():
    db = _session(); run = seed(db); factory = sessionmaker(bind=db.get_bind())
    assert p.accept("dispatch-test", ROOT, FRONT, SHA, session_factory=factory)
    assert p.accept("dispatch-test", ROOT, FRONT, SHA, session_factory=factory)
    assert p.terminal("wrong-doc", request(), SHA, session_factory=factory) == 409
    assert p.terminal("doc-s0", {**request(), "upload_scope_id": "upr_" + "2"*32}, SHA, session_factory=factory) == 409
    assert p.terminal("doc-s0", request(), SHA, session_factory=factory) == 204
    assert p.terminal("doc-s0", request(), SHA, session_factory=factory) == 204
    assert db.query(ProcessingEvent).count() == 2
    for _ in range(3):
        assert p.terminal("doc-s0", {**request(), "duration_seconds": 120.5}, SHA, session_factory=factory) == 409
    durable = db.query(ProcessingEvent).all()
    assert len(durable) == 3
    assert {json.loads(e.payload_json)["ordinal"] for e in durable} == {0, 1, 2}
    assert all(e.processing_run_id == run and "candidate-test" not in e.payload_json for e in durable)
    assert not p.accept("dispatch-test", ROOT, FRONT, SHA, session_factory=factory)
    db.close()


def test_acceptance_can_precede_run_but_conflicting_acceptance_invalidates():
    from app.models import ProcessingRun
    db = _session(); seed(db); factory = sessionmaker(bind=db.get_bind())
    db.query(ProcessingRun).delete(); db.commit()
    assert p.accept("dispatch-test", ROOT, FRONT, SHA, session_factory=factory)
    assert not p.accept("dispatch-test", "upr_" + "2"*32, FRONT, SHA, session_factory=factory)
    assert sorted(json.loads(r.payload_json)["ordinal"] for r in db.query(ProcessingEvent)) == [0, 2]
    assert db.query(ProcessingRun).count() == 0
    db.close()


def test_http_strict_body_and_gate(monkeypatch):
    monkeypatch.setattr(http, "revision", lambda: SHA)
    writes = []
    monkeypatch.setattr(p, "terminal", lambda *args: writes.append(args) or 204)
    app = FastAPI(); app.add_api_route("/d/{document_ref}", http.terminal, methods=["POST"])
    with TestClient(app) as client:
        assert client.post("/d/doc-s0", json=request()).status_code == 204
        assert client.post("/d/doc-s0", json={**request(), "raw_url": "https://invalid"}).status_code == 422
        assert client.post("/d/doc-s0", content=b"x"*2049, headers={"content-type":"application/json"}).status_code == 413
        raw = json.dumps(request()).replace('"duration_seconds": 120.25', '"duration_seconds":1,"duration_seconds":2')
        assert client.post("/d/doc-s0", content=raw, headers={"content-type":"application/json"}).status_code == 422
        monkeypatch.setattr(http, "revision", lambda: None)
        assert client.post("/d/doc-s0", json=request()).status_code == 404
    assert len(writes) == 1


def test_upload_hook_and_ack_fail_open_without_changing_body(monkeypatch):
    monkeypatch.setattr(http, "revision", lambda: SHA)
    calls = []
    def dispatch(_): pass
    dispatch.__module__ = "app.processing.ingestion_dispatch"; dispatch.__name__ = "run_ingestion_dispatch"
    wrapped = http._wrap_finalize(lambda *args: calls.append("old-finalize"))
    async def endpoint(scope, receive, send):
        await asyncio.to_thread(wrapped, dispatch, ("dispatch-test",), {})
        await send({"type":"http.response.start", "status":200, "headers":[]})
        await send({"type":"http.response.body", "body":b'{"book_id":"doc-s0"}'})
    async def run():
        messages = []
        async def receive(): return {"type":"http.request", "body":b""}
        async def send(m): messages.append(m)
        await http.UploadReaderMiddleware(endpoint)({"type":"http", "method":"POST", "path":"/api/v1/upload",
            "headers":[(b'x-atlas-s0-upload',ROOT.encode()),(b'x-atlas-s0-upload-frontend',FRONT.encode())]}, receive, send)
        return messages
    monkeypatch.setattr(p, "accept", lambda *args: True)
    result = asyncio.run(run()); assert dict(result[0]["headers"])[b'x-atlas-s0-upload-accepted'] == ROOT.encode()
    def failure(*args): raise RuntimeError("observer unavailable")
    monkeypatch.setattr(p, "accept", failure)
    failed = asyncio.run(run()); assert failed[0]["headers"] == [] and failed[1] == result[1]
    assert calls == ["old-finalize", "old-finalize"] and http._CURRENT.get() is None


def test_final_composed_collector_requires_matching_durable_reader_rows():
    from app.processing.s0_baseline import collect_s0_run_snapshot
    from tests.test_s0_baseline import _metric
    import app.processing.s0_baseline as baseline
    if not hasattr(baseline, "_measure_upload_reader"):
        pytest.skip("final composition gate")
    db = _session(); run = seed(db)
    for n, e in enumerate(rows()):
        db.add(ProcessingEvent(id=f"upload-reader-{n}", processing_run_id=run, document_id="doc-s0",
            schema_version="atlas.processing.event.v1", event_name=e.event_name, severity="info", payload_json=json.dumps(e.payload)))
    db.commit()
    result = _metric(collect_s0_run_snapshot(db, processing_run_id=run), "upload_to_reader_ready_seconds")
    assert result.status == "observed" and result.value == 120.25
    row = db.query(ProcessingEvent).filter_by(event_name=c.TERMINAL).one()
    original_payload = row.payload_json
    shorter = json.loads(original_payload)
    shorter["duration_seconds"] = 1.0  # Matching Reader terminal reports 1.5.
    row.payload_json = json.dumps(shorter)
    db.commit()
    result = _metric(collect_s0_run_snapshot(db, processing_run_id=run), "upload_to_reader_ready_seconds")
    assert result.status == "not_available" and result.value is None
    row.payload_json = original_payload
    row.payload_json = row.payload_json.replace('"duration_seconds": 120.25', '"duration_seconds":1,"duration_seconds":120.25')
    db.commit()
    result = _metric(collect_s0_run_snapshot(db, processing_run_id=run), "upload_to_reader_ready_seconds")
    assert result.status == "not_available" and result.value is None
    db.close()


def test_bounded_writers_keep_cleanup_ownership_after_waiter_cancellation():
    from threading import Event
    entered, release = Event(), Event()
    def writer(): entered.set(); release.wait(3); return True
    async def exercise():
        task = asyncio.create_task(http._publish(writer))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
            # One running writer still owns its slot after the waiter is gone.
            assert http._CAPACITY.acquire(blocking=False)
            try: assert not http._CAPACITY.acquire(blocking=False)
            finally: http._CAPACITY.release()
        finally: release.set()
    asyncio.run(exercise())


def test_composition_is_idempotent_and_production_install_is_inert(tmp_path, monkeypatch):
    from pathlib import Path
    import shutil
    from scripts.apply_s0_upload_reader_observability import main
    import app.processing.s0_baseline as baseline
    monkeypatch.setattr(http, "revision", lambda: None)
    app = FastAPI(); http.install(app)
    assert not app.user_middleware and not getattr(app.state, "s0_upload_reader_installed", False)
    if not hasattr(baseline, "_measure_upload_reader"):
        pytest.skip("final composition gate")
    root = Path(__file__).resolve().parents[1]
    paths = ('app/main.py', 'app/processing/s0_baseline.py', 'tests/test_s0_baseline.py')
    for name in paths:
        target = tmp_path / name; target.parent.mkdir(parents=True, exist_ok=True); shutil.copy(root / name, target)
    before = {name: (tmp_path/name).read_bytes() for name in paths}
    monkeypatch.chdir(tmp_path); main(); main()
    assert all((tmp_path/name).read_bytes() == value for name, value in before.items())


def test_postgresql_concurrent_slots_and_lock_timeout():
    if os.environ.get("ATLAS_POSTGRESQL_SCHEMA_TEST") != "1":
        pytest.skip("isolated PostgreSQL CI gate")
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from app.database import normalize_database_url
    from app.models import Base, Document
    import uuid
    url = make_url(normalize_database_url(os.environ["DATABASE_URL"]))
    assert url.host in ("127.0.0.1", "localhost") and url.database == "atlas_staging_ci"
    schema = "s0_upload_reader_" + uuid.uuid4().hex
    admin = create_engine(url)
    with admin.begin() as db: db.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        with factory() as db: seed(db)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: p.accept("dispatch-test", ROOT, FRONT, SHA, session_factory=factory), range(4)))
        assert all(results)
        with factory() as db, db.begin():
            db.execute(select(Document.id).where(Document.id == "doc-s0").with_for_update())
            with ThreadPoolExecutor(max_workers=1) as pool:
                assert pool.submit(p.terminal, "doc-s0", request(), SHA, session_factory=factory).result(3) == 503
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: p.terminal("doc-s0", request(), SHA, session_factory=factory), range(4)))
        assert results == [204]*4
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda n: p.terminal("doc-s0", {**request(), "duration_seconds": 121+n}, SHA,
                session_factory=factory), range(4)))
        assert results == [409]*4
        with factory() as db: assert db.query(ProcessingEvent).count() == 3
    finally:
        engine.dispose()
        with admin.begin() as db: db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
