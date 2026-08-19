"""Book deletion contracts around durable processing state."""
from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Document, DocumentType, ProcessingRun, SourceFile
from app.processing.ingestion_dispatch_model import IngestionDispatch
from app.routers.books import delete_book
from app.storage.local import LocalStorageProvider


@pytest.fixture()
def delete_env(tmp_path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    storage = LocalStorageProvider(tmp_path / "objects")
    try:
        yield db, storage
    finally:
        db.close()
        engine.dispose()


def _seed_book_source(db, storage, *, document_status: str):
    retained = b"%PDF-1.4\n% terminal-delete-test\n%%EOF\n"
    put_result = storage.put(retained)
    book = Document(
        document_type=DocumentType.BOOK,
        title="terminal-delete-test",
        file_type="pdf",
        status=document_status,
        pages_count=1,
    )
    db.add(book)
    db.flush()

    source = SourceFile(
        document_id=book.id,
        original_filename="terminal-delete-test.pdf",
        file_type="pdf",
        mime_type="application/pdf",
        byte_size=put_result.byte_size,
        checksum_sha256=put_result.checksum_sha256,
        storage_reference=str(put_result.reference),
        retained=1,
        is_primary=1,
    )
    db.add(source)
    db.flush()
    return book, source


def _seed_book_with_run(db, storage, *, document_status: str, run_status: str):
    book, source = _seed_book_source(db, storage, document_status=document_status)
    run = ProcessingRun(
        processing_run_id=f"run-{book.id}",
        document_id=book.id,
        source_file_id=source.id,
        status=run_status,
        provider_ref="paddle-vl",
    )
    db.add(run)
    db.commit()
    return book.id, source.id, run.processing_run_id, source.storage_reference


def _seed_book_with_dispatch(db, storage, *, dispatch_status: str):
    book, source = _seed_book_source(db, storage, document_status="processing")
    dispatch = IngestionDispatch(
        id=str(uuid.uuid4()),
        acceptance_key=f"delete-test:{uuid.uuid4().hex}",
        document_id=book.id,
        source_file_id=source.id,
        kind="pdf",
        processing_attempt_id=f"pdf-ingest-{uuid.uuid4().hex}",
        provider_job_id=f"pdf-job-{uuid.uuid4().hex}",
        provider_request_id=f"pdf-request-{uuid.uuid4().hex}",
        status=dispatch_status,
    )
    db.add(dispatch)
    db.commit()
    return book.id, source.id, dispatch.id, source.storage_reference


def test_failed_book_with_failed_processing_run_can_be_deleted(delete_env):
    db, storage = delete_env
    book_id, source_id, processing_run_id, storage_reference = _seed_book_with_run(
        db,
        storage,
        document_status="failed",
        run_status="failed",
    )
    assert storage.exists(storage_reference)

    response = asyncio.run(delete_book(book_id, db=db, storage=storage))

    assert response == {"message": f"Book {book_id} deleted successfully"}
    assert db.query(ProcessingRun).filter_by(processing_run_id=processing_run_id).count() == 0
    assert db.query(SourceFile).filter_by(id=source_id).count() == 0
    assert db.query(Document).filter_by(id=book_id).count() == 0
    assert not storage.exists(storage_reference)


def test_active_processing_run_blocks_delete_and_preserves_source(delete_env):
    db, storage = delete_env
    book_id, source_id, processing_run_id, storage_reference = _seed_book_with_run(
        db,
        storage,
        document_status="processing",
        run_status="running",
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(delete_book(book_id, db=db, storage=storage))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Book is still being processed and cannot be deleted yet"
    assert db.query(ProcessingRun).filter_by(processing_run_id=processing_run_id).count() == 1
    assert db.query(SourceFile).filter_by(id=source_id).count() == 1
    assert db.query(Document).filter_by(id=book_id).count() == 1
    assert storage.exists(storage_reference)


@pytest.mark.parametrize("dispatch_status", ["queued", "claimed", "running"])
def test_active_ingestion_dispatch_blocks_delete_before_processing_run_exists(
    delete_env,
    dispatch_status: str,
):
    db, storage = delete_env
    book_id, source_id, dispatch_id, storage_reference = _seed_book_with_dispatch(
        db,
        storage,
        dispatch_status=dispatch_status,
    )
    assert db.query(ProcessingRun).filter_by(document_id=book_id).count() == 0

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(delete_book(book_id, db=db, storage=storage))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Book is still being processed and cannot be deleted yet"
    assert db.query(IngestionDispatch).filter_by(id=dispatch_id).count() == 1
    assert db.query(SourceFile).filter_by(id=source_id).count() == 1
    assert db.query(Document).filter_by(id=book_id).count() == 1
    assert storage.exists(storage_reference)
