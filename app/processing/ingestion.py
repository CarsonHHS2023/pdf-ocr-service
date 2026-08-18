"""Raw processing result ingestion service."""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from app.processing.models import ProcessingPageIdentity
from app.processing.raw_result import (
    RawProcessingResultEnvelope,
    RawResultArtifactMetadata,
    RawResultEvidenceSource,
    RawResultIdentity,
    RawResultIngestionMetadata,
    RawResultPageSummary,
    RawResultProviderProvenance,
    RawResultSourceProvenance,
    is_valid_sha256,
    unsafe_metadata_keys,
    utc_now,
)
from app.storage.base import StorageProvider
from app.storage.errors import IntegrityMismatch, ObjectAlreadyExists, StorageError
from app.storage.models import PutResult, StorageReference


class RawResultIngestionError(Exception):
    """Base class for safe raw-result ingestion failures."""


class InvalidEnvelopeInput(RawResultIngestionError):
    pass


class RawResultSerializationError(RawResultIngestionError):
    pass


class ProviderMetadataMismatch(RawResultIngestionError):
    pass


class RawResultChecksumMismatch(ProviderMetadataMismatch):
    pass


class RawResultSizeMismatch(ProviderMetadataMismatch):
    pass


class RawResultStorageWriteError(RawResultIngestionError):
    pass


class RawResultStorageConflict(RawResultStorageWriteError):
    pass


class UnsafeMetadataError(InvalidEnvelopeInput):
    pass


def canonicalize_inline_json(payload: Any) -> bytes:
    """Return compact UTF-8 JSON with stable keys and no ASCII escaping."""
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise RawResultSerializationError("inline provider result is not JSON serializable") from exc


def summarize_pages(
    identities: list[ProcessingPageIdentity] | tuple[ProcessingPageIdentity, ...],
    *,
    expected_pages_total: int | None = None,
    mapping_valid: bool = True,
) -> RawResultPageSummary:
    numbers = [identity.page_number for identity in identities]
    duplicates = tuple(sorted({number for number in numbers if numbers.count(number) > 1}))
    ranges = tuple(sorted({identity.source_page_range for identity in identities}))
    if expected_pages_total is not None:
        expected = set(range(1, expected_pages_total + 1))
        missing = tuple(sorted(expected - set(numbers)))
    else:
        missing = ()
    return RawResultPageSummary(
        page_count_observed=len(identities),
        first_source_page=min(numbers) if numbers else None,
        last_source_page=max(numbers) if numbers else None,
        missing_pages=missing,
        duplicate_pages=duplicates,
        mapping_valid=mapping_valid and not duplicates and not missing,
        source_ranges_represented=ranges,
    )


def ingest_inline_result(
    *,
    storage: StorageProvider,
    identity: RawResultIdentity,
    source: RawResultSourceProvenance,
    provider: RawResultProviderProvenance | None,
    inline_result: Any,
    payload_media_type: str = "application/json",
    payload_encoding: str | None = "utf-8",
    page_summary: RawResultPageSummary | None = None,
    existing_storage_reference: StorageReference | str | None = None,
    ingested_at=None,
) -> RawProcessingResultEnvelope:
    _validate_common(identity, source, provider or RawResultProviderProvenance())
    _validate_single_evidence_source(inline_result=inline_result, artifact_bytes=None)
    payload_copy = copy.deepcopy(inline_result)
    payload_bytes = canonicalize_inline_json(payload_copy)
    return _persist(
        storage=storage,
        identity=identity,
        source=source,
        provider=provider or RawResultProviderProvenance(),
        payload=payload_bytes,
        media_type=payload_media_type,
        encoding=payload_encoding,
        compression=None,
        evidence_source=RawResultEvidenceSource.INLINE_JSON,
        artifact_metadata=None,
        page_summary=page_summary,
        existing_storage_reference=existing_storage_reference,
        ingested_at=ingested_at,
    )


def ingest_artifact_result(
    *,
    storage: StorageProvider,
    identity: RawResultIdentity,
    source: RawResultSourceProvenance,
    provider: RawResultProviderProvenance | None,
    artifact_bytes: bytes,
    artifact_metadata: RawResultArtifactMetadata | None = None,
    page_summary: RawResultPageSummary | None = None,
    existing_storage_reference: StorageReference | str | None = None,
    ingested_at=None,
) -> RawProcessingResultEnvelope:
    provider = provider or RawResultProviderProvenance()
    artifact_metadata = artifact_metadata or RawResultArtifactMetadata()
    _validate_common(identity, source, provider)
    _validate_artifact_metadata(artifact_metadata)
    _validate_single_evidence_source(inline_result=None, artifact_bytes=artifact_bytes)
    if not isinstance(artifact_bytes, bytes):
        raise InvalidEnvelopeInput("artifact bytes payload must be bytes")
    actual_size = len(artifact_bytes)
    actual_sha = hashlib.sha256(artifact_bytes).hexdigest()
    if artifact_metadata.size_bytes is not None and artifact_metadata.size_bytes != actual_size:
        raise RawResultSizeMismatch(_safe_message(identity, f"artifact size mismatch expected={artifact_metadata.size_bytes} actual={actual_size}"))
    if artifact_metadata.checksum_sha256 is not None and artifact_metadata.checksum_sha256.lower() != actual_sha:
        raise RawResultChecksumMismatch(_safe_message(identity, f"artifact checksum mismatch expected={artifact_metadata.checksum_sha256.lower()} actual={actual_sha}"))
    return _persist(
        storage=storage,
        identity=identity,
        source=source,
        provider=provider,
        payload=artifact_bytes,
        media_type=artifact_metadata.media_type or "application/octet-stream",
        encoding=artifact_metadata.encoding,
        compression=artifact_metadata.compression,
        evidence_source=RawResultEvidenceSource.ARTIFACT_BYTES,
        artifact_metadata=artifact_metadata,
        page_summary=page_summary,
        existing_storage_reference=existing_storage_reference,
        ingested_at=ingested_at,
    )


def _validate_single_evidence_source(*, inline_result: Any | None, artifact_bytes: bytes | None) -> None:
    has_inline = inline_result is not None
    has_artifact = artifact_bytes is not None
    if has_inline == has_artifact:
        raise InvalidEnvelopeInput("exactly one raw result evidence source is required")


def _persist(**kwargs) -> RawProcessingResultEnvelope:
    payload: bytes = kwargs["payload"]
    identity: RawResultIdentity = kwargs["identity"]
    actual_size = len(payload)
    actual_sha = hashlib.sha256(payload).hexdigest()
    try:
        put_result = kwargs["storage"].put(payload, kwargs["existing_storage_reference"], expected_size=actual_size, expected_sha256=actual_sha)
    except ObjectAlreadyExists as exc:
        raise RawResultStorageConflict(_safe_message(identity, "storage reference already exists with different bytes")) from exc
    except IntegrityMismatch as exc:
        raise ProviderMetadataMismatch(_safe_message(identity, "storage integrity mismatch")) from exc
    except StorageError as exc:
        raise RawResultStorageWriteError(_safe_message(identity, "storage write failed")) from exc
    except Exception as exc:
        raise RawResultStorageWriteError(_safe_message(identity, "storage write failed")) from exc
    _validate_put_result(identity, put_result, actual_size, actual_sha, kwargs["existing_storage_reference"])
    ingestion = RawResultIngestionMetadata(
        ingested_at=kwargs["ingested_at"] or utc_now(),
        payload_media_type=kwargs["media_type"],
        payload_encoding=kwargs["encoding"],
        payload_compression=kwargs["compression"],
        payload_size_bytes=put_result.byte_size,
        payload_sha256=put_result.checksum_sha256,
        storage_reference=put_result.reference,
        evidence_source=kwargs["evidence_source"],
        artifact_metadata=kwargs["artifact_metadata"],
        page_summary=kwargs["page_summary"],
    )
    return RawProcessingResultEnvelope(kwargs["identity"], kwargs["source"], kwargs["provider"], ingestion)


def _validate_put_result(
    identity: RawResultIdentity,
    put_result: PutResult,
    actual_size: int,
    actual_sha: str,
    requested_reference: StorageReference | str | None,
) -> None:
    try:
        reference = put_result.reference
        byte_size = put_result.byte_size
        checksum_sha256 = put_result.checksum_sha256
    except Exception as exc:
        raise RawResultStorageWriteError(_safe_message(identity, "storage returned malformed write result")) from exc
    if requested_reference is not None and str(reference) != str(requested_reference):
        raise RawResultStorageWriteError(_safe_message(identity, "storage returned unexpected reference"))
    if byte_size != actual_size:
        raise RawResultStorageWriteError(_safe_message(identity, f"storage returned unexpected size expected={actual_size} actual={byte_size}"))
    if checksum_sha256 != actual_sha:
        raise RawResultStorageWriteError(_safe_message(identity, f"storage returned unexpected checksum expected={actual_sha} actual={checksum_sha256}"))


def _validate_common(identity: RawResultIdentity, source: RawResultSourceProvenance, provider: RawResultProviderProvenance) -> None:
    required = {
        "atlas_attempt_id": identity.atlas_attempt_id,
        "document_id": identity.document_id,
        "source_file_id": identity.source_file_id,
        "provider_name": identity.provider_name,
        "provider_job_id": identity.provider_job_id,
    }
    missing = [name for name, value in required.items() if not isinstance(value, str) or not value.strip()]
    if missing:
        raise InvalidEnvelopeInput(f"missing required raw result identity field(s): {', '.join(missing)}")
    for name, value in {
        "atlas_correlation_id": identity.atlas_correlation_id,
        "provider_request_id": identity.provider_request_id,
        "provider_result_profile": identity.provider_result_profile,
        "provider_result_status": identity.provider_result_status,
    }.items():
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise InvalidEnvelopeInput(f"{name} cannot be blank when supplied")
    if not is_valid_sha256(source.source_checksum_sha256):
        raise InvalidEnvelopeInput("source checksum must be a SHA-256 hex digest")
    for mapping in (provider.configuration, provider.capabilities):
        keys = unsafe_metadata_keys(mapping)
        if keys:
            raise UnsafeMetadataError(f"unsafe provider metadata key(s): {', '.join(sorted(keys))}")


def _validate_artifact_metadata(metadata: RawResultArtifactMetadata) -> None:
    if metadata.size_bytes is not None and metadata.size_bytes < 0:
        raise InvalidEnvelopeInput("artifact size must be non-negative")
    if metadata.checksum_sha256 is not None and not is_valid_sha256(metadata.checksum_sha256):
        raise InvalidEnvelopeInput("artifact checksum must be a SHA-256 hex digest")
    keys = unsafe_metadata_keys(metadata.provider_metadata)
    if keys:
        raise UnsafeMetadataError(f"unsafe artifact metadata key(s): {', '.join(sorted(keys))}")


def _safe_message(identity: RawResultIdentity, detail: str) -> str:
    return f"{detail}; atlas_attempt_id={identity.atlas_attempt_id}; provider_name={identity.provider_name}; provider_job_id={identity.provider_job_id}"
