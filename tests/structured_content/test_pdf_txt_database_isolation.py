from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Document, ProcessingRun, SourceFile
import app.models_v2  # noqa: F401
import app.models_v2_selection  # noqa: F401
from app.processing.pdf_canonicalization import PdfCanonicalizationService
from app.processing.raw_result import (
    RawProcessingResultEnvelope,
    RawResultEvidenceSource,
    RawResultIdentity,
    RawResultIngestionMetadata,
    RawResultProviderProvenance,
    RawResultSourceProvenance,
)
from app.processing.txt.canonicalization import (
    RetainedTxtCanonicalizationRequest,
    TxtCanonicalizationService,
)
from app.processing.txt.structure_recovery import (
    TxtLineStructureAssignment,
    TxtStructureKind,
    TxtStructureWindowResult,
)
from app.storage.local import LocalStorageProvider
from app.storage.models import StorageReference
from app.structured_content_v2.model import normalize_candidate_v2
from app.structured_content_v2.repository import StructuredContentCandidateV2Repository
from app.structured_content_v2.selection import StructuredContentV2SelectionRepository


PDF_RESULT_FIXTURE = Path("tests/fixtures/providers/paddle_vl_api/result_page_mapping_multi_range.json")


class _TxtAnalyzer:
    def analyze(self, window):
        assignments = []
        first_nonempty = next((line.line_id for line in window.lines if not line.is_empty), None)
        for line in window.lines:
            if line.is_empty:
                continue
            if line.line_id == first_nonempty:
                kind, level = TxtStructureKind.TITLE, None
            else:
                kind, level = TxtStructureKind.PARAGRAPH, None
            assignments.append(
                TxtLineStructureAssignment(
                    line.line_id,
                    kind,
                    True,
                    level,
                )
            )
        return TxtStructureWindowResult(window.window_id, tuple(assignments))


def _database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)


def _add_pdf_document(factory, document_id: str, source_id: str, checksum: str) -> None:
    with factory.begin() as session:
        session.add(Document(id=document_id, title=document_id, file_type="pdf", status="processing"))
        session.add(
            SourceFile(
                id=source_id,
                document_id=document_id,
                original_filename=f"{document_id}.pdf",
                file_type="pdf",
                mime_type="application/pdf",
                byte_size=100,
                checksum_sha256=checksum,
                storage_reference=f"src_{hashlib.sha256(source_id.encode()).hexdigest()[:32]}",
                retained=1,
                is_primary=1,
            )
        )


def _add_txt_document(factory, storage, document_id: str, source_id: str, text: str) -> None:
    raw = text.encode("utf-8")
    checksum = hashlib.sha256(raw).hexdigest()
    ref = StorageReference.parse(f"src_{hashlib.sha256(source_id.encode()).hexdigest()[:32]}")
    storage.put(raw, ref, expected_size=len(raw), expected_sha256=checksum)
    with factory.begin() as session:
        session.add(Document(id=document_id, title=document_id, file_type="txt", status="processing"))
        session.add(
            SourceFile(
                id=source_id,
                document_id=document_id,
                original_filename=f"{document_id}.txt",
                file_type="txt",
                mime_type="text/plain",
                byte_size=len(raw),
                checksum_sha256=checksum,
                storage_reference=str(ref),
                retained=1,
                is_primary=1,
            )
        )


def _pdf_envelope(storage, *, document_id: str, source_id: str, attempt: str, source_sha: str):
    payload = json.loads(PDF_RESULT_FIXTURE.read_text(encoding="utf-8"))
    documents = payload if isinstance(payload, list) else payload.get("documents")
    if isinstance(documents, list):
        for document in documents:
            if isinstance(document, dict):
                document["document_id"] = document_id
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ref = StorageReference.parse(f"src_{hashlib.sha256((attempt + '-raw').encode()).hexdigest()[:32]}")
    put = storage.put(raw, ref, expected_size=len(raw), expected_sha256=hashlib.sha256(raw).hexdigest())
    return RawProcessingResultEnvelope(
        identity=RawResultIdentity(
            atlas_attempt_id=attempt,
            atlas_correlation_id=f"corr-{attempt}",
            document_id=document_id,
            source_file_id=source_id,
            provider_name="paddle-vl",
            provider_job_id=f"job-{attempt}",
            provider_request_id=f"request-{attempt}",
            provider_result_profile="standard",
            provider_result_status="completed",
        ),
        source=RawResultSourceProvenance(
            source_checksum_sha256=source_sha,
            source_media_type="application/pdf",
        ),
        provider=RawResultProviderProvenance(build_tag="isolation-fixture"),
        ingestion=RawResultIngestionMetadata(
            ingested_at=datetime.now(timezone.utc),
            payload_media_type="application/json",
            payload_encoding="utf-8",
            payload_compression=None,
            payload_size_bytes=put.byte_size,
            payload_sha256=put.checksum_sha256,
            storage_reference=put.reference,
            evidence_source=RawResultEvidenceSource.INLINE_JSON,
        ),
    )


def _snapshot(factory, document_id: str) -> dict:
    candidates = StructuredContentCandidateV2Repository()
    selections = StructuredContentV2SelectionRepository(candidates)
    with factory() as session:
        document = session.get(Document, document_id)
        assert document is not None
        sources = session.execute(
            select(SourceFile).where(SourceFile.document_id == document_id).order_by(SourceFile.id)
        ).scalars().all()
        runs = session.execute(
            select(ProcessingRun).where(ProcessingRun.document_id == document_id).order_by(ProcessingRun.processing_run_id)
        ).scalars().all()
        candidate_summaries = candidates.list_candidates_for_document(session, document_id)
        full_candidates = tuple(
            candidates.get_candidate(session, summary.candidate_id)
            for summary in candidate_summaries
        )
        selection = selections.get_selection(session, document_id)
        return {
            "document": (
                document.id,
                document.file_type,
                document.title,
                document.status,
                document.error_message,
            ),
            "sources": tuple(
                (
                    row.id,
                    row.file_type,
                    row.original_filename,
                    row.byte_size,
                    row.checksum_sha256,
                    row.storage_reference,
                    row.retained,
                    row.is_primary,
                )
                for row in sources
            ),
            "runs": tuple(
                (
                    row.processing_run_id,
                    row.source_file_id,
                    row.status,
                    row.raw_result_ref,
                    row.structured_processing_result_ref,
                )
                for row in runs
            ),
            "candidates": tuple(
                sorted(
                    (
                        item.candidate_id,
                        json.dumps(
                            normalize_candidate_v2(item),
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    )
                    for item in full_candidates
                )
            ),
            "selection": (
                selection.candidate_id,
                selection.selection_version,
                selection.selection_actor_ref,
            ),
        }


def test_pdf_txt_pdf_txt_canonicalization_preserves_existing_documents(tmp_path) -> None:
    """Alternating canonical ingestion must never mutate another document aggregate."""
    engine, factory = _database()
    storage = LocalStorageProvider(tmp_path)
    pdf_service = PdfCanonicalizationService(storage=storage, session_factory=factory)
    txt_service = TxtCanonicalizationService(
        storage=storage,
        session_factory=factory,
        analyzer=_TxtAnalyzer(),
    )

    pdf_a_sha = "a" * 64
    pdf_b_sha = "b" * 64

    try:
        # 1) PDF A becomes canonical and selected.
        _add_pdf_document(factory, "pdf-a", "pdf-a-source", pdf_a_sha)
        pdf_a = pdf_service.canonicalize(
            _pdf_envelope(
                storage,
                document_id="pdf-a",
                source_id="pdf-a-source",
                attempt="pdf-a-run",
                source_sha=pdf_a_sha,
            )
        )
        assert pdf_a.selected_candidate_id == pdf_a.candidate_id
        pdf_a_snapshot = _snapshot(factory, "pdf-a")

        # 2) TXT A canonicalization must leave PDF A byte-for-byte equivalent at the ORM boundary.
        _add_txt_document(factory, storage, "txt-a", "txt-a-source", "TXT A\nFirst paragraph.\nSecond paragraph.\n")
        txt_a = txt_service.canonicalize(
            RetainedTxtCanonicalizationRequest(
                document_ref="txt-a",
                source_file_ref="txt-a-source",
                processing_run_ref="txt-a-run",
            )
        )
        assert txt_a.selected_candidate_id == txt_a.candidate_id
        assert _snapshot(factory, "pdf-a") == pdf_a_snapshot
        txt_a_snapshot = _snapshot(factory, "txt-a")

        # 3) PDF B canonicalization must leave both earlier PDF and TXT aggregates unchanged.
        _add_pdf_document(factory, "pdf-b", "pdf-b-source", pdf_b_sha)
        pdf_b = pdf_service.canonicalize(
            _pdf_envelope(
                storage,
                document_id="pdf-b",
                source_id="pdf-b-source",
                attempt="pdf-b-run",
                source_sha=pdf_b_sha,
            )
        )
        assert pdf_b.selected_candidate_id == pdf_b.candidate_id
        assert _snapshot(factory, "pdf-a") == pdf_a_snapshot
        assert _snapshot(factory, "txt-a") == txt_a_snapshot
        pdf_b_snapshot = _snapshot(factory, "pdf-b")

        # 4) TXT B canonicalization must preserve all three previously canonical documents.
        _add_txt_document(factory, storage, "txt-b", "txt-b-source", "TXT B\nAnother paragraph.\nFinal paragraph.\n")
        txt_b = txt_service.canonicalize(
            RetainedTxtCanonicalizationRequest(
                document_ref="txt-b",
                source_file_ref="txt-b-source",
                processing_run_ref="txt-b-run",
            )
        )
        assert txt_b.selected_candidate_id == txt_b.candidate_id
        assert _snapshot(factory, "pdf-a") == pdf_a_snapshot
        assert _snapshot(factory, "txt-a") == txt_a_snapshot
        assert _snapshot(factory, "pdf-b") == pdf_b_snapshot

        txt_b_snapshot = _snapshot(factory, "txt-b")
        assert txt_b_snapshot["document"][1] == "txt"
        assert pdf_a_snapshot["document"][1] == "pdf"
        assert pdf_b_snapshot["document"][1] == "pdf"
    finally:
        engine.dispose()
