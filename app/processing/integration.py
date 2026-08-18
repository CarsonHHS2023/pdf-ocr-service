"""End-to-end processing integration coordinator."""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from typing import Any
from urllib.parse import quote, urlparse, urlunparse

from app.config import Settings, settings as default_settings
from app.processing.models import ProviderLifecycleStatus
from app.processing.orchestration import (
    OrchestrationError,
    OrchestrationErrorCategory,
    OrchestrationOutcome,
    OrchestrationPhase,
    OrchestrationRequest,
    PollingPolicy,
    ProcessingOrchestrator,
)
from app.processing.pdf_canonicalization import (
    PdfCanonicalizationError,
    PdfCanonicalizationOutcome,
    PdfCanonicalizationService,
)
from app.processing.raw_result import RawProcessingResultEnvelope, is_valid_sha256
from app.processing.transport.models import TransportGrantDescriptor, TransportGrantState
from app.processing.transport.service import InMemoryTransportGrantService
from app.storage.models import StorageReference

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,}$")
_CONTROL_OR_WHITESPACE_RE = re.compile(r"[\x00-\x20\x7f]")


class IntegrationErrorCategory(str, Enum):
    INVALID_RETAINED_SOURCE = "invalid_retained_source"
    INVALID_PUBLIC_ORIGIN = "missing_or_invalid_public_origin"
    GRANT_CREATION_FAILURE = "grant_creation_failure"
    URL_CONSTRUCTION_FAILURE = "url_construction_failure"
    ORCHESTRATION_FAILURE = "orchestration_failure"
    CANONICALIZATION_FAILURE = "canonicalization_failure"
    SUBMISSION_UNCERTAIN = "submission_uncertain"
    TIMEOUT = "timeout"
    CLEANUP_WARNING = "cleanup_revocation_warning"
    UNEXPECTED = "unexpected_integration_failure"


@dataclass(frozen=True)
class IntegrationError(Exception):
    category: IntegrationErrorCategory
    safe_message: str
    orchestration_error: OrchestrationError | None = field(default=None, repr=False)
    warnings: tuple[str, ...] = ()
    grant_id: str | None = None
    grant_final_state: TransportGrantState | None = None
    revocation_succeeded: bool | None = None

    def __str__(self) -> str:
        return f"{self.category.value}: {self.safe_message}"


@dataclass(frozen=True)
class TrustedPublicSourceOrigin:
    origin: str = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "origin", validate_public_source_origin(self.origin))

    def __repr__(self) -> str:
        parsed = urlparse(self.origin)
        return f"TrustedPublicSourceOrigin(origin='https://{parsed.hostname}/')"


@dataclass(frozen=True, repr=False)
class TemporarySourceTransportUrl:
    url: str

    def __repr__(self) -> str:
        return "TemporarySourceTransportUrl(url=<redacted>)"


@dataclass(frozen=True)
class RetainedSourceDescriptor:
    document_id: str
    source_file_id: str
    storage_reference: StorageReference
    retained: bool
    sha256: str
    byte_size: int
    media_type: str
    etag: str | None = None
    filename: str | None = None

    def validate(self) -> None:
        for name in ("document_id", "source_file_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise IntegrationError(IntegrationErrorCategory.INVALID_RETAINED_SOURCE, f"{name} is required")
        if not self.retained:
            raise IntegrationError(IntegrationErrorCategory.INVALID_RETAINED_SOURCE, "source must be retained")
        if not isinstance(self.storage_reference, StorageReference):
            raise IntegrationError(IntegrationErrorCategory.INVALID_RETAINED_SOURCE, "storage reference is required")
        if not is_valid_sha256(self.sha256):
            raise IntegrationError(IntegrationErrorCategory.INVALID_RETAINED_SOURCE, "source checksum must be a SHA-256 hex digest")
        if not isinstance(self.byte_size, int) or isinstance(self.byte_size, bool) or self.byte_size < 0:
            raise IntegrationError(IntegrationErrorCategory.INVALID_RETAINED_SOURCE, "source byte size must be non-negative")
        if self.media_type != "application/pdf":
            raise IntegrationError(IntegrationErrorCategory.INVALID_RETAINED_SOURCE, "only application/pdf sources are supported")


@dataclass(frozen=True)
class ProcessingIntegrationRequest:
    processing_attempt_id: str
    correlation_id: str | None
    retained_source: RetainedSourceDescriptor
    provider_name: str = "paddle-vl"
    provider_job_id: str = "paddle-vl-redacted-0000"
    provider_request_id: str | None = None
    result_profile: str = "standard"
    provider_job_options: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class ProcessingIntegrationOutcome:
    document_id: str
    source_file_id: str
    provider_name: str
    provider_job_id: str
    provider_request_id: str | None
    integration_terminal_phase: OrchestrationPhase
    provider_terminal_status: ProviderLifecycleStatus | None
    orchestration_outcome: OrchestrationOutcome | None = field(repr=False)
    raw_result: RawProcessingResultEnvelope | None = field(repr=False)
    raw_result_storage_reference: StorageReference | None
    raw_result_checksum_sha256: str | None
    raw_result_size_bytes: int | None
    elapsed_seconds: float
    poll_count: int
    warnings: tuple[str, ...]
    grant_id: str
    grant_final_state: TransportGrantState | None
    revocation_succeeded: bool
    error: IntegrationError | None = field(default=None, repr=False)
    canonicalization: PdfCanonicalizationOutcome | None = field(default=None, repr=False)


@dataclass(frozen=True)
class _FinalGrantState:
    descriptor: TransportGrantDescriptor | None
    revoked: bool


def validate_public_source_origin(value: str | None) -> str:
    if value is None or not isinstance(value, str) or not value.strip():
        raise IntegrationError(IntegrationErrorCategory.INVALID_PUBLIC_ORIGIN, "public source transport origin is required")
    if value != value.strip() or _CONTROL_OR_WHITESPACE_RE.search(value):
        raise IntegrationError(IntegrationErrorCategory.INVALID_PUBLIC_ORIGIN, "public source transport origin must not include whitespace or control characters")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise IntegrationError(IntegrationErrorCategory.INVALID_PUBLIC_ORIGIN, "public source transport origin must be HTTPS with a host")
    if parsed.username or parsed.password:
        raise IntegrationError(IntegrationErrorCategory.INVALID_PUBLIC_ORIGIN, "public source transport origin must not include userinfo")
    if parsed.query:
        raise IntegrationError(IntegrationErrorCategory.INVALID_PUBLIC_ORIGIN, "public source transport origin must not include query")
    if parsed.fragment:
        raise IntegrationError(IntegrationErrorCategory.INVALID_PUBLIC_ORIGIN, "public source transport origin must not include fragment")
    if parsed.path not in ("", "/"):
        raise IntegrationError(IntegrationErrorCategory.INVALID_PUBLIC_ORIGIN, "public source transport origin must not include a path")
    return urlunparse(("https", parsed.netloc, "/", "", "", ""))


def build_temporary_source_transport_url(origin: TrustedPublicSourceOrigin | str, token: str) -> TemporarySourceTransportUrl:
    if not _TOKEN_RE.fullmatch(token or ""):
        raise IntegrationError(IntegrationErrorCategory.URL_CONSTRUCTION_FAILURE, "transport token is malformed")
    normalized = origin.origin if isinstance(origin, TrustedPublicSourceOrigin) else validate_public_source_origin(origin)
    return TemporarySourceTransportUrl(normalized.rstrip("/") + "/internal/source-transport/" + quote(token, safe=""))


class EndToEndProcessingIntegrationService:
    def __init__(
        self,
        *,
        grant_service: InMemoryTransportGrantService,
        orchestrator: ProcessingOrchestrator,
        canonicalizer: PdfCanonicalizationService | None = None,
        public_origin: str | None = None,
        app_settings: Settings | None = None,
        monotonic: Any | None = None,
        polling_policy: PollingPolicy | None = None,
    ) -> None:
        self.grant_service = grant_service
        self.orchestrator = orchestrator
        self.canonicalizer = canonicalizer
        self._origin_value = public_origin if public_origin is not None else (app_settings or default_settings).public_source_transport_origin
        self.monotonic = monotonic or time.monotonic
        self.polling_policy = polling_policy or PollingPolicy(
            timeout_seconds=300,
            initial_interval_seconds=2,
            max_interval_seconds=10,
            backoff_factor=1.5,
        )

    async def process(self, request: ProcessingIntegrationRequest) -> ProcessingIntegrationOutcome:
        start = self.monotonic()
        warnings: list[str] = []
        request.retained_source.validate()
        origin = TrustedPublicSourceOrigin(self._origin_value)
        try:
            created = self.grant_service.create_grant(
                storage_reference=request.retained_source.storage_reference,
                atlas_attempt_id=request.processing_attempt_id,
                document_id=request.retained_source.document_id,
                source_file_id=request.retained_source.source_file_id,
                source_sha256=request.retained_source.sha256,
                source_byte_size=request.retained_source.byte_size,
                media_type=request.retained_source.media_type,
                ttl=timedelta(minutes=20),
                source_etag=request.retained_source.etag,
                filename=request.retained_source.filename,
                provider_job_id=request.provider_job_id,
                correlation_id=request.correlation_id,
            )
            grant = created.descriptor
        except Exception as exc:
            raise IntegrationError(IntegrationErrorCategory.GRANT_CREATION_FAILURE, "transport grant creation failed") from exc

        try:
            transport_url = build_temporary_source_transport_url(origin, created.token)
        except IntegrationError as exc:
            final = self._finalize(grant.grant_id, revoke=True, warnings=warnings)
            raise IntegrationError(
                exc.category,
                exc.safe_message,
                warnings=tuple(warnings),
                grant_id=grant.grant_id,
                grant_final_state=_state(final.descriptor),
                revocation_succeeded=final.revoked,
            ) from None

        try:
            orch_req = OrchestrationRequest(
                request.processing_attempt_id,
                request.correlation_id,
                request.retained_source.document_id,
                request.retained_source.source_file_id,
                transport_url.url,
                request.retained_source.sha256,
                request.retained_source.media_type,
                request.provider_name,
                request.provider_job_id,
                request.provider_request_id,
                request.result_profile,
                dict(request.provider_job_options),
                request.retained_source.etag,
            )
            out = await self.orchestrator.run_once(orch_req, self.polling_policy)
            revoke = _should_revoke_outcome(out)
            final = self._finalize(grant.grant_id, revoke=revoke, warnings=warnings)
            integration_error = _integration_error_for_outcome(out, tuple(warnings), grant.grant_id, final)
            canonicalization: PdfCanonicalizationOutcome | None = None
            if integration_error is None and out.succeeded and out.raw_result is not None and self.canonicalizer is not None:
                try:
                    canonicalize_async = getattr(self.canonicalizer, "canonicalize_async", None)
                    if callable(canonicalize_async):
                        canonicalization = await canonicalize_async(out.raw_result)
                    else:
                        canonicalization = await asyncio.to_thread(
                            self.canonicalizer.canonicalize,
                            out.raw_result,
                        )
                except PdfCanonicalizationError:
                    integration_error = IntegrationError(
                        IntegrationErrorCategory.CANONICALIZATION_FAILURE,
                        "retained raw result could not be canonicalized",
                        warnings=tuple(warnings),
                        grant_id=grant.grant_id,
                        grant_final_state=_state(final.descriptor),
                        revocation_succeeded=final.revoked,
                    )
            return _make_outcome(
                request,
                out,
                grant,
                final,
                tuple(warnings),
                self.monotonic() - start,
                integration_error,
                canonicalization,
            )
        except OrchestrationError as exc:
            category = _category_for_orchestration_error(exc)
            revoke = category not in {IntegrationErrorCategory.SUBMISSION_UNCERTAIN, IntegrationErrorCategory.TIMEOUT}
            final = self._finalize(grant.grant_id, revoke=revoke, warnings=warnings)
            raise IntegrationError(
                category,
                exc.safe_message,
                exc,
                tuple(warnings),
                grant.grant_id,
                _state(final.descriptor),
                final.revoked,
            ) from None
        except IntegrationError:
            raise
        except Exception:
            final = self._finalize(grant.grant_id, revoke=True, warnings=warnings)
            raise IntegrationError(
                IntegrationErrorCategory.UNEXPECTED,
                "unexpected integration failure",
                warnings=tuple(warnings),
                grant_id=grant.grant_id,
                grant_final_state=_state(final.descriptor),
                revocation_succeeded=final.revoked,
            ) from None

    def _finalize(self, grant_id: str, *, revoke: bool, warnings: list[str]) -> _FinalGrantState:
        if not revoke:
            return _FinalGrantState(self.grant_service.inspect(grant_id), False)
        try:
            return _FinalGrantState(self.grant_service.revoke(grant_id), True)
        except Exception:
            warnings.append("transport grant revocation failed; grant remains expiry-managed")
            return _FinalGrantState(self.grant_service.inspect(grant_id), False)


def _category_for_orchestration_error(exc: OrchestrationError) -> IntegrationErrorCategory:
    if exc.category == OrchestrationErrorCategory.SUBMISSION_UNCERTAIN:
        return IntegrationErrorCategory.SUBMISSION_UNCERTAIN
    if exc.category == OrchestrationErrorCategory.TIMEOUT:
        return IntegrationErrorCategory.TIMEOUT
    return IntegrationErrorCategory.ORCHESTRATION_FAILURE


def _should_revoke_outcome(out: OrchestrationOutcome) -> bool:
    if out.error and out.error.category in {OrchestrationErrorCategory.TIMEOUT, OrchestrationErrorCategory.SUBMISSION_UNCERTAIN}:
        return False
    return True


def _integration_error_for_outcome(
    out: OrchestrationOutcome,
    warnings: tuple[str, ...],
    grant_id: str,
    final: _FinalGrantState,
) -> IntegrationError | None:
    if out.error is None:
        return None
    return IntegrationError(
        _category_for_orchestration_error(out.error),
        out.error.safe_message,
        out.error,
        warnings,
        grant_id,
        _state(final.descriptor),
        final.revoked,
    )


def _make_outcome(req, out, grant, final, warnings, elapsed, err, canonicalization=None):
    raw = out.raw_result
    ingestion = raw.ingestion if raw else None
    return ProcessingIntegrationOutcome(
        req.retained_source.document_id,
        req.retained_source.source_file_id,
        req.provider_name,
        out.provider_job_id,
        out.provider_request_id,
        out.final_phase,
        out.provider_terminal_status,
        out,
        raw,
        ingestion.storage_reference if ingestion else None,
        ingestion.payload_sha256 if ingestion else None,
        ingestion.payload_size_bytes if ingestion else None,
        elapsed,
        out.poll_count,
        tuple(warnings) + tuple(map(str, out.warnings)),
        grant.grant_id,
        _state(final.descriptor),
        final.revoked,
        err,
        canonicalization,
    )


def _state(descriptor: TransportGrantDescriptor | None) -> TransportGrantState | None:
    return descriptor.state if descriptor else None
