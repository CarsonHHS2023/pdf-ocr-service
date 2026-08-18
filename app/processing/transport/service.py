"""In-memory provider-independent source transport grant service."""
from __future__ import annotations

import hashlib
import math
import re
import secrets
import threading
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Callable, Mapping, Any

from app.processing.transport.errors import (
    ExpiredGrant,
    GrantNotFound,
    InvalidGrantInput,
    InvalidToken,
    RetrievalLimitExceeded,
    RevokedGrant,
    UnsafeMetadata,
)
from app.processing.transport.models import (
    AuthorizedTransportGrant,
    StoredTransportGrant,
    TransportGrantCreationResult,
    TransportGrantDescriptor,
    TransportGrantPolicy,
    TransportGrantState,
)
from app.storage.models import StorageReference

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,}$")
_UNSAFE_METADATA_KEYS = {
    "token",
    "secret",
    "authorization",
    "auth",
    "bearer",
    "bearer_token",
    "signed_url",
    "source_url",
    "download_url",
    "local_path",
    "path",
    "headers",
    "request_headers",
    "cookie",
    "cookies",
    "query",
    "query_string",
    "credential",
    "credentials",
    "password",
    "api_key",
    "x_api_key",
    "x_amz_signature",
}
Clock = Callable[[], datetime]


@dataclass(frozen=True)
class TransportGrantServicePolicy:
    default_ttl: timedelta = timedelta(minutes=20)
    maximum_ttl: timedelta = timedelta(hours=1)
    default_max_source_bytes: int = 100 * 1024 * 1024
    default_max_retrieval_count: int | None = None
    cleanup_batch_limit: int = 100
    token_entropy_bytes: int = 32


class InMemoryTransportGrantService:
    """Process-local grant registry; no Storage, database, route, or provider access."""

    def __init__(self, *, policy: TransportGrantServicePolicy | None = None, clock: Clock | None = None) -> None:
        self._policy = policy or TransportGrantServicePolicy()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self._by_digest: dict[str, StoredTransportGrant] = {}
        self._digest_by_id: dict[str, str] = {}
        self._validate_policy()

    def create_grant(
        self,
        *,
        storage_reference: StorageReference,
        atlas_attempt_id: str,
        document_id: str,
        source_file_id: str,
        source_sha256: str,
        source_byte_size: int,
        media_type: str,
        ttl: timedelta | None = None,
        source_etag: str | None = None,
        filename: str | None = None,
        provider_job_id: str | None = None,
        correlation_id: str | None = None,
        max_retrieval_count: int | None = None,
        safe_metadata: Mapping[str, Any] | None = None,
        **forbidden: Any,
    ) -> TransportGrantCreationResult:
        self._reject_forbidden(forbidden)
        self._validate_create(storage_reference, atlas_attempt_id, document_id, source_file_id, source_sha256, source_byte_size, media_type, ttl, max_retrieval_count, safe_metadata)
        now = self._now()
        effective_ttl = self._policy.default_ttl if ttl is None else ttl
        expires_at = now + effective_ttl
        token = secrets.token_urlsafe(self._policy.token_entropy_bytes)
        digest = self._digest(token)
        grant_id = f"tg_{uuid.uuid4().hex}"
        policy = TransportGrantPolicy(
            replay_allowed=True,
            max_retrieval_count=max_retrieval_count if max_retrieval_count is not None else self._policy.default_max_retrieval_count,
            max_source_bytes=self._policy.default_max_source_bytes,
            safe_metadata=safe_metadata or {},
        )
        record = StoredTransportGrant(
            grant_id=grant_id, token_digest=digest, storage_reference=storage_reference,
            atlas_attempt_id=atlas_attempt_id, document_id=document_id, source_file_id=source_file_id,
            provider_job_id=provider_job_id, correlation_id=correlation_id, created_at=now, expires_at=expires_at,
            revoked_at=None, first_retrieved_at=None, last_retrieved_at=None, retrieval_count=0,
            source_sha256=source_sha256.lower(), source_etag=source_etag, media_type=media_type,
            source_byte_size=source_byte_size, filename=filename, policy=policy,
        )
        with self._lock:
            self._by_digest[digest] = record
            self._digest_by_id[grant_id] = digest
        return TransportGrantCreationResult(descriptor=self._descriptor(record, now), token=token)

    def authorize(self, token: str) -> AuthorizedTransportGrant:
        record = self._authorized_record(token)
        return self._authorized_descriptor(record)

    def record_retrieval(self, token: str) -> AuthorizedTransportGrant:
        """Atomically authorize and count one successful retrieval completion."""
        if not self._valid_token_text(token):
            raise InvalidToken()
        digest = self._digest(token)
        with self._lock:
            record = self._by_digest.get(digest)
            if record is None or not secrets.compare_digest(record.token_digest, digest):
                raise GrantNotFound()
            now = self._now()
            self._ensure_authorized(record, now)
            updated = replace(
                record,
                retrieval_count=record.retrieval_count + 1,
                first_retrieved_at=record.first_retrieved_at or now,
                last_retrieved_at=now,
            )
            self._by_digest[digest] = updated
        return self._authorized_descriptor(updated)

    def revoke(self, grant_id: str) -> TransportGrantDescriptor | None:
        if not grant_id or not grant_id.strip():
            raise InvalidGrantInput("grant_id must be non-empty")
        with self._lock:
            digest = self._digest_by_id.get(grant_id)
            if digest is None:
                return None
            record = self._by_digest[digest]
            if record.revoked_at is None:
                record = replace(record, revoked_at=self._now())
                self._by_digest[digest] = record
            return self._descriptor(record, self._now())

    def inspect(self, grant_id: str) -> TransportGrantDescriptor | None:
        with self._lock:
            digest = self._digest_by_id.get(grant_id)
            return None if digest is None else self._descriptor(self._by_digest[digest], self._now())

    def cleanup_expired(self, *, limit: int | None = None) -> list[str]:
        batch = self._policy.cleanup_batch_limit if limit is None else limit
        if batch <= 0:
            raise InvalidGrantInput("cleanup limit must be positive")
        removed: list[str] = []
        with self._lock:
            now = self._now()
            for digest, record in list(self._by_digest.items()):
                if len(removed) >= batch:
                    break
                if record.revoked_at is not None or now >= record.expires_at:
                    removed.append(record.grant_id)
                    del self._by_digest[digest]
                    self._digest_by_id.pop(record.grant_id, None)
        return removed

    def _authorized_record(self, token: str) -> StoredTransportGrant:
        if not self._valid_token_text(token):
            raise InvalidToken()
        digest = self._digest(token)
        with self._lock:
            record = self._by_digest.get(digest)
            if record is None or not secrets.compare_digest(record.token_digest, digest):
                raise GrantNotFound()
            self._ensure_authorized(record, self._now())
            return record

    def _ensure_authorized(self, record: StoredTransportGrant, now: datetime) -> None:
        if record.revoked_at is not None:
            raise RevokedGrant(record.grant_id)
        if now >= record.expires_at:
            raise ExpiredGrant(record.grant_id)
        if record.source_byte_size > record.policy.max_source_bytes:
            raise InvalidGrantInput("source byte size exceeds grant policy snapshot")
        if record.policy.max_retrieval_count is not None and record.retrieval_count >= record.policy.max_retrieval_count:
            raise RetrievalLimitExceeded(record.grant_id)

    def _descriptor(self, r: StoredTransportGrant, now: datetime) -> TransportGrantDescriptor:
        state = self._state(r, now)
        return TransportGrantDescriptor(r.grant_id, r.storage_reference, r.atlas_attempt_id, r.document_id, r.source_file_id, r.provider_job_id, r.correlation_id, r.created_at, r.expires_at, r.revoked_at, r.first_retrieved_at, r.last_retrieved_at, r.retrieval_count, state, r.source_sha256, r.source_etag, r.media_type, r.source_byte_size, r.filename, r.policy)

    def _authorized_descriptor(self, r: StoredTransportGrant) -> AuthorizedTransportGrant:
        return AuthorizedTransportGrant(r.grant_id, r.storage_reference, r.atlas_attempt_id, r.document_id, r.source_file_id, r.provider_job_id, r.correlation_id, r.expires_at, r.source_sha256, r.source_etag, r.media_type, r.source_byte_size, r.policy)

    def _state(self, r: StoredTransportGrant, now: datetime) -> TransportGrantState:
        if r.revoked_at is not None:
            return TransportGrantState.REVOKED
        if now >= r.expires_at:
            return TransportGrantState.EXPIRED
        if r.policy.max_retrieval_count is not None and r.retrieval_count >= r.policy.max_retrieval_count:
            return TransportGrantState.EXHAUSTED
        return TransportGrantState.ACTIVE

    def _validate_policy(self) -> None:
        if self._policy.default_ttl <= timedelta(0) or self._policy.maximum_ttl <= timedelta(0):
            raise InvalidGrantInput("TTL policy must be positive")
        if self._policy.default_ttl > self._policy.maximum_ttl:
            raise InvalidGrantInput("default TTL cannot exceed maximum TTL")
        if (
            not isinstance(self._policy.default_max_source_bytes, int)
            or self._policy.default_max_source_bytes < 0
            or not isinstance(self._policy.cleanup_batch_limit, int)
            or self._policy.cleanup_batch_limit <= 0
            or not isinstance(self._policy.token_entropy_bytes, int)
            or self._policy.token_entropy_bytes < 32
        ):
            raise InvalidGrantInput("invalid transport grant policy")
        if self._policy.default_max_retrieval_count is not None and (
            not isinstance(self._policy.default_max_retrieval_count, int)
            or self._policy.default_max_retrieval_count <= 0
        ):
            raise InvalidGrantInput("default_max_retrieval_count must be positive")

    def _validate_create(self, storage_reference: StorageReference, *args: Any) -> None:
        atlas_attempt_id, document_id, source_file_id, source_sha256, source_byte_size, media_type, ttl, max_retrieval_count, safe_metadata = args
        if not isinstance(storage_reference, StorageReference):
            raise InvalidGrantInput("storage_reference must be a StorageReference")
        for name, value in (("atlas_attempt_id", atlas_attempt_id), ("document_id", document_id), ("source_file_id", source_file_id)):
            if not isinstance(value, str) or not value.strip():
                raise InvalidGrantInput(f"{name} must be non-empty")
        if not isinstance(source_sha256, str) or not _SHA256_RE.fullmatch(source_sha256):
            raise InvalidGrantInput("source_sha256 must be a 64-character hex SHA-256")
        if not isinstance(source_byte_size, int) or source_byte_size < 0:
            raise InvalidGrantInput("source_byte_size must be non-negative")
        if source_byte_size > self._policy.default_max_source_bytes:
            raise InvalidGrantInput("source_byte_size exceeds configured limit")
        if not isinstance(media_type, str) or not media_type.strip():
            raise InvalidGrantInput("media_type must be non-empty")
        effective_ttl = self._policy.default_ttl if ttl is None else ttl
        if not isinstance(effective_ttl, timedelta) or effective_ttl <= timedelta(0) or effective_ttl > self._policy.maximum_ttl or not math.isfinite(effective_ttl.total_seconds()):
            raise InvalidGrantInput("ttl must be positive, finite, and within maximum_ttl")
        if max_retrieval_count is not None and (not isinstance(max_retrieval_count, int) or max_retrieval_count <= 0):
            raise InvalidGrantInput("max_retrieval_count must be positive")
        self._reject_unsafe_metadata(safe_metadata or {})

    def _reject_forbidden(self, values: Mapping[str, Any]) -> None:
        for key in values:
            normalized = key.lower()
            if any(part in normalized for part in ("token", "url", "path", "header", "cookie")):
                raise InvalidGrantInput(f"caller-supplied {key} is not accepted")
        if values:
            raise InvalidGrantInput("unexpected grant input")

    def _reject_unsafe_metadata(self, metadata: Mapping[str, Any]) -> None:
        def walk(value: Any) -> str | None:
            if isinstance(value, Mapping):
                for key, child in value.items():
                    normalized = str(key).lower().replace("-", "_").replace(" ", "_")
                    if normalized in _UNSAFE_METADATA_KEYS:
                        return str(key)
                    found = walk(child)
                    if found:
                        return found
            elif isinstance(value, (list, tuple, set, frozenset)):
                for child in value:
                    found = walk(child)
                    if found:
                        return found
            return None
        found = walk(metadata)
        if found:
            raise UnsafeMetadata(f"unsafe metadata key is not allowed: {found}")

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise InvalidGrantInput("clock must return timezone-aware UTC datetimes")
        return now.astimezone(timezone.utc)

    def _valid_token_text(self, token: str) -> bool:
        return isinstance(token, str) and bool(_TOKEN_RE.fullmatch(token.strip()))

    def _digest(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()
