"""Exact Staging composition regressions, with synthetic delegates and local SQL."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import shutil
import threading
from types import SimpleNamespace as NS
import uuid

import pytest

from app import s0_preprocessing_cpu_observability as o
from app import s0_preprocessing_cpu_metrics as m
from tests.test_s0_preprocessing_cpu_observability import (
    capture, database, evidence, measured, REV, RUN, DOC, SOURCE,
)


def test_real_executor_bridge_and_phase2_alias(monkeypatch, capture):
    from app.processing import pdf_ingestion as ingestion
    from app.processing import s0_phase2_stage_observability as stage
    assert getattr(ingestion._prepare_geometry_provider_input_async, "_s0_worker_cpu_installed", False)
    assert getattr(ingestion.process_pdf_document_background, "_s0_worker_cpu_installed", False)
    first = ingestion.process_pdf_document_background
    o.install_preprocessing_cpu_observability()
    assert first is ingestion.process_pdf_document_background
    threads = []
    expected = NS(byte_size=3, preprocessing=NS(page_count=1, changed_page_count=0))
    def synthetic(**kwargs):
        threads.append(threading.get_ident())
        assert kwargs["processing_attempt_id"] == RUN
        return expected
    monkeypatch.setattr(ingestion, "prepare_geometry_provider_input", stage._wrap_preprocessing(synthetic))
    monkeypatch.setattr(ingestion, "_read_verified_source_pdf", lambda *_: b"synthetic-not-a-pdf")
    monkeypatch.setattr(ingestion, "record_pdf_processing_heartbeat", lambda **_: None)
    monkeypatch.setattr(stage, "_record", lambda **_: None)
    with ThreadPoolExecutor(max_workers=1) as pool:
        monkeypatch.setattr(ingestion, "_PDF_PREPROCESSING_EXECUTOR", pool)
        monkeypatch.setattr(ingestion, "_PDF_PREPROCESSING_CAPACITY", threading.BoundedSemaphore(2))
        async def delegate(*_):
            result = await ingestion._prepare_geometry_provider_input_async(
                storage=object(), descriptor=NS(document_id=DOC, source_file_id=SOURCE,
                    byte_size=10, filename=None), processing_attempt_id=RUN,
                document_id=DOC, expected_page_count=1)
            o.note_cpu_terminal(DOC, RUN, "completed")
            return result
        assert asyncio.run(o.observe_pdf_processing(delegate, DOC, SOURCE, NS(processing_attempt_id=RUN))) is expected
    assert threads and threads != [threading.get_ident()]
    assert measured(capture)["status"] == "observed"


def test_terminal_note_requires_real_committed_run_identity(database, monkeypatch):
    from app.processing import pdf_ingestion as ingestion
    factory, root, _ = database
    monkeypatch.setattr(ingestion, "SessionLocal", factory)
    monkeypatch.setattr(ingestion, "_diagnostic", lambda *_, **__: None)
    root.outcome = "unknown"
    token = o._ROOT.set(root)
    try:
        ingestion._set_document_terminal_state(root.document_id, processing_attempt_id=root.run_id,
                                               status="completed", error_message=None)
    finally:
        o._ROOT.reset(token)
    assert root.outcome == "completed"


def test_overlay_idempotence_and_partial_install_failure(tmp_path, monkeypatch):
    from scripts.apply_s0_preprocessing_cpu_observability import main
    from scripts.apply_s0_failure_retry_observability import main as previous
    source = Path(__file__).resolve().parents[1]
    paths = ("app/processing/pdf_ingestion.py", "app/processing/s0_baseline.py",
             "app/processing/s0_phase2_stage_observability.py", "app/processing/orchestration.py")
    for name in paths:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(source / name, target)
    monkeypatch.chdir(tmp_path)
    before = {p: Path(p).read_bytes() for p in paths}
    previous(); main(); main()
    assert before == {p: Path(p).read_bytes() for p in paths}
    path = Path(paths[0])
    path.write_text(path.read_text().replace("    note_preprocessing_future(concurrent_future)\n", ""))
    with pytest.raises(RuntimeError, match="partially installed"):
        main()


@pytest.mark.skipif(os.getenv("ATLAS_POSTGRESQL_SCHEMA_TEST") != "1", reason="disposable PostgreSQL CI only")
def test_disposable_postgres_atomic_batch_and_duplicate_rejection(monkeypatch):
    from sqlalchemy import event, text
    from sqlalchemy.orm import sessionmaker
    from app.database import engine
    from app.models import Base, Document, SourceFile, ProcessingRun
    from app.processing.processing_event_model import ProcessingEvent
    from tests.test_s0_provider_source_download_observability import _seed_base, RUN_ID, DOCUMENT_ID, SOURCE_FILE_ID
    assert engine.dialect.name == "postgresql"
    assert engine.url.host in ("localhost", "127.0.0.1", "::1"), "refuse non-local test database"
    schema = "cpu_test_" + uuid.uuid4().hex
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated = engine.execution_options(schema_translate_map={None: schema})
    try:
        Base.metadata.create_all(isolated, tables=[Document.__table__, SourceFile.__table__,
                                                  ProcessingRun.__table__, ProcessingEvent.__table__])
        factory = sessionmaker(bind=isolated)
        with factory() as db:
            _seed_base(db)
        root, rows = evidence()
        root.run_id, root.document_id, root.source_id = RUN_ID, DOCUMENT_ID, SOURCE_FILE_ID
        for _, p in rows:
            p.update(root.common())
        monkeypatch.setattr(o, "_revision", lambda: REV)
        assert o._persist(root, rows[:2], session_factory=factory)
        def fail(db):
            db.flush()
            raise RuntimeError("synthetic rollback")
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
            assert db.query(ProcessingEvent).filter(ProcessingEvent.event_name.in_(m.EVENT_NAMES)).count() == 4
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
