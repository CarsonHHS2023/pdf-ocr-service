from __future__ import annotations

import ast
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Document, ProcessingRun, SourceFile
import app.models_v2  # noqa: F401
import app.models_v2_selection  # noqa: F401
from app.processing.pdf_canonicalization import (
    PdfCanonicalizationError,
    PdfCanonicalizationService,
    PdfSelectionDisposition,
)
from app.processing.raw_result import (
    RawProcessingResultEnvelope,
    RawResultArtifactMetadata,
    RawResultEvidenceSource,
    RawResultIdentity,
    RawResultIngestionMetadata,
    RawResultProviderProvenance,
    RawResultSourceProvenance,
)
from app.storage.local import LocalStorageProvider
from app.storage.models import StorageReference
from app.structured_content_v2.repository import StructuredContentCandidateV2Repository
from app.structured_content_v2.selection import StructuredContentV2SelectionRepository


FIXTURE = Path("tests/fixtures/providers/paddle_vl_api/result_page_mapping_multi_range.json")
SOURCE_SHA = "a" * 64


def _db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory.begin() as session:
        session.add(Document(id="document_fixture_001", title="Fixture", file_type="pdf", status="processing"))
        session.add(
            SourceFile(
                id="source-file-001",
                document_id="document_fixture_001",
                original_filename="fixture.pdf",
                file_type="pdf",
                mime_type="application/pdf",
                byte_size=100,
                checksum_sha256=SOURCE_SHA,
                storage_reference="src_" + "1" * 32,
                retained=1,
            )
        )
    return engine, factory


def _payload_bytes() -> bytes:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _envelope(storage, *, attempt="attempt-001", compressed=False, raw_bytes: bytes | None = None):
    plain = raw_bytes if raw_bytes is not None else _payload_bytes()
    stored = gzip.compress(plain) if compressed else plain
    ref = StorageReference.parse("src_" + hashlib.sha256((attempt + ("-gz" if compressed else "-json")).encode()).hexdigest()[:32])
    put = storage.put(stored, ref, expected_size=len(stored), expected_sha256=hashlib.sha256(stored).hexdigest())
    artifact = None
    evidence_source = RawResultEvidenceSource.INLINE_JSON
    payload_media_type = "application/json"
    compression = None
    if compressed:
        evidence_source = RawResultEvidenceSource.ARTIFACT_BYTES
        payload_media_type = "application/octet-stream"
        compression = "gzip"
        artifact = RawResultArtifactMetadata(
            artifact_id="artifact-001",
            media_type="application/json",
            compression="gzip",
            size_bytes=len(stored),
            checksum_sha256=put.checksum_sha256,
        )
    return RawProcessingResultEnvelope(
        identity=RawResultIdentity(
            atlas_attempt_id=attempt,
            atlas_correlation_id="corr-001",
            document_id="document_fixture_001",
            source_file_id="source-file-001",
            provider_name="paddle-vl",
            provider_job_id="job-001",
            provider_request_id="request-001",
            provider_result_profile="standard",
            provider_result_status="completed",
        ),
        source=RawResultSourceProvenance(
            source_checksum_sha256=SOURCE_SHA,
            source_media_type="application/pdf",
        ),
        provider=RawResultProviderProvenance(build_tag="fixture-build"),
        ingestion=RawResultIngestionMetadata(
            ingested_at=datetime.now(timezone.utc),
            payload_media_type=payload_media_type,
            payload_encoding="utf-8" if not compressed else None,
            payload_compression=compression,
            payload_size_bytes=put.byte_size,
            payload_sha256=put.checksum_sha256,
            storage_reference=put.reference,
            evidence_source=evidence_source,
            artifact_metadata=artifact,
        ),
    )


def test_retained_pdf_becomes_persisted_candidate_spr_and_initial_explicit_selection(tmp_path) -> None:
    engine, factory = _db()
    storage = LocalStorageProvider(tmp_path)
    service = PdfCanonicalizationService(storage=storage, session_factory=factory)
    envelope = _envelope(storage)
    try:
        outcome = service.canonicalize(envelope)

        assert outcome.document_ref == "document_fixture_001"
        assert outcome.processing_run_ref == "attempt-001"
        assert outcome.selection_disposition is PdfSelectionDisposition.CREATED
        assert outcome.initial_selection_created is True
        assert outcome.selected_candidate_id == outcome.candidate_id
        assert outcome.selection_version == 1
        assert storage.exists(outcome.structured_processing_result_ref)

        spr_bytes = storage.get(outcome.structured_processing_result_ref)
        spr_payload = json.loads(spr_bytes.decode("utf-8"))
        assert spr_payload["schema_version"] == 2
        assert [unit["kind"] for unit in spr_payload["source_units"]] == ["physical_page"] * 3
        assert [node["text"] for node in spr_payload["nodes"]][:2] == [
            "# Fixture page 1\n\nHello page one.",
            "Fixture page 2 text.",
        ]

        with factory() as session:
            run = session.execute(select(ProcessingRun).where(ProcessingRun.processing_run_id == "attempt-001")).scalar_one()
            assert run.status == "succeeded"
            assert run.raw_result_ref == outcome.raw_result_ref
            assert run.structured_processing_result_ref == outcome.structured_processing_result_ref
            candidate = StructuredContentCandidateV2Repository().get_candidate(session, outcome.candidate_id)
            assert candidate.document_ref == "document_fixture_001"
            assert candidate.processing_run_ref == "attempt-001"
            selection = StructuredContentV2SelectionRepository().get_selection(session, "document_fixture_001")
            assert selection.candidate_id == outcome.candidate_id
            assert selection.selection_actor_ref == "atlas.pdf-ingestion-v2"
    finally:
        engine.dispose()


def test_retry_is_idempotent_and_reuses_deterministic_spr_reference(tmp_path) -> None:
    engine, factory = _db()
    storage = LocalStorageProvider(tmp_path)
    service = PdfCanonicalizationService(storage=storage, session_factory=factory)
    envelope = _envelope(storage)
    try:
        first = service.canonicalize(envelope)
        second = service.canonicalize(envelope)
        assert second.candidate_id == first.candidate_id
        assert second.structured_processing_result_ref == first.structured_processing_result_ref
        assert second.selected_candidate_id == first.selected_candidate_id
        assert second.selection_disposition is PdfSelectionDisposition.UNCHANGED
        assert second.initial_selection_created is False
        assert second.selection_version == 1
    finally:
        engine.dispose()


def test_later_processing_run_promotes_system_owned_selection(tmp_path) -> None:
    engine, factory = _db()
    storage = LocalStorageProvider(tmp_path)
    service = PdfCanonicalizationService(storage=storage, session_factory=factory)
    try:
        first = service.canonicalize(_envelope(storage, attempt="attempt-001"))
        later = service.canonicalize(_envelope(storage, attempt="attempt-002"))

        assert later.candidate_id != first.candidate_id
        assert later.selection_disposition is PdfSelectionDisposition.PROMOTED
        assert later.initial_selection_created is False
        assert later.selected_candidate_id == later.candidate_id
        assert later.selection_version == 2
        with factory() as session:
            candidates = StructuredContentCandidateV2Repository().list_candidates_for_document(session, "document_fixture_001")
            assert {item.candidate_id for item in candidates} == {first.candidate_id, later.candidate_id}
            selection = StructuredContentV2SelectionRepository().get_selection(session, "document_fixture_001")
            assert selection.candidate_id == later.candidate_id
            assert selection.selection_actor_ref == "atlas.pdf-reprocessing-v2"
    finally:
        engine.dispose()


def test_later_processing_run_preserves_user_owned_selection(tmp_path) -> None:
    engine, factory = _db()
    storage = LocalStorageProvider(tmp_path)
    service = PdfCanonicalizationService(storage=storage, session_factory=factory)
    selections = StructuredContentV2SelectionRepository()
    try:
        first = service.canonicalize(_envelope(storage, attempt="attempt-001"))
        with factory.begin() as session:
            manual = selections.set_selection(
                session,
                document_ref="document_fixture_001",
                candidate_id=first.candidate_id,
                expected_version=first.selection_version,
                selection_actor_ref="user:test-user",
                reason="manual Reader candidate choice",
            )
        assert manual.selection_version == 2

        later = service.canonicalize(_envelope(storage, attempt="attempt-002"))

        assert later.candidate_id != first.candidate_id
        assert later.selection_disposition is PdfSelectionDisposition.PRESERVED
        assert later.initial_selection_created is False
        assert later.selected_candidate_id == first.candidate_id
        assert later.selection_version == 2
        with factory() as session:
            selection = selections.get_selection(session, "document_fixture_001")
            assert selection.candidate_id == first.candidate_id
            assert selection.selection_actor_ref == "user:test-user"
    finally:
        engine.dispose()


def test_gzip_json_artifact_is_decoded_from_retained_bytes(tmp_path) -> None:
    engine, factory = _db()
    storage = LocalStorageProvider(tmp_path)
    service = PdfCanonicalizationService(storage=storage, session_factory=factory)
    try:
        outcome = service.canonicalize(_envelope(storage, compressed=True))
        assert outcome.candidate_id.startswith("scv2_pdf_")
        assert storage.exists(outcome.structured_processing_result_ref)
    finally:
        engine.dispose()


def test_checksum_mismatch_fails_closed_and_records_safe_run_failure(tmp_path) -> None:
    engine, factory = _db()
    storage = LocalStorageProvider(tmp_path)
    service = PdfCanonicalizationService(storage=storage, session_factory=factory)
    envelope = _envelope(storage)
    broken_ingestion = RawResultIngestionMetadata(
        ingested_at=envelope.ingestion.ingested_at,
        payload_media_type=envelope.ingestion.payload_media_type,
        payload_encoding=envelope.ingestion.payload_encoding,
        payload_compression=envelope.ingestion.payload_compression,
        payload_size_bytes=envelope.ingestion.payload_size_bytes,
        payload_sha256="f" * 64,
        storage_reference=envelope.ingestion.storage_reference,
        evidence_source=envelope.ingestion.evidence_source,
    )
    broken = RawProcessingResultEnvelope(envelope.identity, envelope.source, envelope.provider, broken_ingestion)
    try:
        with pytest.raises(PdfCanonicalizationError, match="checksum"):
            service.canonicalize(broken)
        assert storage.exists(envelope.ingestion.storage_reference)
        with factory() as session:
            run = session.execute(select(ProcessingRun).where(ProcessingRun.processing_run_id == "attempt-001")).scalar_one()
            assert run.status == "failed"
            assert run.safe_error_code == "pdf_canonicalization_failed"
            assert "checksum" not in (run.safe_error_summary or "")
    finally:
        engine.dispose()


def test_missing_matching_document_fails_closed(tmp_path) -> None:
    engine, factory = _db()
    storage = LocalStorageProvider(tmp_path)
    service = PdfCanonicalizationService(storage=storage, session_factory=factory)
    payload = json.loads(_payload_bytes().decode("utf-8"))
    payload["documents"][0]["document_id"] = "other-document"
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    try:
        with pytest.raises(PdfCanonicalizationError, match="exactly one matching document"):
            service.canonicalize(_envelope(storage, raw_bytes=raw))
    finally:
        engine.dispose()


class _FailingCandidateRepository(StructuredContentCandidateV2Repository):
    def create_candidate(self, session, candidate):
        raise RuntimeError("database implementation secret")


def test_candidate_persistence_failure_keeps_raw_evidence_and_marks_run_failed(tmp_path) -> None:
    engine, factory = _db()
    storage = LocalStorageProvider(tmp_path)
    envelope = _envelope(storage)
    service = PdfCanonicalizationService(
        storage=storage,
        session_factory=factory,
        candidates=_FailingCandidateRepository(),
    )
    try:
        with pytest.raises(PdfCanonicalizationError, match="retained PDF canonicalization failed"):
            service.canonicalize(envelope)
        assert storage.exists(envelope.ingestion.storage_reference)
        with factory() as session:
            run = session.execute(select(ProcessingRun).where(ProcessingRun.processing_run_id == "attempt-001")).scalar_one()
            assert run.status == "failed"
            assert run.safe_error_summary == "retained PDF canonicalization failed"
    finally:
        engine.dispose()


def test_canonicalization_path_has_no_legacy_page_or_mineru_dependencies() -> None:
    source = Path("app/processing/pdf_canonicalization.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden = (
        "app.services.page_ocr_service",
        "app.services.mineru_popo_service",
        "app.routers",
        "modal",
    )
    assert not any(name.startswith(forbidden) for name in imported)
    assert "PdfPage" not in source
    assert "MineruResult" not in source
    assert "PageOCRService" not in source
