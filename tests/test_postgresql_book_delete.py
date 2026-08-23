"""Real-PostgreSQL regression for terminal processing-state book deletion."""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.book_service import BookService, _purge_structured_content
from app.database import engine
from app.models import (
    Document,
    DocumentType,
    ProcessingRun,
    SourceFile,
    StructuredContentCandidate,
    StructuredContentSelection,
)
from app.models_v2 import (
    StructuredContentAnchorV2Record,
    StructuredContentCandidateV2Record,
    StructuredContentEvidenceV2Record,
    StructuredContentNodeV2Record,
    StructuredContentSourceUnitV2Record,
)
from app.models_v2_selection import StructuredContentSelectionV2Record
from app.processing.ingestion_dispatch_model import IngestionDispatch
from app.storage.local import LocalStorageProvider


pytestmark = pytest.mark.skipif(
    os.getenv("ATLAS_POSTGRESQL_SCHEMA_TEST") != "1",
    reason="requires the disposable PostgreSQL CI service",
)


def _seed_structured_content(db, book_id: str) -> tuple[str, str]:
    v1_id = str(uuid.uuid4())
    v1_candidate = StructuredContentCandidate(
        id=v1_id,
        candidate_id=f"scv1-{uuid.uuid4().hex}",
        document_id=book_id,
        lineage_key=f"lineage-v1-{uuid.uuid4().hex}",
        schema_id="structured-content-v1",
        schema_version=1,
        recovery_state="complete",
    )
    db.add(v1_candidate)
    db.flush()
    db.add(
        StructuredContentSelection(
            document_id=book_id,
            candidate_id=v1_id,
            selection_version=1,
        )
    )

    v2_id = str(uuid.uuid4())
    v2_candidate = StructuredContentCandidateV2Record(
        id=v2_id,
        candidate_id=f"scv2-{uuid.uuid4().hex}",
        document_id=book_id,
        lineage_key=f"lineage-v2-{uuid.uuid4().hex}",
        schema_id="structured-content-v2",
        schema_version=2,
        recovery_state="complete",
    )
    db.add(v2_candidate)
    db.flush()
    db.add(
        StructuredContentSelectionV2Record(
            document_id=book_id,
            candidate_record_id=v2_id,
            selection_version=1,
        )
    )

    source_unit = StructuredContentSourceUnitV2Record(
        candidate_id=v2_id,
        source_unit_id="page-1",
        kind="physical_page",
        source_order=0,
        source_ref="source:test:page-1",
        recovery_state="complete",
        width=1000,
        height=1400,
        dimension_unit="px",
    )
    db.add(source_unit)
    db.flush()

    evidence = StructuredContentEvidenceV2Record(
        candidate_id=v2_id,
        evidence_id="evidence-1",
        source_unit_record_id=source_unit.id,
    )
    db.add(evidence)
    db.flush()
    db.add(
        StructuredContentAnchorV2Record(
            candidate_id=v2_id,
            source_unit_record_id=source_unit.id,
            owner_type="evidence",
            owner_record_id=evidence.id,
            anchor_order=0,
            anchor_kind="spatial",
            bbox_left=0.1,
            bbox_top=0.1,
            bbox_right=0.9,
            bbox_bottom=0.9,
        )
    )

    parent = StructuredContentNodeV2Record(
        candidate_id=v2_id,
        node_id="node-parent",
        lineage_key="node-parent-lineage",
        node_type="paragraph",
        sibling_order=0,
        recovery_state="complete",
    )
    db.add(parent)
    db.flush()
    db.add(
        StructuredContentNodeV2Record(
            candidate_id=v2_id,
            node_id="node-child",
            lineage_key="node-child-lineage",
            node_type="paragraph",
            parent_node_record_id=parent.id,
            sibling_order=0,
            recovery_state="complete",
        )
    )
    db.flush()
    return v1_id, v2_id


def test_completed_book_with_canonical_content_deletes_under_postgresql_constraints(tmp_path):
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
    v1_candidate_id: str | None = None
    v2_candidate_id: str | None = None

    try:
        db.add(
            Document(
                id=book_id,
                document_type=DocumentType.BOOK,
                title="PostgreSQL completed canonical delete",
                file_type="pdf",
                status="completed",
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
                status="succeeded",
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
        v1_candidate_id, v2_candidate_id = _seed_structured_content(db, book_id)
        db.commit()

        assert db.query(StructuredContentSelection).filter_by(document_id=book_id).count() == 1
        assert db.query(StructuredContentSelectionV2Record).filter_by(document_id=book_id).count() == 1
        assert db.query(StructuredContentEvidenceV2Record).filter_by(candidate_id=v2_candidate_id).count() == 1
        assert db.query(StructuredContentAnchorV2Record).filter_by(candidate_id=v2_candidate_id).count() == 1
        assert db.query(StructuredContentNodeV2Record).filter_by(candidate_id=v2_candidate_id).count() == 2

        assert BookService.delete_book(db, book_id, storage) is True

        assert db.query(ProcessingRun).filter_by(processing_run_id=processing_run_id).count() == 0
        assert db.query(IngestionDispatch).filter_by(id=dispatch_id).count() == 0
        assert db.query(SourceFile).filter_by(id=source_id).count() == 0
        assert db.query(StructuredContentSelection).filter_by(document_id=book_id).count() == 0
        assert db.query(StructuredContentCandidate).filter_by(id=v1_candidate_id).count() == 0
        assert db.query(StructuredContentSelectionV2Record).filter_by(document_id=book_id).count() == 0
        assert db.query(StructuredContentCandidateV2Record).filter_by(id=v2_candidate_id).count() == 0
        assert db.query(StructuredContentEvidenceV2Record).filter_by(candidate_id=v2_candidate_id).count() == 0
        assert db.query(StructuredContentAnchorV2Record).filter_by(candidate_id=v2_candidate_id).count() == 0
        assert db.query(StructuredContentNodeV2Record).filter_by(candidate_id=v2_candidate_id).count() == 0
        assert db.query(Document).filter_by(id=book_id).count() == 0
        assert not storage.exists(storage_reference)
    finally:
        db.rollback()
        try:
            _purge_structured_content(db, book_id)
        except Exception:
            db.rollback()
        db.query(ProcessingRun).filter_by(processing_run_id=processing_run_id).delete(synchronize_session=False)
        db.query(IngestionDispatch).filter_by(id=dispatch_id).delete(synchronize_session=False)
        db.query(SourceFile).filter_by(id=source_id).delete(synchronize_session=False)
        db.query(Document).filter_by(id=book_id).delete(synchronize_session=False)
        db.commit()
        db.close()
