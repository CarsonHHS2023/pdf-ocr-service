from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json

import fitz
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Document, SourceFile
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
from app.storage.local import LocalStorageProvider
from app.storage.models import StorageReference
from app.structured_content_v2.model import AssetRecoveryStateV2
from app.structured_content_v2.repository import StructuredContentCandidateV2Repository


def _pdf_bytes() -> bytes:
    document = fitz.open()
    try:
        page = document.new_page(width=200, height=200)
        page.draw_rect(fitz.Rect(40, 50, 160, 150), color=(0, 0, 0), fill=(0.8, 0.8, 0.8))
        return document.tobytes()
    finally:
        document.close()


def _raw_result_bytes(document_id: str) -> bytes:
    payload = {
        "documents": [
            {
                "document_id": document_id,
                "raw_result": [
                    {
                        "page_number": 1,
                        "page_index": 0,
                        "width": 200,
                        "height": 200,
                        "blocks": [
                            {
                                "type": "figure",
                                "bbox": [40, 50, 160, 150],
                                "order": 0,
                                "text": "Test figure",
                            }
                        ],
                    }
                ],
            }
        ]
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def test_canonicalization_persists_available_png_rendition_for_figure(tmp_path) -> None:
    document_id = "document-visual"
    source_file_id = "source-visual"
    attempt_id = "attempt-visual"
    pdf = _pdf_bytes()
    pdf_sha = hashlib.sha256(pdf).hexdigest()

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    storage = LocalStorageProvider(tmp_path)

    source_put = storage.put(
        pdf,
        StorageReference.parse("src_" + "1" * 32),
        expected_size=len(pdf),
        expected_sha256=pdf_sha,
    )
    raw = _raw_result_bytes(document_id)
    raw_sha = hashlib.sha256(raw).hexdigest()
    raw_put = storage.put(
        raw,
        StorageReference.parse("src_" + "2" * 32),
        expected_size=len(raw),
        expected_sha256=raw_sha,
    )

    with factory.begin() as session:
        session.add(Document(id=document_id, title="Visual", file_type="pdf", status="processing"))
        session.add(
            SourceFile(
                id=source_file_id,
                document_id=document_id,
                original_filename="visual.pdf",
                file_type="pdf",
                mime_type="application/pdf",
                byte_size=source_put.byte_size,
                checksum_sha256=source_put.checksum_sha256,
                storage_reference=str(source_put.reference),
                retained=1,
                is_primary=1,
            )
        )

    envelope = RawProcessingResultEnvelope(
        identity=RawResultIdentity(
            atlas_attempt_id=attempt_id,
            atlas_correlation_id="correlation-visual",
            document_id=document_id,
            source_file_id=source_file_id,
            provider_name="paddle-vl",
            provider_job_id="job-visual",
            provider_request_id="request-visual",
            provider_result_profile="standard",
            provider_result_status="completed",
        ),
        source=RawResultSourceProvenance(
            source_checksum_sha256=pdf_sha,
            source_media_type="application/pdf",
        ),
        provider=RawResultProviderProvenance(build_tag="visual-test"),
        ingestion=RawResultIngestionMetadata(
            ingested_at=datetime.now(timezone.utc),
            payload_media_type="application/json",
            payload_encoding="utf-8",
            payload_compression=None,
            payload_size_bytes=raw_put.byte_size,
            payload_sha256=raw_put.checksum_sha256,
            storage_reference=raw_put.reference,
            evidence_source=RawResultEvidenceSource.INLINE_JSON,
        ),
    )

    try:
        outcome = PdfCanonicalizationService(storage=storage, session_factory=factory).canonicalize(envelope)
        with factory() as session:
            candidate = StructuredContentCandidateV2Repository().get_candidate(session, outcome.candidate_id)

        figure = next(node for node in candidate.nodes if node.node_type.value == "figure")
        assert len(figure.asset_ids) == 1
        asset = next(item for item in candidate.assets if item.asset_id == figure.asset_ids[0])
        assert asset.recovery_state is AssetRecoveryStateV2.AVAILABLE
        assert len(asset.rendition_ids) == 1

        rendition = next(item for item in candidate.renditions if item.rendition_id == asset.rendition_ids[0])
        assert rendition.recovery_state is AssetRecoveryStateV2.AVAILABLE
        assert rendition.media_type == "image/png"
        assert storage.exists(rendition.artifact_ref)
        png = storage.get(rendition.artifact_ref)
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
    finally:
        engine.dispose()
