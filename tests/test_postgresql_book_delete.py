"""Real-PostgreSQL regression for terminal processing-state book deletion."""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.book_service import BookService
from app.database import engine
from app.models import Document, DocumentType, ProcessingRun, SourceFile
from app.processing.ingestion_dispatch_model import IngestionDispatch
from app.storage.local import LocalStorageProvider


pytestmark = pytest.mark.skipif(
    os.getenv("ATLAS_POSTGRESQL_SCHEMA_TEST") != "1",
    reason="requires the disposable PostgreSQL CI service",
)


def test_failed_book_with_terminal_processing_state_deletes_under_postgresql_constraints(tmp_path):
    assert engine.dialect.name == "postgresql"
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    storage = LocalStorageProvider(tmp_path / "objects")
    book_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    processing_run_id = f"ci-delete-{uuid.uuid4()}"
    dispatch_id = str(uuid.uuid4())
    retained = b"%PDF-1.4\n% postgres-terminal-delete\n%%EOF\n"
    put_result = storage.put(retained)
    storage_reference = str(put_result.reference)

    try:
        db.add(
            Document(
                id=book_id,
                document_type=DocumentType.BOOK,
                title="PostgreSQL terminal delete",
                file_type="pdf",
                status="failed",
                pages_count=1,
            )
        )
        db.flush()
        db.add(
            SourceFile(
                id=source_id,
                document_id=book_id,
                original_filename="postgres-terminal-delete.pdf",
                file_type="pdf",
                mime_type="application/pdf",
                byte_size=put_result.byte_size,
                checksum_sha256=put_result.checksum_sha256,
                storage_reference=storage_reference,
                retained=1,
                is_primary=1,
            )
        )
        db.flush()
        db.add(
            ProcessingRun(
                processing_run_id=processing_run_id,
                document_id=book_id,
                source_file_id=source_id,
                status="failed",
                provider_ref="paddle-vl",
            )
        )
        db.add(
            IngestionDispatch(
                id=dispatch_id,
                acceptance_key=f"postgres-delete:{uuid.uuid4().hex}",
                document_id=book_id,
                source_file_id=source_id,
                kind="pdf",
                processing_attempt_id=f"pdf-ingest-{uuid.uuid4().hex}",
                provider_job_id=f"pdf-job-{uuid.uuid4().hex}",
                provider_request_id=f"pdf-request-{uuid.uuid4().hex}",
                status="succeeded",
            )
        )
        db.commit()

        assert BookService.delete_book(db, book_id, storage) is True
        assert db.query(ProcessingRun).filter_by(processing_run_id=processing_run_id).count() == 0
        assert db.query(IngestionDispatch).filter_by(id=dispatch_id).count() == 0
        assert db.query(SourceFile).filter_by(id=source_id).count() == 0
        assert db.query(Document).filter_by(id=book_id).count() == 0
        assert not storage.exists(storage_reference)
    finally:
        db.rollback()
        # Best-effort cleanup if an assertion fails before the service completes.
        db.query(ProcessingRun).filter_by(processing_run_id=processing_run_id).delete(synchronize_session=False)
        db.query(IngestionDispatch).filter_by(id=dispatch_id).delete(synchronize_session=False)
        db.query(SourceFile).filter_by(id=source_id).delete(synchronize_session=False)
        db.query(Document).filter_by(id=book_id).delete(synchronize_session=False)
        db.commit()
        db.close()
