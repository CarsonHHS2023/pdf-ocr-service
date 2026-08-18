from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import fitz  # type: ignore[import]
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Document, ProcessingRun, SourceFile
import app.models_v2  # noqa: F401
import app.models_v2_selection  # noqa: F401
from app.processing.integration import (
    EndToEndProcessingIntegrationService,
    ProcessingIntegrationRequest,
    RetainedSourceDescriptor,
)
from app.processing.llm_structure_refinement import (
    RefinementOperationKind,
    StructureRefinementOperation,
    StructureRefinementPatch,
)
from app.processing.models import ProviderLifecycleStatus
from app.processing.orchestration import OrchestrationOutcome, OrchestrationPhase
from app.processing.pdf_canonicalization import PdfCanonicalizationService
from app.processing.raw_result import (
    RawProcessingResultEnvelope,
    RawResultEvidenceSource,
    RawResultIdentity,
    RawResultIngestionMetadata,
    RawResultProviderProvenance,
    RawResultSourceProvenance,
)
from app.processing.transport.service import InMemoryTransportGrantService
from app.storage.local import LocalStorageProvider
from app.storage.models import StorageReference
from app.structured_content_v2.repository import StructuredContentCandidateV2Repository


FIXTURE = Path("tests/fixtures/providers/paddle_vl_api/result_page_mapping_multi_range.json")
DOCUMENT_ID = "document_fixture_001"
SOURCE_FILE_ID = "source-file-001"
ATTEMPT_ID = "attempt-modal-llm-001"
SOURCE_REFERENCE = StorageReference.parse("src_" + "1" * 32)
RAW_REFERENCE = StorageReference.parse("src_" + "2" * 32)


def _source_pdf() -> bytes:
    document = fitz.open()
    try:
        for page_number in range(1, 4):
            page = document.new_page(width=600, height=800)
            page.insert_text((72, 72), f"Fixture page {page_number}", fontsize=18)
            page.insert_text((72, 120), f"Body text on page {page_number}.", fontsize=12)
        return document.tobytes()
    finally:
        document.close()


def _database(pdf_bytes: bytes):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    checksum = hashlib.sha256(pdf_bytes).hexdigest()
    with factory.begin() as session:
        session.add(Document(id=DOCUMENT_ID, title="Fixture", file_type="pdf", status="processing"))
        session.add(
            SourceFile(
                id=SOURCE_FILE_ID,
                document_id=DOCUMENT_ID,
                original_filename="fixture.pdf",
                file_type="pdf",
                mime_type="application/pdf",
                byte_size=len(pdf_bytes),
                checksum_sha256=checksum,
                storage_reference=str(SOURCE_REFERENCE),
                retained=1,
            )
        )
    return engine, factory


def _retained_modal_result(storage: LocalStorageProvider, source_sha256: str) -> RawProcessingResultEnvelope:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw_bytes = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    put = storage.put(
        raw_bytes,
        RAW_REFERENCE,
        expected_size=len(raw_bytes),
        expected_sha256=hashlib.sha256(raw_bytes).hexdigest(),
    )
    return RawProcessingResultEnvelope(
        identity=RawResultIdentity(
            atlas_attempt_id=ATTEMPT_ID,
            atlas_correlation_id="corr-modal-llm-001",
            document_id=DOCUMENT_ID,
            source_file_id=SOURCE_FILE_ID,
            provider_name="paddle-vl",
            provider_job_id="modal-job-001",
            provider_request_id="modal-request-001",
            provider_result_profile="standard",
            provider_result_status="completed",
        ),
        source=RawResultSourceProvenance(
            source_checksum_sha256=source_sha256,
            source_media_type="application/pdf",
        ),
        provider=RawResultProviderProvenance(build_tag="modal-fixture-build"),
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


class _CompletedModalOrchestrator:
    def __init__(self, raw_result: RawProcessingResultEnvelope) -> None:
        self.raw_result = raw_result
        self.calls = 0

    async def run_once(self, request, policy=None):
        self.calls += 1
        return OrchestrationOutcome(
            ATTEMPT_ID,
            "corr-modal-llm-001",
            DOCUMENT_ID,
            SOURCE_FILE_ID,
            "paddle-vl",
            "modal-job-001",
            "modal-request-001",
            OrchestrationPhase.RAW_RESULT_RETAINED,
            ProviderLifecycleStatus.PROVIDER_COMPLETED,
            1.0,
            1,
            None,
            self.raw_result,
        )


@dataclass
class _WarningRefiner:
    calls: int = 0

    def propose(self, spr):
        self.calls += 1
        target = next(node for node in spr.nodes if node.text)
        return StructureRefinementPatch(
            model_id="integration-test-llm",
            operations=(
                StructureRefinementOperation(
                    kind=RefinementOperationKind.ADD_WARNING,
                    node_id=target.node_id,
                    confidence=0.99,
                    reason_codes=("full_chain_test",),
                    warning="reviewed after Modal OCR",
                ),
            ),
        )


class _FailingRefiner:
    def __init__(self) -> None:
        self.calls = 0

    def propose(self, spr):
        self.calls += 1
        raise RuntimeError("simulated LLM outage with private provider detail")


def _request(pdf_bytes: bytes) -> ProcessingIntegrationRequest:
    return ProcessingIntegrationRequest(
        processing_attempt_id=ATTEMPT_ID,
        correlation_id="corr-modal-llm-001",
        retained_source=RetainedSourceDescriptor(
            document_id=DOCUMENT_ID,
            source_file_id=SOURCE_FILE_ID,
            storage_reference=SOURCE_REFERENCE,
            retained=True,
            sha256=hashlib.sha256(pdf_bytes).hexdigest(),
            byte_size=len(pdf_bytes),
            media_type="application/pdf",
            filename="fixture.pdf",
        ),
        provider_job_id="modal-job-001",
        provider_request_id="modal-request-001",
    )


def _run_chain(tmp_path, refiner):
    pdf_bytes = _source_pdf()
    engine, factory = _database(pdf_bytes)
    storage = LocalStorageProvider(tmp_path)
    storage.put(
        pdf_bytes,
        SOURCE_REFERENCE,
        expected_size=len(pdf_bytes),
        expected_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
    )
    raw_result = _retained_modal_result(storage, hashlib.sha256(pdf_bytes).hexdigest())
    orchestrator = _CompletedModalOrchestrator(raw_result)
    seen_pdf_bytes: list[bytes] = []

    def refiner_factory(retained_pdf: bytes):
        seen_pdf_bytes.append(retained_pdf)
        return refiner

    canonicalizer = PdfCanonicalizationService(
        storage=storage,
        session_factory=factory,
        structure_refiner_factory=refiner_factory,
        refinement_fail_closed=False,
    )
    service = EndToEndProcessingIntegrationService(
        grant_service=InMemoryTransportGrantService(),
        orchestrator=orchestrator,
        canonicalizer=canonicalizer,
        public_origin="https://public.example",
    )
    outcome = asyncio.run(service.process(_request(pdf_bytes)))
    return engine, factory, storage, orchestrator, seen_pdf_bytes, outcome


def test_modal_result_runs_through_llm_refinement_and_persists_final_candidate(tmp_path) -> None:
    refiner = _WarningRefiner()
    engine, factory, storage, orchestrator, seen_pdf_bytes, outcome = _run_chain(tmp_path, refiner)
    try:
        assert orchestrator.calls == 1
        assert refiner.calls == 1
        assert len(seen_pdf_bytes) == 1
        assert seen_pdf_bytes[0].startswith(b"%PDF")
        assert outcome.error is None
        assert outcome.canonicalization is not None

        spr_bytes = storage.get(outcome.canonicalization.structured_processing_result_ref)
        spr_payload = json.loads(spr_bytes.decode("utf-8"))
        refined_nodes = [
            node
            for node in spr_payload["nodes"]
            if (node.get("metadata") or {}).get("refinement_warnings")
        ]
        assert len(refined_nodes) == 1
        assert refined_nodes[0]["metadata"]["refinement_warnings"] == [
            "reviewed after Modal OCR"
        ]
        audit = refined_nodes[0]["metadata"]["llm_structure_refinement"]
        assert audit[0]["model_id"] == "integration-test-llm"
        assert audit[0]["applied"] is True

        with factory() as session:
            run = session.execute(
                select(ProcessingRun).where(ProcessingRun.processing_run_id == ATTEMPT_ID)
            ).scalar_one()
            assert run.status == "succeeded"
            assert run.structured_processing_result_ref == outcome.canonicalization.structured_processing_result_ref
            candidate = StructuredContentCandidateV2Repository().get_candidate(
                session,
                outcome.canonicalization.candidate_id,
            )
            assert candidate.processing_run_ref == ATTEMPT_ID
            assert outcome.canonicalization.selected_candidate_id == candidate.candidate_id
    finally:
        engine.dispose()


def test_llm_failure_degrades_to_modal_result_and_still_persists_candidate(tmp_path) -> None:
    refiner = _FailingRefiner()
    engine, factory, storage, orchestrator, seen_pdf_bytes, outcome = _run_chain(tmp_path, refiner)
    try:
        assert orchestrator.calls == 1
        assert refiner.calls == 1
        assert len(seen_pdf_bytes) == 1
        assert outcome.error is None
        assert outcome.canonicalization is not None

        spr_bytes = storage.get(outcome.canonicalization.structured_processing_result_ref)
        spr_payload = json.loads(spr_bytes.decode("utf-8"))
        assert all(
            "llm_structure_refinement" not in (node.get("metadata") or {})
            for node in spr_payload["nodes"]
        )

        with factory() as session:
            run = session.execute(
                select(ProcessingRun).where(ProcessingRun.processing_run_id == ATTEMPT_ID)
            ).scalar_one()
            assert run.status == "succeeded"
            assert run.safe_error_code is None
            assert "private provider detail" not in str(outcome)
            candidate = StructuredContentCandidateV2Repository().get_candidate(
                session,
                outcome.canonicalization.candidate_id,
            )
            assert candidate.document_ref == DOCUMENT_ID
    finally:
        engine.dispose()
