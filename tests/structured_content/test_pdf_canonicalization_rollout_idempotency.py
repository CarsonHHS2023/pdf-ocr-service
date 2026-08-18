from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models_v2  # noqa: F401
import app.models_v2_selection  # noqa: F401
import app.processing.pdf_canonicalization as pdf_canonicalization
from app.models import Base, Document, SourceFile
from app.processing.pdf_canonicalization import PdfCanonicalizationService
from app.processing.raw_result import (
    RawProcessingResultEnvelope,
    RawResultEvidenceSource,
    RawResultIdentity,
    RawResultIngestionMetadata,
    RawResultProviderProvenance,
    RawResultSourceProvenance,
)
from app.storage.local import LocalStorageProvider
from app.storage.models import StorageReference


FIXTURE = Path("tests/fixtures/providers/paddle_vl_api/result_page_mapping_multi_range.json")
SOURCE_SHA = "a" * 64


def _database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory.begin() as session:
        session.add(
            Document(
                id="document_fixture_001",
                title="Fixture",
                file_type="pdf",
                status="processing",
            )
        )
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


def _envelope(storage: LocalStorageProvider) -> RawProcessingResultEnvelope:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    reference = StorageReference.parse(
        "src_" + hashlib.sha256(b"rollout-idempotency").hexdigest()[:32]
    )
    put = storage.put(
        raw,
        reference,
        expected_size=len(raw),
        expected_sha256=hashlib.sha256(raw).hexdigest(),
    )
    return RawProcessingResultEnvelope(
        identity=RawResultIdentity(
            atlas_attempt_id="attempt-001",
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
            payload_media_type="application/json",
            payload_encoding="utf-8",
            payload_compression=None,
            payload_size_bytes=put.byte_size,
            payload_sha256=put.checksum_sha256,
            storage_reference=put.reference,
            evidence_source=RawResultEvidenceSource.INLINE_JSON,
        ),
    )


def test_replay_reuses_persisted_candidate_before_rollout_sensitive_transforms(
    tmp_path,
    monkeypatch,
) -> None:
    engine, factory = _database()
    storage = LocalStorageProvider(tmp_path)
    service = PdfCanonicalizationService(
        storage=storage,
        session_factory=factory,
        structure_refiner_factory=None,
    )
    envelope = _envelope(storage)

    try:
        first = service.canonicalize(envelope)

        def fail_if_rebuilt(*args, **kwargs):
            raise AssertionError("persisted candidate must be reused on replay")

        monkeypatch.setattr(
            pdf_canonicalization,
            "transform_spr_v2_to_candidate",
            fail_if_rebuilt,
        )
        monkeypatch.setattr(
            pdf_canonicalization,
            "enrich_candidate_with_pdf_visual_assets",
            fail_if_rebuilt,
        )

        replay = service.canonicalize(envelope)

        assert replay.candidate_id == first.candidate_id
        assert replay.selected_candidate_id == first.selected_candidate_id
        assert replay.structured_processing_result_ref == first.structured_processing_result_ref
        assert replay.selection_version == first.selection_version == 1
        assert replay.initial_selection_created is False
    finally:
        engine.dispose()
