"""Non-persistent one-attempt processing orchestration."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
import math
import re
from types import MappingProxyType
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from app.processing.errors import ProviderClientError, ProviderErrorCategory
from app.processing.ingestion import RawResultIngestionError, ingest_artifact_result, ingest_inline_result, summarize_pages
from app.processing.models import ArtifactMetadata, DocumentProcessingProvider, ProviderJobStatus, ProviderLifecycleStatus, ProviderProgress, ProviderResult
from app.processing.raw_result import RawProcessingResultEnvelope, RawResultArtifactMetadata, RawResultIdentity, RawResultPageSummary, RawResultProviderProvenance, RawResultSourceProvenance, is_valid_sha256
from app.storage.base import StorageProvider
from app.storage.models import StorageReference

SUPPORTED_RESULT_PROFILES = {"summary", "standard", "full"}


class OrchestrationPhase(str, Enum):
    VALIDATING = "validating"
    SUBMITTING = "submitting"
    PROVIDER_QUEUED = "provider_queued"
    PROVIDER_RUNNING = "provider_running"
    PROVIDER_COMPLETED = "provider_completed"
    RETRIEVING_RESULT = "retrieving_result"
    DOWNLOADING_ARTIFACT = "downloading_artifact"
    INGESTING_RAW_RESULT = "ingesting_raw_result"
    RAW_RESULT_RETAINED = "raw_result_retained"
    PROVIDER_PARTIAL_FAILED = "provider_partial_failed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    SUBMISSION_UNCERTAIN = "submission_uncertain"


class OrchestrationErrorCategory(str, Enum):
    INVALID_INPUT = "invalid_orchestration_input"
    SUBMISSION_REJECTED = "submission_rejected"
    SUBMISSION_UNCERTAIN = "submission_outcome_uncertain"
    IDENTITY_MISMATCH = "provider_job_identity_mismatch"
    STATUS_FAILURE = "provider_status_failure"
    JOB_EXPIRED = "provider_job_expired"
    TIMEOUT = "orchestration_timeout"
    RESULT_UNAVAILABLE = "result_unavailable"
    RESULT_MALFORMED = "result_malformed"
    ARTIFACT_FAILURE = "artifact_retrieval_failure"
    INGESTION_FAILURE = "raw_result_ingestion_failure"
    PROVIDER_FAILED = "provider_execution_failure"
    UNEXPECTED = "unexpected_orchestration_failure"


@dataclass
class OrchestrationError(Exception):
    category: OrchestrationErrorCategory
    safe_message: str
    phase: OrchestrationPhase
    provider_job_id: str | None = None
    provider_status: str | None = None
    provider_error_code: str | None = None
    retryable: bool = False
    elapsed_seconds: float = 0.0
    poll_count: int = 0
    provider_request_id: str | None = None
    last_provider_progress: ProviderProgress | None = field(default=None, repr=False)
    last_successful_poll_elapsed_seconds: float | None = None

    def __str__(self) -> str:
        return f"{self.category.value}: {self.safe_message}"


@dataclass(frozen=True)
class PollingPolicy:
    timeout_seconds: float = 300.0
    initial_interval_seconds: float = 1.0
    max_interval_seconds: float = 10.0
    exponential_backoff: bool = True
    backoff_factor: float = 2.0
    max_status_requests: int | None = None
    max_result_requests: int | None = None

    def validate(self) -> None:
        for name in ("timeout_seconds", "initial_interval_seconds", "max_interval_seconds", "backoff_factor"):
            value = getattr(self, name)
            if not isinstance(value, int | float) or isinstance(value, bool) or not math.isfinite(float(value)):
                raise ValueError(f"{name} must be a finite positive number")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.initial_interval_seconds <= 0:
            raise ValueError("initial poll interval must be positive")
        if self.max_interval_seconds <= 0 or self.max_interval_seconds < self.initial_interval_seconds:
            raise ValueError("maximum poll interval must be positive and >= initial interval")
        if self.backoff_factor <= 1:
            raise ValueError("backoff_factor must be greater than 1")
        if self.max_status_requests is not None and self.max_status_requests <= 0:
            raise ValueError("max_status_requests must be positive when supplied")
        if self.max_result_requests is not None and self.max_result_requests <= 0:
            raise ValueError("max_result_requests must be positive when supplied")


@dataclass(frozen=True)
class OrchestrationRequest:
    processing_attempt_id: str
    correlation_id: str | None
    document_id: str
    source_file_id: str
    source_url: str = field(repr=False)
    source_checksum_sha256: str
    source_media_type: str
    provider_name: str
    provider_job_id: str
    provider_request_id: str | None
    result_profile: str
    provider_job_options: dict[str, Any] = field(default_factory=dict)
    source_etag: str | None = None
    expected_page_count: int | None = None
    raw_result_storage_reference: StorageReference | str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_job_options", MappingProxyType(dict(self.provider_job_options)))

    def validate(self) -> None:
        for name in ("processing_attempt_id", "document_id", "source_file_id", "source_media_type", "provider_name", "provider_job_id", "result_profile"):
            value = getattr(self, name, "")
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")
        if self.correlation_id is not None and not self.correlation_id.strip():
            raise ValueError("correlation_id cannot be blank")
        if self.provider_request_id is not None and not self.provider_request_id.strip():
            raise ValueError("provider_request_id cannot be blank")
        parsed = urlparse(self.source_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("source_url must be provider-reachable HTTPS")
        if not is_valid_sha256(self.source_checksum_sha256):
            raise ValueError("source_checksum_sha256 must be a SHA-256 hex digest")
        if self.expected_page_count is not None and self.expected_page_count < 0:
            raise ValueError("expected_page_count must be non-negative")
        if self.result_profile not in SUPPORTED_RESULT_PROFILES:
            raise ValueError("result_profile must be one of: summary, standard, full")
        _validate_provider_options(dict(self.provider_job_options))


@dataclass(frozen=True)
class OrchestrationOutcome:
    processing_attempt_id: str
    correlation_id: str | None
    document_id: str
    source_file_id: str
    provider_name: str
    provider_job_id: str
    provider_request_id: str | None
    final_phase: OrchestrationPhase
    provider_terminal_status: ProviderLifecycleStatus | None
    elapsed_seconds: float
    poll_count: int
    provider_status_snapshot: ProviderJobStatus | None
    raw_result: RawProcessingResultEnvelope | None = None
    page_summary: RawResultPageSummary | None = None
    warnings: tuple[Any, ...] = ()
    partial_failure_details: tuple[Any, ...] = ()
    error: OrchestrationError | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None and self.final_phase == OrchestrationPhase.RAW_RESULT_RETAINED and self.provider_terminal_status == ProviderLifecycleStatus.PROVIDER_COMPLETED


Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


class ProcessingOrchestrator:
    def __init__(self, *, provider: DocumentProcessingProvider, storage: StorageProvider, sleep: Sleep | None = None, monotonic: Clock | None = None) -> None:
        self.provider = provider
        self.storage = storage
        self.sleep = sleep or asyncio.sleep
        import time
        self.monotonic = monotonic or time.monotonic

    async def run_once(self, request: OrchestrationRequest, policy: PollingPolicy | None = None) -> OrchestrationOutcome:
        policy = policy or PollingPolicy()
        phase = OrchestrationPhase.VALIDATING
        start = self.monotonic(); polls = 0; snapshot: ProviderJobStatus | None = None
        try:
            request.validate(); policy.validate()
            phase = OrchestrationPhase.SUBMITTING
            submission = await self.provider.submit_job(_build_provider_request(request))
            if not submission or not submission.job_id or not submission.status:
                raise OrchestrationError(OrchestrationErrorCategory.SUBMISSION_REJECTED, "provider returned malformed accepted response", phase, request.provider_job_id)
            if submission.job_id != request.provider_job_id:
                raise OrchestrationError(OrchestrationErrorCategory.IDENTITY_MISMATCH, "provider returned a different job_id than requested", phase, request.provider_job_id)
            provider_request_id = submission.request_id or request.provider_request_id
            terminal, polls, phase, snapshot, last_poll_elapsed = await self._poll_terminal(request, policy, start, polls, submission.status)
            if terminal.status == ProviderLifecycleStatus.FAILED:
                return self._failure_outcome(request, provider_request_id, OrchestrationError(OrchestrationErrorCategory.PROVIDER_FAILED, "provider execution failed", OrchestrationPhase.FAILED, request.provider_job_id, terminal.status.value, _provider_code(terminal.error), False, self.monotonic()-start, polls, terminal.request_id, terminal.progress, last_poll_elapsed), terminal, polls, start)
            if terminal.status == ProviderLifecycleStatus.EXPIRED:
                return self._failure_outcome(request, provider_request_id, OrchestrationError(OrchestrationErrorCategory.JOB_EXPIRED, "provider job expired; a future new Atlas attempt may be required", OrchestrationPhase.FAILED, request.provider_job_id, terminal.status.value, _provider_code(terminal.error), False, self.monotonic()-start, polls, terminal.request_id, terminal.progress, last_poll_elapsed), terminal, polls, start)
            result, polls, snapshot = await self._retrieve_result(request, policy, start, polls, terminal, last_poll_elapsed)
            provider_request_id = result.request_id or provider_request_id
            if result.status == ProviderLifecycleStatus.PROVIDER_PARTIAL_FAILED and not result.raw_provider_payload and not result.documents and not result.result_artifact:
                return OrchestrationOutcome(request.processing_attempt_id, request.correlation_id, request.document_id, request.source_file_id, request.provider_name, request.provider_job_id, provider_request_id, OrchestrationPhase.PROVIDER_PARTIAL_FAILED, result.status, self.monotonic()-start, polls, snapshot, None, None, tuple(_warnings(result)), tuple(_errors(result)))
            page_summary = _page_summary(request, result)
            phase = OrchestrationPhase.DOWNLOADING_ARTIFACT if result.result_artifact else OrchestrationPhase.INGESTING_RAW_RESULT
            raw = await self._ingest(request, result, page_summary)
            final = OrchestrationPhase.RAW_RESULT_RETAINED if result.status == ProviderLifecycleStatus.PROVIDER_COMPLETED else OrchestrationPhase.PROVIDER_PARTIAL_FAILED
            return OrchestrationOutcome(request.processing_attempt_id, request.correlation_id, request.document_id, request.source_file_id, request.provider_name, request.provider_job_id, provider_request_id, final, result.status, self.monotonic()-start, polls, snapshot, raw, page_summary, tuple(_warnings(result)), tuple(_errors(result)))
        except ProviderClientError as exc:
            cat = OrchestrationErrorCategory.SUBMISSION_UNCERTAIN if phase == OrchestrationPhase.SUBMITTING and exc.detail.category in {ProviderErrorCategory.TIMEOUT, ProviderErrorCategory.UNAVAILABLE} else _map_provider_error(exc, phase)
            err_phase = OrchestrationPhase.SUBMISSION_UNCERTAIN if cat == OrchestrationErrorCategory.SUBMISSION_UNCERTAIN else phase
            message = _safe_provider_message(exc)
            if cat == OrchestrationErrorCategory.SUBMISSION_UNCERTAIN:
                message = f"{message}; submission outcome uncertain, reconcile provider job before retrying"
            raise OrchestrationError(cat, message, err_phase, request.provider_job_id, None, exc.detail.provider_code, exc.detail.retryable, _elapsed(start, self.monotonic()), polls) from exc
        except RawResultIngestionError as exc:
            return self._failure_outcome(request, request.provider_request_id, OrchestrationError(OrchestrationErrorCategory.INGESTION_FAILURE, _redact(str(exc)), OrchestrationPhase.INGESTING_RAW_RESULT, request.provider_job_id, None, None, False, _elapsed(start, self.monotonic()), polls), snapshot, polls, start)
        except ValueError as exc:
            raise OrchestrationError(OrchestrationErrorCategory.INVALID_INPUT, _redact(str(exc)), phase, request.provider_job_id if 'request' in locals() else None, elapsed_seconds=_elapsed(start, self.monotonic()), poll_count=polls) from exc

    async def _poll_terminal(self, request, policy, start, polls, submission_status):
        interval = policy.initial_interval_seconds
        snapshot: ProviderJobStatus | None = None
        last_poll_elapsed: float | None = None
        phase = _phase_for_status(submission_status)
        while True:
            now = self.monotonic()
            _check_deadline(
                policy,
                start,
                now,
                polls,
                provider_job_id=request.provider_job_id,
                snapshot=snapshot,
                last_successful_poll_elapsed_seconds=last_poll_elapsed,
            )
            if policy.max_status_requests is not None and polls >= policy.max_status_requests:
                raise _timeout_error(
                    "maximum provider status requests reached",
                    request.provider_job_id,
                    snapshot,
                    _elapsed(start, now),
                    polls,
                    last_poll_elapsed,
                )
            try:
                status = await self.provider.get_job_status(request.provider_job_id)
            except ProviderClientError as exc:
                raise _provider_client_error_with_snapshot(
                    exc,
                    phase,
                    request.provider_job_id,
                    snapshot,
                    _elapsed(start, self.monotonic()),
                    polls,
                    last_poll_elapsed,
                ) from exc
            polls += 1
            snapshot = status
            last_poll_elapsed = _elapsed(start, self.monotonic())
            phase = _phase_for_status(status.status)
            if status.status in {ProviderLifecycleStatus.PROVIDER_COMPLETED, ProviderLifecycleStatus.PROVIDER_PARTIAL_FAILED, ProviderLifecycleStatus.FAILED, ProviderLifecycleStatus.EXPIRED}:
                return status, polls, phase, status, last_poll_elapsed
            await self.sleep(_sleep_interval(interval, policy, start, self.monotonic()))
            if policy.exponential_backoff:
                interval = min(interval * policy.backoff_factor, policy.max_interval_seconds)

    async def _retrieve_result(self, request, policy, start, polls, terminal, last_poll_elapsed):
        result_requests = 0
        while True:
            now = self.monotonic()
            _check_deadline(
                policy,
                start,
                now,
                polls,
                provider_job_id=request.provider_job_id,
                snapshot=terminal,
                last_successful_poll_elapsed_seconds=last_poll_elapsed,
            )
            if policy.max_result_requests is not None and result_requests >= policy.max_result_requests:
                raise OrchestrationError(
                    OrchestrationErrorCategory.RESULT_UNAVAILABLE,
                    "maximum provider result requests reached",
                    OrchestrationPhase.RETRIEVING_RESULT,
                    request.provider_job_id,
                    terminal.status.value,
                    elapsed_seconds=_elapsed(start, now),
                    poll_count=polls,
                    provider_request_id=terminal.request_id,
                    last_provider_progress=terminal.progress,
                    last_successful_poll_elapsed_seconds=last_poll_elapsed,
                )
            try:
                result_requests += 1
                result = await self.provider.get_job_result(request.provider_job_id, request.result_profile)
            except ProviderClientError as exc:
                if exc.detail.category == ProviderErrorCategory.RESULT_NOT_READY:
                    await self.sleep(_sleep_interval(policy.initial_interval_seconds, policy, start, self.monotonic()))
                    continue
                raise _provider_client_error_with_snapshot(
                    exc,
                    OrchestrationPhase.RETRIEVING_RESULT,
                    request.provider_job_id,
                    terminal,
                    _elapsed(start, self.monotonic()),
                    polls,
                    last_poll_elapsed,
                ) from exc
            if result.job_id != request.provider_job_id or result.profile != request.result_profile:
                raise OrchestrationError(OrchestrationErrorCategory.RESULT_MALFORMED, "provider result identity/profile mismatch", OrchestrationPhase.RETRIEVING_RESULT, request.provider_job_id, result.status.value)
            if result.request_id and terminal.request_id and result.request_id != terminal.request_id:
                raise OrchestrationError(OrchestrationErrorCategory.RESULT_MALFORMED, "provider result request_id did not match terminal status", OrchestrationPhase.RETRIEVING_RESULT, request.provider_job_id, result.status.value)
            if result.status != terminal.status:
                raise OrchestrationError(OrchestrationErrorCategory.RESULT_MALFORMED, "provider result status did not match terminal status", OrchestrationPhase.RETRIEVING_RESULT, request.provider_job_id, result.status.value)
            if not result.raw_provider_payload and not result.documents and not result.result_artifact and result.status != ProviderLifecycleStatus.PROVIDER_PARTIAL_FAILED:
                raise OrchestrationError(OrchestrationErrorCategory.RESULT_MALFORMED, "provider result contained no inline payload or artifact metadata", OrchestrationPhase.RETRIEVING_RESULT, request.provider_job_id, result.status.value)
            return result, polls, terminal

    async def _ingest(self, request, result, page_summary):
        identity = RawResultIdentity(request.processing_attempt_id, request.correlation_id, request.document_id, request.source_file_id, request.provider_name, request.provider_job_id, result.request_id or request.provider_request_id, result.profile, result.status.value)
        source = RawResultSourceProvenance(request.source_checksum_sha256, request.source_etag, request.source_media_type)
        provider = RawResultProviderProvenance(build_tag=_field(result.raw_provider_payload, "build_tag"), configuration={"profile": result.profile, "status": result.status.value, "source_checksum_sha256": request.source_checksum_sha256, "source_media_type": request.source_media_type}, timestamps=_field(result.raw_provider_payload, "timestamps") or {}, warnings=tuple(_warnings(result)), errors=tuple(_errors(result)))
        if result.result_artifact:
            metadata = _artifact_metadata(result.result_artifact)
            artifact = await self.provider.get_job_artifact(request.provider_job_id, metadata)
            if artifact is None or not isinstance(artifact.content, bytes):
                raise OrchestrationError(OrchestrationErrorCategory.ARTIFACT_FAILURE, "provider artifact download returned no bytes", OrchestrationPhase.DOWNLOADING_ARTIFACT, request.provider_job_id, result.status.value)
            return ingest_artifact_result(storage=self.storage, identity=identity, source=source, provider=provider, artifact_bytes=artifact.content, artifact_metadata=RawResultArtifactMetadata(artifact_id=artifact.metadata.artifact_id, media_type=artifact.metadata.format, compression=artifact.metadata.compression, size_bytes=artifact.metadata.size_bytes, checksum_sha256=artifact.metadata.sha256, provider_metadata={"format": artifact.metadata.format, "compression": artifact.metadata.compression}), page_summary=page_summary, existing_storage_reference=request.raw_result_storage_reference)
        payload = result.raw_provider_payload if result.raw_provider_payload is not None else {"documents": result.documents}
        return ingest_inline_result(storage=self.storage, identity=identity, source=source, provider=provider, inline_result=payload, page_summary=page_summary, existing_storage_reference=request.raw_result_storage_reference)

    def _failure_outcome(self, request, provider_request_id, error, snapshot, polls, start):
        return OrchestrationOutcome(request.processing_attempt_id, request.correlation_id, request.document_id, request.source_file_id, request.provider_name, request.provider_job_id, provider_request_id, error.phase, None if snapshot is None else snapshot.status, _elapsed(start, self.monotonic()), polls, snapshot, error=error)


@dataclass(frozen=True)
class ProviderSourceDocumentRequest:
    document_id: str
    pdf_source_url: str = field(repr=False)
    pdf_source_etag: str | None = None
    pdf_source_sha256: str | None = None

    def to_provider_json(self) -> dict[str, Any]:
        data = {"document_id": self.document_id, "pdf_source_url": self.pdf_source_url}
        if self.pdf_source_etag is not None:
            data["pdf_source_etag"] = self.pdf_source_etag
        if self.pdf_source_sha256 is not None:
            data["pdf_source_sha256"] = self.pdf_source_sha256
        return data


@dataclass(frozen=True)
class ProviderJobRequest:
    job_id: str
    request_id: str | None
    documents: list[ProviderSourceDocumentRequest]
    options: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "2026-07-10"

    def to_provider_json(self) -> dict[str, Any]:
        _validate_provider_options(self.options)
        return {
            "schema_version": self.schema_version,
            "job_id": self.job_id,
            "request_id": self.request_id,
            "documents": [document.to_provider_json() for document in self.documents],
            "options": dict(self.options),
        }


def _build_provider_request(r: OrchestrationRequest) -> ProviderJobRequest:
    return ProviderJobRequest(
        r.provider_job_id,
        r.provider_request_id or r.correlation_id,
        [ProviderSourceDocumentRequest(r.document_id, r.source_url, r.source_etag, r.source_checksum_sha256)],
        dict(r.provider_job_options),
    )


def _timeout_error(message, provider_job_id, snapshot, elapsed, polls, last_poll_elapsed):
    return OrchestrationError(
        OrchestrationErrorCategory.TIMEOUT,
        message,
        OrchestrationPhase.TIMED_OUT,
        provider_job_id,
        _snapshot_status(snapshot),
        elapsed_seconds=elapsed,
        poll_count=polls,
        provider_request_id=_snapshot_request_id(snapshot),
        last_provider_progress=_snapshot_progress(snapshot),
        last_successful_poll_elapsed_seconds=last_poll_elapsed,
    )


def _check_deadline(
    policy,
    start,
    now,
    polls,
    *,
    provider_job_id=None,
    snapshot=None,
    last_successful_poll_elapsed_seconds=None,
):
    elapsed = _elapsed(start, now)
    if elapsed >= policy.timeout_seconds:
        raise _timeout_error(
            "orchestration timed out; provider job may continue running because cancellation is not implemented",
            provider_job_id,
            snapshot,
            elapsed,
            polls,
            last_successful_poll_elapsed_seconds,
        )


def _provider_client_error_with_snapshot(
    exc,
    phase,
    provider_job_id,
    snapshot,
    elapsed,
    polls,
    last_poll_elapsed,
):
    return OrchestrationError(
        _map_provider_error(exc, phase),
        _safe_provider_message(exc),
        phase,
        provider_job_id,
        _snapshot_status(snapshot),
        exc.detail.provider_code,
        exc.detail.retryable,
        elapsed,
        polls,
        _snapshot_request_id(snapshot),
        _snapshot_progress(snapshot),
        last_poll_elapsed,
    )


def _snapshot_status(snapshot):
    return snapshot.status.value if isinstance(snapshot, ProviderJobStatus) else None


def _snapshot_request_id(snapshot):
    return snapshot.request_id if isinstance(snapshot, ProviderJobStatus) else None


def _snapshot_progress(snapshot):
    return snapshot.progress if isinstance(snapshot, ProviderJobStatus) else None


def _elapsed(start, now):
    return max(0.0, float(now - start))


def _sleep_interval(interval, policy, start, now):
    remaining = max(0.0, policy.timeout_seconds - _elapsed(start, now))
    return min(float(interval), float(policy.max_interval_seconds), remaining)


def _phase_for_status(s):
    try:
        return {ProviderLifecycleStatus.QUEUED: OrchestrationPhase.PROVIDER_QUEUED, ProviderLifecycleStatus.RUNNING: OrchestrationPhase.PROVIDER_RUNNING, ProviderLifecycleStatus.PROVIDER_COMPLETED: OrchestrationPhase.PROVIDER_COMPLETED, ProviderLifecycleStatus.PROVIDER_PARTIAL_FAILED: OrchestrationPhase.PROVIDER_PARTIAL_FAILED, ProviderLifecycleStatus.FAILED: OrchestrationPhase.FAILED, ProviderLifecycleStatus.EXPIRED: OrchestrationPhase.FAILED}[s]
    except KeyError as exc:
        raise OrchestrationError(OrchestrationErrorCategory.STATUS_FAILURE, "provider returned unknown lifecycle status", OrchestrationPhase.FAILED, provider_status=str(s)) from exc


def _map_provider_error(exc, phase):
    if phase == OrchestrationPhase.DOWNLOADING_ARTIFACT:
        return OrchestrationErrorCategory.ARTIFACT_FAILURE
    return {ProviderErrorCategory.RESULT_NOT_READY: OrchestrationErrorCategory.RESULT_UNAVAILABLE, ProviderErrorCategory.RESULT_EXPIRED: OrchestrationErrorCategory.RESULT_UNAVAILABLE, ProviderErrorCategory.ARTIFACT_MISSING: OrchestrationErrorCategory.ARTIFACT_FAILURE, ProviderErrorCategory.EXECUTION_FAILED: OrchestrationErrorCategory.PROVIDER_FAILED, ProviderErrorCategory.VALIDATION: OrchestrationErrorCategory.SUBMISSION_REJECTED, ProviderErrorCategory.CONFLICT: OrchestrationErrorCategory.SUBMISSION_REJECTED}.get(exc.detail.category, OrchestrationErrorCategory.STATUS_FAILURE if phase in {OrchestrationPhase.PROVIDER_QUEUED, OrchestrationPhase.PROVIDER_RUNNING} else OrchestrationErrorCategory.UNEXPECTED)


def _safe_provider_message(exc):
    return _redact(exc.detail.safe_message)


def _provider_code(error):
    return error.get("code") if isinstance(error, dict) else None


def _field(payload, name):
    return payload.get(name) if isinstance(payload, dict) else None


def _warnings(result):
    payload = result.raw_provider_payload or {}
    return payload.get("warnings") or []


def _errors(result):
    payload = result.raw_provider_payload or {}
    return payload.get("errors") or ([] if result.status != ProviderLifecycleStatus.PROVIDER_PARTIAL_FAILED else ["provider partial failure"])


def _artifact_metadata(value):
    if not isinstance(value, dict):
        raise OrchestrationError(OrchestrationErrorCategory.RESULT_MALFORMED, "artifact metadata was malformed", OrchestrationPhase.DOWNLOADING_ARTIFACT)
    artifact_id = value.get("artifact_id")
    size_bytes = value.get("size_bytes")
    checksum = value.get("sha256") or value.get("checksum_sha256")
    if not isinstance(artifact_id, str) or not artifact_id.strip():
        raise OrchestrationError(OrchestrationErrorCategory.RESULT_MALFORMED, "artifact metadata was missing artifact_id", OrchestrationPhase.DOWNLOADING_ARTIFACT)
    if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes < 0:
        raise OrchestrationError(OrchestrationErrorCategory.RESULT_MALFORMED, "artifact metadata had invalid size_bytes", OrchestrationPhase.DOWNLOADING_ARTIFACT)
    if not is_valid_sha256(checksum):
        raise OrchestrationError(OrchestrationErrorCategory.RESULT_MALFORMED, "artifact metadata had invalid checksum", OrchestrationPhase.DOWNLOADING_ARTIFACT)
    return ArtifactMetadata(artifact_id, value.get("download_endpoint"), value.get("format") or value.get("media_type"), value.get("compression"), size_bytes, checksum)


def _page_summary(request, result):
    pages: list[dict[str, Any]] = []
    for document in result.documents or []:
        if isinstance(document, dict) and isinstance(document.get("raw_result"), list):
            pages.extend(document["raw_result"])
    if not pages:
        return None
    try:
        return summarize_pages(_map_page_identities(request.document_id, pages, request.expected_page_count), expected_pages_total=request.expected_page_count)
    except Exception:
        if result.status == ProviderLifecycleStatus.PROVIDER_PARTIAL_FAILED:
            return RawResultPageSummary(len(pages), mapping_valid=False)
        raise OrchestrationError(OrchestrationErrorCategory.RESULT_MALFORMED, "provider page metadata was malformed", OrchestrationPhase.RETRIEVING_RESULT, request.provider_job_id, result.status.value)


def _map_page_identities(document_id: str, pages: list[dict[str, Any]], expected_pages_total: int | None):
    from app.processing.models import ProcessingPageIdentity
    identities = []
    seen = set()
    for page in pages:
        page_number = int(page["page_number"])
        page_index = int(page["page_index"])
        local_page_index = int(page["local_page_index"])
        source_range = page["source_page_range"]
        start, end = (int(source_range["page_start"]), int(source_range["page_end"])) if isinstance(source_range, dict) else (int(source_range[0]), int(source_range[1]))
        if page_number in seen or page_index != page_number - 1 or page_number < start or page_number > end or local_page_index != page_number - start:
            raise ValueError("invalid page mapping")
        seen.add(page_number)
        identities.append(ProcessingPageIdentity(document_id, page_number, page_index, local_page_index, (start, end)))
    if expected_pages_total is not None and set(range(1, expected_pages_total + 1)) - seen:
        raise ValueError("missing pages")
    return sorted(identities, key=lambda identity: identity.page_number)


def _validate_provider_options(options: dict[str, Any]) -> None:
    for name, value in options.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float) and (not math.isfinite(float(value)) or value <= 0):
            raise ValueError(f"provider option {name} must be finite and positive")


_SENSITIVE_RE = re.compile(r"(https?://\S+|Bearer\s+\S+|Authorization:\s*\S+|api[_-]?key=\S+|token=\S+)", re.IGNORECASE)


def _redact(message: str) -> str:
    return _SENSITIVE_RE.sub("<redacted>", str(message))
