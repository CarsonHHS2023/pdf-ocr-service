from __future__ import annotations

import asyncio

import pytest

from app.processing.errors import (
    ProviderClientError,
    ProviderErrorCategory,
    ProviderErrorDetail,
)
from app.processing.integration import (
    IntegrationError,
    IntegrationErrorCategory,
    ProcessingIntegrationRequest,
    RetainedSourceDescriptor,
)
from app.processing.models import (
    ProviderJobStatus,
    ProviderLifecycleStatus,
    ProviderProgress,
    ProviderResult,
    ProviderSubmission,
)
from app.processing.orchestration import (
    OrchestrationError,
    OrchestrationErrorCategory,
    OrchestrationPhase,
    OrchestrationRequest,
    PollingPolicy,
    ProcessingOrchestrator,
)
from app.processing import pdf_provider_sharding_compat as compat
from app.processing.pdf_provider_sharding import ProviderTransportShardRunResult
from app.processing.provider_input_source_access import build_provider_input_source_url_factory
from app.storage.errors import ProviderUnavailable
from app.storage.local import LocalStorageProvider
from app.storage.models import StorageReference
from scripts.apply_provider_shard_resilience import patch_provider_shard_resilience


_SHA = "a" * 64


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    async def sleep(self, seconds: float) -> None:
        self.value += seconds


class _Provider:
    def __init__(self) -> None:
        self.submission = ProviderSubmission(
            "job-resilience",
            "request-resilience",
            ProviderLifecycleStatus.QUEUED,
        )
        self.statuses: list[ProviderJobStatus | Exception] = []
        self.results: list[ProviderResult | Exception] = []

    async def submit_job(self, request):
        return self.submission

    async def get_job_status(self, job_id):
        item = self.statuses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def get_job_result(self, job_id, profile=None):
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def get_job_artifact(self, job_id, metadata=None):  # pragma: no cover
        raise AssertionError("artifact retrieval is not expected")


def _request() -> OrchestrationRequest:
    return OrchestrationRequest(
        processing_attempt_id="attempt-resilience",
        correlation_id="correlation-resilience",
        document_id="document-resilience",
        source_file_id="source-resilience",
        source_url="https://example.test/provider.pdf",
        source_checksum_sha256=_SHA,
        source_media_type="application/pdf",
        provider_name="paddle-vl",
        provider_job_id="job-resilience",
        provider_request_id="request-resilience",
        result_profile="full",
    )


def _running(percent: float = 40.0, pages_completed: int = 40) -> ProviderJobStatus:
    return ProviderJobStatus(
        "job-resilience",
        "request-resilience",
        ProviderLifecycleStatus.RUNNING,
        False,
        ProviderProgress(
            pages_total=100,
            pages_completed=pages_completed,
            percent_complete=percent,
            provider_execution_complete=False,
        ),
    )


def _completed() -> ProviderJobStatus:
    return ProviderJobStatus(
        "job-resilience",
        "request-resilience",
        ProviderLifecycleStatus.PROVIDER_COMPLETED,
        True,
        ProviderProgress(
            pages_total=100,
            pages_completed=100,
            percent_complete=100.0,
            provider_execution_complete=True,
        ),
    )


def _retryable_unavailable(message: str = "provider temporarily unavailable") -> ProviderClientError:
    return ProviderClientError(
        ProviderErrorDetail(
            ProviderErrorCategory.UNAVAILABLE,
            message,
            retryable=True,
        )
    )


def _orchestrator(tmp_path, provider: _Provider, clock: _Clock) -> ProcessingOrchestrator:
    return ProcessingOrchestrator(
        provider=provider,
        storage=LocalStorageProvider(tmp_path),
        sleep=clock.sleep,
        monotonic=clock,
    )


def test_overlay_is_idempotent_after_required_markers_exist() -> None:
    patch_provider_shard_resilience()
    patch_provider_shard_resilience()


def test_status_poll_retries_transient_unavailable_within_existing_deadline(tmp_path, capsys) -> None:
    provider = _Provider()
    provider.statuses = [
        _running(),
        _retryable_unavailable(),
        _completed(),
    ]
    clock = _Clock()

    terminal, polls, phase, snapshot, _ = asyncio.run(
        _orchestrator(tmp_path, provider, clock)._poll_terminal(
            _request(),
            PollingPolicy(
                timeout_seconds=30,
                initial_interval_seconds=1,
                max_interval_seconds=2,
            ),
            0.0,
            0,
            ProviderLifecycleStatus.QUEUED,
        )
    )

    assert terminal.status is ProviderLifecycleStatus.PROVIDER_COMPLETED
    assert phase is OrchestrationPhase.PROVIDER_COMPLETED
    assert snapshot is terminal
    assert polls == 2
    assert provider.statuses == []
    stderr = capsys.readouterr().err
    assert "PDF_PROVIDER_POLL_RETRY" in stderr
    assert "phase=provider_running" in stderr
    assert "error_category=provider_unavailable" in stderr


def test_status_poll_retry_exhaustion_preserves_last_successful_snapshot(tmp_path) -> None:
    provider = _Provider()
    provider.statuses = [
        _running(percent=40.0, pages_completed=40),
        _retryable_unavailable("transient-1"),
        _retryable_unavailable("transient-2"),
        _retryable_unavailable("transient-3"),
        _retryable_unavailable("transient-4"),
    ]
    clock = _Clock()

    with pytest.raises(OrchestrationError) as captured:
        asyncio.run(
            _orchestrator(tmp_path, provider, clock)._poll_terminal(
                _request(),
                PollingPolicy(
                    timeout_seconds=30,
                    initial_interval_seconds=1,
                    max_interval_seconds=2,
                ),
                0.0,
                0,
                ProviderLifecycleStatus.QUEUED,
            )
        )

    error = captured.value
    assert error.category is OrchestrationErrorCategory.STATUS_FAILURE
    assert error.phase is OrchestrationPhase.PROVIDER_RUNNING
    assert error.provider_status == ProviderLifecycleStatus.RUNNING.value
    assert error.provider_request_id == "request-resilience"
    assert error.poll_count == 1
    assert error.last_provider_progress is not None
    assert error.last_provider_progress.percent_complete == 40.0


def test_result_poll_retries_transient_unavailable_within_existing_deadline(tmp_path) -> None:
    provider = _Provider()
    terminal = _completed()
    provider.results = [
        _retryable_unavailable("result endpoint temporarily unavailable"),
        ProviderResult(
            "job-resilience",
            "request-resilience",
            ProviderLifecycleStatus.PROVIDER_COMPLETED,
            "full",
            None,
            documents=[{"document_id": "document-resilience", "raw_result": []}],
        ),
    ]
    clock = _Clock()

    result, polls, snapshot = asyncio.run(
        _orchestrator(tmp_path, provider, clock)._retrieve_result(
            _request(),
            PollingPolicy(
                timeout_seconds=30,
                initial_interval_seconds=1,
                max_interval_seconds=2,
            ),
            0.0,
            1,
            terminal,
            0.0,
        )
    )

    assert result.status is ProviderLifecycleStatus.PROVIDER_COMPLETED
    assert polls == 1
    assert snapshot is terminal
    assert provider.results == []


def test_sharded_failure_outcome_preserves_nested_provider_snapshot() -> None:
    orchestration_error = OrchestrationError(
        OrchestrationErrorCategory.STATUS_FAILURE,
        "provider is unavailable",
        OrchestrationPhase.PROVIDER_RUNNING,
        "job-resilience-s001",
        ProviderLifecycleStatus.RUNNING.value,
        None,
        True,
        125.0,
        9,
        "request-resilience-s001",
        ProviderProgress(
            pages_total=95,
            pages_completed=63,
            percent_complete=66.315789,
            provider_execution_complete=False,
        ),
        118.0,
    )
    integration_error = IntegrationError(
        IntegrationErrorCategory.ORCHESTRATION_FAILURE,
        "provider is unavailable",
        orchestration_error=orchestration_error,
        warnings=("transient provider transport failure",),
        revocation_succeeded=True,
    )
    request = ProcessingIntegrationRequest(
        processing_attempt_id="attempt-resilience",
        correlation_id="correlation-resilience",
        retained_source=RetainedSourceDescriptor(
            document_id="document-resilience",
            source_file_id="source-resilience",
            storage_reference=StorageReference.parse("src_" + "b" * 32),
            retained=True,
            sha256=_SHA,
            byte_size=123,
            media_type="application/pdf",
            filename="source.pdf",
        ),
        provider_name="paddle-vl",
        provider_job_id="job-resilience",
        provider_request_id="request-resilience",
        result_profile="full",
    )
    result = ProviderTransportShardRunResult(
        canonicalization=None,
        raw_result=None,
        error=integration_error,
        cleanup_safe=True,
        submission_started=True,
        shard_count=2,
    )

    outcome = compat._outcome_from_sharded_result(
        request,
        result,
        elapsed_seconds=125.0,
    )
    fields = compat._provider_failure_diagnostic_fields(outcome.error)

    assert outcome.provider_terminal_status is ProviderLifecycleStatus.RUNNING
    assert outcome.provider_request_id == "request-resilience-s001"
    assert outcome.poll_count == 9
    assert outcome.warnings == ("transient provider transport failure",)
    assert fields["error_phase"] == "provider_running"
    assert fields["provider_status"] == "running"
    assert fields["provider_pages_completed"] == 63
    assert fields["provider_percent_complete"] == 66.315789


def test_provider_source_fallback_diagnostic_is_mirrored_to_stderr(monkeypatch, capsys) -> None:
    import app.processing.provider_input_source_access as source_access

    def unavailable(*args, **kwargs):
        raise ProviderUnavailable("temporary object URL unavailable")

    monkeypatch.setattr(source_access, "generate_existing_provider_read_url", unavailable)
    factory = build_provider_input_source_url_factory(
        storage=object(),
        reference=StorageReference.parse("src_" + "c" * 32),
        byte_size=12345,
    )

    from datetime import timedelta

    assert factory(timedelta(minutes=20)) is None
    stderr = capsys.readouterr().err
    assert "PDF_PROVIDER_SOURCE_ACCESS" in stderr
    assert "route=atlas_source_transport_fallback" in stderr
    assert "token=" not in stderr
    assert "http" not in stderr.lower()
