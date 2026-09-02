from __future__ import annotations
import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace as NS
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import StaticPool

from app import s0_reader_open_observability as reader

SHA = "a" * 40
SCOPE = "reader_" + "1" * 32


def evidence(mode="first_open", scope=SCOPE):
    common = dict(measurement_scope=reader.MEASUREMENT_SCOPE, open_scope_id=scope,
        candidate_scope_id="candidate_" + "c" * 16, backend_revision=SHA, succeeded=True)
    routes = ["metadata", "navigation", "content"] + (["content"] if mode == "reopen" else [])
    rows = [NS(event_name=reader.REQUEST_EVENT, payload={**common, "ordinal": i, "route": route,
        "server_seconds": .1, "query_count": i, "node_limit": 150 if route == "content" else 0,
        "window_start": ((i - 2) * 150 if mode == "reopen" and route == "content" else 0)}) for i, route in enumerate(routes, 1)]
    rows.append(NS(event_name=reader.TERMINAL_EVENT, payload={**common, "mode": mode,
        "frontend_revision": "b" * 40, "duration_seconds": 1.5, "request_count": len(routes)}))
    return rows


def measure(rows, **kwargs):
    return reader.measure_reader_open(rows, evidence_incomplete=kwargs.get("incomplete", False),
        uninspectable_event_names=kwargs.get("uninspectable", frozenset()))


def test_first_and_reopen_are_separate_samples_and_query_counts():
    result = measure(list(reversed(evidence()+evidence("reopen", "reader_"+"2"*32))))
    assert result["status"] == "observed"
    assert result["latency"] == {"first_open": {"sample_count": 1, "mean_seconds": 1.5}, "reopen": {"sample_count": 1, "mean_seconds": 1.5}}
    assert result["queries"]["first_open"]["counts"] == [6]
    assert result["queries"]["reopen"]["counts"] == [10]
    assert measure(evidence(), incomplete=True)["status"] == "partial"


@pytest.mark.parametrize("change", [
    lambda rows: rows.pop(), lambda rows: rows.pop(0),
    lambda rows: rows.append(copy.deepcopy(rows[0])), lambda rows: rows.append(copy.deepcopy(rows[-1])),
    lambda rows: rows[0].payload.update(query_count=True), lambda rows: rows[0].payload.update(query_count=-1),
    lambda rows: rows[0].payload.update(server_seconds=10**400), lambda rows: rows[-1].payload.update(duration_seconds=float("nan")),
    lambda rows: rows[-1].payload.update(request_count=True), lambda rows: rows[1].payload.update(ordinal=4),
    lambda rows: rows[1].payload.update(candidate_scope_id="candidate_"+"d"*16),
    lambda rows: rows[0].payload.update(backend_revision="d"*40), lambda rows: rows[2].payload.update(node_limit=500),
    lambda rows: rows[2].payload.update(window_start=150), lambda rows: rows[0].payload.update(filename="private.pdf"),
])
def test_invalid_incomplete_duplicate_and_private_evidence_is_unavailable(change):
    rows = evidence(); change(rows)
    assert measure(rows)["status"] == "not_available"


def test_limits_malformed_mixed_revisions_and_discontinuous_reopen():
    assert measure([])["status"] == "not_available"
    for name in (reader.REQUEST_EVENT, reader.TERMINAL_EVENT):
        assert measure(evidence(), uninspectable={name})["status"] == "not_available"
    rows = evidence("reopen"); rows[3].payload["window_start"] = 450
    assert measure(rows)["status"] == "not_available"
    rows = evidence()+evidence("reopen", "reader_"+"2"*32); rows[-1].payload["frontend_revision"] = "d"*40
    assert measure(rows)["status"] == "not_available"
    rows = [e for n in range(33) for e in evidence(scope=f"reader_{n:032x}")]
    assert measure(rows)["status"] == "not_available"


@pytest.fixture
def staged(monkeypatch, tmp_path):
    marker = tmp_path/'staging-revision.txt'; marker.write_text(SHA)
    monkeypatch.setattr(reader, "_REVISION_FILE", marker)
    return marker


def test_query_count_crosses_worker_thread_and_excludes_binary_and_persistence(staged, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    event.listen(engine, "before_cursor_execute", reader._before_execute)
    writes=[]
    def persist(*args):
        assert reader._CURRENT.get() is None
        with engine.connect() as db: db.execute(text("SELECT 'private persistence statement'"))
        writes.append(args)
    monkeypatch.setattr(reader, "_persist", persist)
    app=FastAPI(); app.add_middleware(reader.ReaderOpenMiddleware)
    @app.get('/api/reader/v2/documents/{doc}/content')
    def content(doc: str):
        with engine.connect() as db:
            db.execute(text("SELECT 'secret row'")); db.execute(text("SELECT 2"))
        reader.observe_reader_view(NS(document_ref=doc, candidate_id="candidate-private"))
        return {"nodes": []}
    with TestClient(app) as client:
        headers={"X-Atlas-S0-Open":SCOPE,"X-Atlas-S0-Ordinal":"3"}
        response=client.get('/api/reader/v2/documents/doc/content?limit=150',headers=headers)
        assert response.status_code==200 and response.headers['x-atlas-s0-revision']==SHA
        assert writes[0][3]['query_count']==2
        assert 'secret' not in json.dumps(writes[0][3]) and 'candidate-private' not in json.dumps(writes[0][3])
        client.get('/api/reader/v2/documents/doc/content?limit=500',headers=headers)
        client.get('/api/reader/v2/documents/doc/content?limit=150&start_node_order=151',headers=headers)
        client.get('/api/reader/v2/documents/doc/assets/a/content',headers=headers)
        staged.unlink(); client.get('/api/reader/v2/documents/doc/content?limit=150',headers=headers)
        assert len(writes)==1
    engine.dispose()


def test_concurrent_requests_do_not_share_observation_or_count(staged, monkeypatch):
    writes=[]
    monkeypatch.setattr(reader,"_persist",lambda *args:writes.append(args))
    async def endpoint(scope, receive, send):
        doc=scope['path'].rsplit('/',1)[-1]
        reader.observe_reader_view(NS(document_ref=doc,candidate_id=doc))
        for _ in range(2 if doc=='a' else 5):
            await asyncio.to_thread(reader._before_execute)
            await asyncio.sleep(0)
        await send({'type':'http.response.start','status':200,'headers':[]})
        await send({'type':'http.response.body','body':b'{}'})
    async def run():
        async def no_op(*args): pass
        middleware=reader.ReaderOpenMiddleware(endpoint)
        await asyncio.gather(*(middleware({'type':'http','method':'GET','path':f'/api/reader/v2/documents/{d}',
            'headers':[(b'x-atlas-s0-open',SCOPE.encode()),(b'x-atlas-s0-ordinal',b'1')]},no_op,no_op) for d in ('a','b')))
    asyncio.run(run())
    assert {w[0]:w[3]['query_count'] for w in writes}=={'a':2,'b':5}


def test_disconnect_emits_no_success_and_failed_write_does_not_change_response(staged, monkeypatch):
    writes=[]
    monkeypatch.setattr(reader,"_persist",lambda *args:writes.append(args))
    async def endpoint(scope, receive, send):
        reader.observe_reader_view(NS(document_ref='doc',candidate_id='candidate'))
        await send({'type':'http.response.start','status':200,'headers':[]})
        await send({'type':'http.response.body','body':b'{}'})
    async def run(disconnect):
        async def receive(): pass
        async def send(message):
            if disconnect and message['type']=='http.response.body': raise OSError('disconnect')
        await reader.ReaderOpenMiddleware(endpoint)({'type':'http','method':'GET','path':'/api/reader/v2/documents/doc',
            'headers':[(b'x-atlas-s0-open',SCOPE.encode()),(b'x-atlas-s0-ordinal',b'1')]},receive,send)
    with pytest.raises(OSError): asyncio.run(run(True))
    assert not writes
    def failure(*args): raise RuntimeError('database down')
    monkeypatch.setattr(reader,'_persist',failure)
    asyncio.run(run(False))


def test_terminal_is_bounded_and_keeps_raw_identity_out_of_event(staged,monkeypatch):
    writes=[]
    monkeypatch.setattr(reader,'_persist',lambda *args: writes.append(args) or True)
    app=FastAPI(); app.add_api_route('/documents/{document_ref}/s0-open',reader.terminal,methods=['POST'])
    body=dict(open_scope_id=SCOPE,candidate_id='private-candidate',frontend_revision='b'*40,backend_revision=SHA,
        mode='first_open',request_count=3,duration_seconds=1.25)
    with TestClient(app) as client:
        assert client.post('/documents/doc/s0-open',json=body).status_code==204
        assert 'candidate_id' not in writes[0][3]
        assert client.post('/documents/doc/s0-open',json={**body,'filename':'private.pdf'}).status_code==422
        assert client.post('/documents/doc/s0-open',content=b'x'*2049).status_code==413
        assert client.post('/documents/doc/s0-open',json={**body,'backend_revision':'c'*40}).status_code==422
        staged.unlink()
        assert client.post('/documents/doc/s0-open',json=body).status_code==404
        assert len(writes)==1


def test_blocked_persistence_does_not_block_event_loop(staged,monkeypatch):
    entered,release=threading.Event(),threading.Event()
    def persist(*args):
        entered.set(); assert release.wait(5)
        return True
    monkeypatch.setattr(reader,'_persist',persist)
    async def endpoint(scope,receive,send):
        reader.observe_reader_view(NS(document_ref='doc',candidate_id='candidate'))
        await send({'type':'http.response.start','status':200,'headers':[]})
        await send({'type':'http.response.body','body':b'{}'})
    async def run():
        async def no_op(*args): pass
        task=asyncio.create_task(reader.ReaderOpenMiddleware(endpoint)({'type':'http','method':'GET',
            'path':'/api/reader/v2/documents/doc','headers':[(b'x-atlas-s0-open',SCOPE.encode()),(b'x-atlas-s0-ordinal',b'1')]},no_op,no_op))
        try:
            assert await asyncio.to_thread(entered.wait,2)
            for _ in range(3): await asyncio.sleep(0)
            assert not task.done()
        finally: release.set()
        await task
    asyncio.run(run())


def test_collector_maps_durable_events_from_exact_run_and_detects_malformed():
    from tests.test_s0_baseline import _session,_seed_run,_metric
    from app.processing.s0_baseline import collect_s0_run_snapshot
    from app.processing.processing_event_model import ProcessingEvent
    db=_session(); run_id=_seed_run(db,with_events=False)
    for i,e in enumerate(evidence()):
        db.add(ProcessingEvent(id=f'reader-{i}',processing_run_id=run_id,document_id='doc-s0',
            schema_version='atlas.processing.event.v1',event_name=e.event_name,severity='info',payload_json=json.dumps(e.payload)))
    db.commit()
    s=collect_s0_run_snapshot(db,processing_run_id=run_id)
    assert _metric(s,'reader_open_latency_seconds').status=='observed'
    assert _metric(s,'reader_bounded_query_count').value['first_open']['counts']==[6]
    db.add(ProcessingEvent(id='malformed',processing_run_id=run_id,document_id='doc-s0',schema_version='atlas.processing.event.v1',
        event_name=reader.REQUEST_EVENT,severity='info',payload_json='{'))
    db.commit()
    assert _metric(collect_s0_run_snapshot(db,processing_run_id=run_id),'reader_bounded_query_count').status=='not_available'
    db.close()


def test_persistence_uses_exact_candidate_run_and_hashes_identity(staged,monkeypatch):
    from tests.test_s0_baseline import _session,_seed_run
    from sqlalchemy.orm import sessionmaker
    from app.models_v2 import StructuredContentCandidateV2Record as Candidate
    from app.processing import processing_events
    from app.processing.processing_event_model import ProcessingEvent
    db=_session(); run=_seed_run(db,with_events=False)
    db.add(Candidate(candidate_id='private-candidate',document_id='doc-s0',lineage_key='lineage',
        schema_id='atlas.structured-content.v2',schema_version=2,processing_run_ref=run,recovery_state='complete'))
    db.commit()
    factory=sessionmaker(bind=db.get_bind())
    monkeypatch.setattr(processing_events,'staging_processing_events_enabled',lambda:True)
    payload=evidence()[0].payload.copy();payload.pop('candidate_scope_id')
    assert reader._persist('doc-s0','private-candidate',reader.REQUEST_EVENT,payload,factory)
    assert not reader._persist('wrong-document','private-candidate',reader.REQUEST_EVENT,payload,factory)
    assert not reader._persist('doc-s0','missing-candidate',reader.REQUEST_EVENT,payload,factory)
    row=db.query(ProcessingEvent).one()
    assert row.processing_run_id==run and row.document_id=='doc-s0'
    assert 'private-candidate' not in row.payload_json and 'candidate_' in row.payload_json
    staged.unlink()
    assert not reader._persist('doc-s0','private-candidate',reader.REQUEST_EVENT,payload,factory)
    db.close()


def test_overlay_is_idempotent_and_install_staging_only(monkeypatch,tmp_path):
    from scripts.apply_s0_reader_open_observability import main
    # CI applies the prerequisite overlays before this test.
    import shutil
    root=Path(__file__).resolve().parents[1]
    for rel in ('app/main.py','app/routers/reader_v2.py','app/processing/s0_baseline.py','tests/test_s0_baseline.py'):
        target=tmp_path/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy(root/rel,target)
    monkeypatch.chdir(tmp_path);main()
    first={p:p.read_bytes() for p in tmp_path.rglob('*.py')};main()
    assert all(p.read_bytes()==value for p,value in first.items())
    monkeypatch.setattr(reader,'_REVISION_FILE',tmp_path/'absent')
    app=FastAPI();reader.install(app)
    assert not app.user_middleware
