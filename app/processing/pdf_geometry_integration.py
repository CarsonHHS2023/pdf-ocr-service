"""Integration helpers for geometry-preprocessed provider PDF input."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
from typing import Any

from app.processing.models import ArtifactMetadata, DocumentProcessingProvider
from app.processing.orchestration import ProcessingOrchestrator
from app.processing.pdf_geometry_preprocessing import GeometryPreprocessedPdf
from app.processing.pdf_opencv_quality_pipeline import (
    GEOMETRY_PREPROCESSING_VERSION,
    preprocess_pdf_geometry_opencv as preprocess_pdf_geometry,
    retain_opencv_diagnostics,
)
from app.processing.raw_result import RawResultProviderProvenance
from app.storage.base import StorageProvider
from app.storage.models import StorageReference


@dataclass(frozen=True, slots=True)
class GeometryProviderInput:
    processing_attempt_id: str
    storage_reference: StorageReference
    checksum_sha256: str
    byte_size: int
    media_type: str
    filename: str
    preprocessing: GeometryPreprocessedPdf


def prepare_geometry_provider_input(
    *,
    storage: StorageProvider,
    source_pdf_bytes: bytes,
    original_filename: str | None,
    processing_attempt_id: str,
    expected_page_count: int | None = None,
) -> GeometryProviderInput:
    """Run the isolated OpenCV experiment and retain its selected complete PDF."""
    if not isinstance(processing_attempt_id, str) or not processing_attempt_id.strip():
        raise ValueError("processing_attempt_id must be non-empty")
    processed = preprocess_pdf_geometry(
        source_pdf_bytes,
        expected_page_count=expected_page_count,
    )
    retain_opencv_diagnostics(
        source_pdf_bytes=source_pdf_bytes,
        processed=processed,
        processing_attempt_id=processing_attempt_id,
    )
    reference = _geometry_pdf_reference(
        processing_attempt_id,
        processed.checksum_sha256,
    )
    put = storage.put(
        processed.pdf_bytes,
        reference,
        expected_size=processed.byte_size,
        expected_sha256=processed.checksum_sha256,
    )
    stem = Path(original_filename or "document.pdf").stem or "document"
    return GeometryProviderInput(
        processing_attempt_id=processing_attempt_id,
        storage_reference=put.reference,
        checksum_sha256=put.checksum_sha256,
        byte_size=put.byte_size,
        media_type="application/pdf",
        filename=f"{stem}.opencv-quality-gated.pdf",
        preprocessing=processed,
    )


def _geometry_pdf_reference(
    processing_attempt_id: str,
    checksum_sha256: str,
) -> StorageReference:
    digest = hashlib.sha256(
        (
            f"atlas-{GEOMETRY_PREPROCESSING_VERSION}\x1f"
            f"{processing_attempt_id}\x1f{checksum_sha256}"
        ).encode("utf-8")
    ).hexdigest()[:32]
    return StorageReference.parse(f"src_{digest}")


class ProviderInputGrantService:
    """Serve the derived PDF while preserving original Source provenance."""

    def __init__(self, delegate: Any, provider_input: GeometryProviderInput) -> None:
        self._delegate = delegate
        self._provider_input = provider_input

    def create_grant(self, **kwargs):
        kwargs = dict(kwargs)
        kwargs.update(
            {
                "storage_reference": self._provider_input.storage_reference,
                "source_sha256": self._provider_input.checksum_sha256,
                "source_byte_size": self._provider_input.byte_size,
                "media_type": self._provider_input.media_type,
                "source_etag": None,
                "filename": self._provider_input.filename,
            }
        )
        return self._delegate.create_grant(**kwargs)

    def inspect(self, grant_id):
        return self._delegate.inspect(grant_id)

    def revoke(self, grant_id):
        return self._delegate.revoke(grant_id)


class ProviderInputChecksumProvider:
    """Send the derived PDF checksum to Modal without changing its protocol."""

    def __init__(self, delegate: DocumentProcessingProvider, provider_input: GeometryProviderInput) -> None:
        self._delegate = delegate
        self._provider_input = provider_input

    async def submit_job(self, request):
        documents = [
            replace(
                document,
                pdf_source_etag=None,
                pdf_source_sha256=self._provider_input.checksum_sha256,
            )
            for document in request.documents
        ]
        return await self._delegate.submit_job(replace(request, documents=documents))

    async def get_job_status(self, job_id: str):
        return await self._delegate.get_job_status(job_id)

    async def get_job_result(self, job_id: str, profile: str | None = None):
        return await self._delegate.get_job_result(job_id, profile)

    async def get_job_artifact(
        self,
        job_id: str,
        metadata: ArtifactMetadata | None = None,
    ):
        return await self._delegate.get_job_artifact(job_id, metadata)


class ProviderInputAwareProcessingOrchestrator(ProcessingOrchestrator):
    """Record both original Source and derived provider-input provenance."""

    def __init__(self, *, provider_input: GeometryProviderInput, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.provider_input = provider_input

    async def _ingest(self, request, result, page_summary):
        envelope = await super()._ingest(request, result, page_summary)
        configuration = _thaw_metadata(envelope.provider.configuration)
        configuration.update(
            {
                "source_checksum_sha256": request.source_checksum_sha256,
                "provider_input_kind": "geometry_preprocessed_pdf",
                "provider_input_checksum_sha256": self.provider_input.checksum_sha256,
                "provider_input_size_bytes": self.provider_input.byte_size,
                "provider_input_media_type": self.provider_input.media_type,
                "geometry_preprocessing_version": self.provider_input.preprocessing.version,
                "geometry_page_count": self.provider_input.preprocessing.page_count,
                "geometry_changed_page_count": self.provider_input.preprocessing.changed_page_count,
            }
        )
        provider = RawResultProviderProvenance(
            build_tag=envelope.provider.build_tag,
            model_version=envelope.provider.model_version,
            pipeline_version=envelope.provider.pipeline_version,
            configuration=configuration,
            capabilities=_thaw_metadata(envelope.provider.capabilities),
            timestamps=_thaw_metadata(envelope.provider.timestamps),
            warnings=tuple(_thaw_metadata(envelope.provider.warnings)),
            errors=tuple(_thaw_metadata(envelope.provider.errors)),
        )
        return replace(envelope, provider=provider)


def _thaw_metadata(value: Any) -> Any:
    """Return ordinary containers from recursively frozen provenance metadata."""
    if isinstance(value, Mapping):
        return {key: _thaw_metadata(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return tuple(_thaw_metadata(child) for child in value)
    if isinstance(value, frozenset):
        return set(_thaw_metadata(child) for child in value)
    return value


__all__ = [
    "GeometryProviderInput",
    "ProviderInputAwareProcessingOrchestrator",
    "ProviderInputChecksumProvider",
    "ProviderInputGrantService",
    "prepare_geometry_provider_input",
]
