"""Provider-independent raw processing result envelope models."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import re
from types import MappingProxyType
from typing import Any, Mapping

from app.storage.models import StorageReference

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_UNSAFE_METADATA_KEYS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "access_token",
    "refresh_token",
    "bearer_token",
    "token",
    "auth",
    "bearer",
    "secret",
    "password",
    "api_key",
    "x-api-key",
    "signed_url",
    "artifact_url",
    "download_url",
    "source_url",
    "headers",
    "request_headers",
    "cookies",
    "cache_key",
    "path",
    "x-amz-signature",
    "x_amz_signature",
}


class RawResultEvidenceSource(str, Enum):
    INLINE_JSON = "inline_json"
    ARTIFACT_BYTES = "artifact_bytes"


@dataclass(frozen=True)
class RawResultIdentity:
    atlas_attempt_id: str
    atlas_correlation_id: str | None
    document_id: str
    source_file_id: str
    provider_name: str
    provider_job_id: str
    provider_request_id: str | None = None
    provider_result_profile: str | None = None
    provider_result_status: str | None = None


@dataclass(frozen=True)
class RawResultSourceProvenance:
    source_checksum_sha256: str
    source_etag: str | None = None
    source_media_type: str | None = None


@dataclass(frozen=True)
class RawResultProviderProvenance:
    build_tag: str | None = None
    model_version: str | None = None
    pipeline_version: str | None = None
    configuration: Mapping[str, Any] = field(default_factory=dict)
    capabilities: Mapping[str, Any] = field(default_factory=dict)
    timestamps: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[Any, ...] = ()
    errors: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "configuration", freeze_metadata(self.configuration))
        object.__setattr__(self, "capabilities", freeze_metadata(self.capabilities))
        object.__setattr__(self, "timestamps", freeze_metadata(self.timestamps))
        object.__setattr__(self, "warnings", freeze_metadata(tuple(self.warnings)))
        object.__setattr__(self, "errors", freeze_metadata(tuple(self.errors)))


@dataclass(frozen=True)
class RawResultArtifactMetadata:
    artifact_id: str | None = None
    media_type: str | None = None
    encoding: str | None = None
    compression: str | None = None
    size_bytes: int | None = None
    checksum_sha256: str | None = None
    provider_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_metadata", freeze_metadata(self.provider_metadata))


@dataclass(frozen=True)
class RawResultPageSummary:
    page_count_observed: int
    first_source_page: int | None = None
    last_source_page: int | None = None
    missing_pages: tuple[int, ...] = ()
    duplicate_pages: tuple[int, ...] = ()
    mapping_valid: bool = True
    source_ranges_represented: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class RawResultIngestionMetadata:
    ingested_at: datetime
    payload_media_type: str
    payload_encoding: str | None
    payload_compression: str | None
    payload_size_bytes: int
    payload_sha256: str
    storage_reference: StorageReference
    evidence_source: RawResultEvidenceSource
    artifact_metadata: RawResultArtifactMetadata | None = None
    page_summary: RawResultPageSummary | None = None


@dataclass(frozen=True)
class RawProcessingResultEnvelope:
    identity: RawResultIdentity
    source: RawResultSourceProvenance
    provider: RawResultProviderProvenance
    ingestion: RawResultIngestionMetadata


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def is_valid_sha256(value: str) -> bool:
    return bool(_SHA256_RE.fullmatch(value))


def freeze_metadata(value: Any) -> Any:
    """Deep-copy and freeze metadata containers used in retained envelopes."""
    copied = copy.deepcopy(value)
    return _freeze(copied)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(child) for child in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze(child) for child in value)
    return value


def unsafe_metadata_keys(value: Any) -> set[str]:
    """Find unsafe transport-secret keys in metadata containers, not raw payloads."""
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            normalized = key_text.lower().replace("-", "_")
            if key_text.lower() in _UNSAFE_METADATA_KEYS or normalized in _UNSAFE_METADATA_KEYS:
                found.add(key_text)
            found.update(unsafe_metadata_keys(child))
    elif isinstance(value, list | tuple | set | frozenset):
        for child in value:
            found.update(unsafe_metadata_keys(child))
    return found
