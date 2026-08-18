"""Value models for provider-independent source transport grants."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from app.storage.models import StorageReference


class TransportGrantState(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    EXHAUSTED = "exhausted"


@dataclass(frozen=True)
class TransportGrantPolicy:
    replay_allowed: bool = True
    max_retrieval_count: int | None = None
    max_source_bytes: int = 100 * 1024 * 1024
    safe_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "safe_metadata", _freeze(copy.deepcopy(self.safe_metadata)))


@dataclass(frozen=True)
class TransportGrantDescriptor:
    grant_id: str
    storage_reference: StorageReference
    atlas_attempt_id: str
    document_id: str
    source_file_id: str
    provider_job_id: str | None
    correlation_id: str | None
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    first_retrieved_at: datetime | None
    last_retrieved_at: datetime | None
    retrieval_count: int
    state: TransportGrantState
    source_sha256: str
    source_etag: str | None
    media_type: str
    source_byte_size: int
    filename: str | None
    policy: TransportGrantPolicy


@dataclass(frozen=True)
class AuthorizedTransportGrant:
    grant_id: str
    storage_reference: StorageReference
    atlas_attempt_id: str
    document_id: str
    source_file_id: str
    provider_job_id: str | None
    correlation_id: str | None
    expires_at: datetime
    source_sha256: str
    source_etag: str | None
    media_type: str
    source_byte_size: int
    policy: TransportGrantPolicy


@dataclass(frozen=True, repr=False)
class TransportGrantCreationResult:
    descriptor: TransportGrantDescriptor
    token: str

    def __repr__(self) -> str:
        return f"TransportGrantCreationResult(descriptor={self.descriptor!r}, token=<redacted>)"


@dataclass(frozen=True, repr=False)
class StoredTransportGrant:
    grant_id: str
    token_digest: str
    storage_reference: StorageReference
    atlas_attempt_id: str
    document_id: str
    source_file_id: str
    provider_job_id: str | None
    correlation_id: str | None
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    first_retrieved_at: datetime | None
    last_retrieved_at: datetime | None
    retrieval_count: int
    source_sha256: str
    source_etag: str | None
    media_type: str
    source_byte_size: int
    filename: str | None
    policy: TransportGrantPolicy

    def __repr__(self) -> str:
        return f"StoredTransportGrant(grant_id={self.grant_id!r}, state_fields_redacted=True)"


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(child) for key, child in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(child) for child in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze(child) for child in value)
    return value
