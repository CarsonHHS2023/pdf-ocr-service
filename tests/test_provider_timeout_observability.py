from __future__ import annotations

import asyncio

import pytest

from app.processing.errors import (
    ProviderClientError,
    ProviderErrorCategory,
    ProviderErrorDetail,
)
from app.processing.models import (
    ProviderJobStatus,
    ProviderLifecycleStatus,
    ProviderProgress,
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
from app.storage.local import LocalStorageProvider


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
            "job-timeout",
            "request-timeout",
            ProviderLifecycleStatus.QUEUED,
        )
        self.statuses: list[ProviderJobStatus | Exception] = []
        self.results: list[object] = []

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
        processing_attempt_id="attempt-timeout",
        correlation_id="correlation-timeout",
        document_id="document-timeout",
        source_file_id="source-timeout",
        source_url="https://example.test/provider.pdf",
        source_checksum_sha256=_SHA,
        source_media_type="application/pdf",
        provider_name="paddle-vl",
        provider_job_id="job-timeout",
        provider_request_id="request-timeout",
        result_profile="full",
    )


def _running(*, percent: float, pages_completed: int) -> ProviderJobStatus:
    return ProviderJobStatus(
        "job-timeout",
        "request-timeout",
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
        "job-timeout",
        "request-timeout",
        ProviderLifecycleStatus.PROVIDER_COMPLETED,
        True,
        ProviderProgress(
            pages_total=100,
            pages_completed=100,
            percent_complete=100.0,
            provider_execution_complete=True,
        ),
    )


def _orchestrator(tmp_path, provider: _Provider, clock: _Clock) -> ProcessingOrchestrator:
    return ProcessingOrchestrator(
        provider=provider,
        storage=LocalStorageProvider(tmp_path),
        sleep=clock.sleep,
        monotonic=clock,
    )


def test_deadline_timeout_preserves_last_provider_status_and_progress(tmp_path) -> None:
    provider = _Provider()
    provider.statuses = [
        _running(percent=10.0, pages_completed=10),
        _running(percent=25.0, pages_completed=25),
        _running(percent=50.0, pages_completed=50),
    ]
    clock = _Clock()

    with pytest.raises(OrchestrationError) as captured:
        asyncio.run(
            _orchestrator(tmp_path, provider, clock).run_once(
                _request(),
                PollingPolicy(
                    timeout_seconds=2,
                    initial_interval_seconds=1,
                    max_interval_seconds=1,
                ),
            )
        )

    error = captured.value
    assert error.category is OrchestrationErrorCategory.TIMEOUT
    assert error.phase is OrchestrationPhase.TIMED_OUT
    assert error.provider_job_id == "job-timeout"
    assert error.provider_request_id == "request-timeout"
    assert error.provider_status == ProviderLifecycleStatus.RUNNING.value
    assert error.poll_count == 2
    assert error.elapsed_seconds == 2.0
    assert error.last_successful_poll_elapsed_seconds == 1.0
    assert error.last_provider_progress is not None
    assert error.last_provider_progress.pages_total == 100
    assert error.last_provider_progress.pages_completed == 25
    assert error.last_provider_progress.percent_complete == 25.0


def test_max_status_requests_preserves_last_provider_snapshot(tmp_path) -> None:
    provider = _Provider()
    provider.statuses = [_running(percent=12.5, pages_completed=12)]
    clock = _Clock()

    with pytest.raises(OrchestrationError) as captured:
        asyncio.run(
            _orchestrator(tmp_path, provider, clock).run_once(
                _request(),
                PollingPolicy(timeout_seconds=30, max_status_requests=1),
            )
        )

    error = captured.value
    assert error.category is OrchestrationErrorCategory.TIMEOUT
    assert error.provider_status == ProviderLifecycleStatus.RUNNING.value
    assert error.provider_request_id == "request-timeout"
    assert error.poll_count == 1
    assert error.last_provider_progress is not None
    assert error.last_provider_progress.percent_complete == 12.5


def test_status_poll_client_failure_uses_provider_phase_and_last_snapshot(tmp_path) -> None:
    provider = _Provider()
    provider.statuses = [
        _running(percent=40.0, pages_completed=40),
        ProviderClientError(
            ProviderErrorDetail(
                ProviderErrorCategory.UNAVAILABLE,
                "provider temporarily unavailable",
                retryable=False,
            )
        ),
    ]
    clock = _Clock()

    with pytest.raises(OrchestrationError) as captured:
        asyncio.run(
            _orchestrator(tmp_path, provider, clock).run_once(
                _request(),
                PollingPolicy(
                    timeout_seconds=30,
                    initial_interval_seconds=1,
                    max_interval_seconds=1,
                ),
            )
        )

    error = captured.value
    assert error.category is OrchestrationErrorCategory.STATUS_FAILURE
    assert error.phase is OrchestrationPhase.PROVIDER_RUNNING
    assert error.provider_status == ProviderLifecycleStatus.RUNNING.value
    assert error.provider_request_id == "request-timeout"
    assert error.poll_count == 1
    assert error.last_provider_progress is not None
    assert error.last_provider_progress.percent_complete == 40.0


def test_result_poll_client_failure_preserves_terminal_provider_snapshot(tmp_path) -> None:
    provider = _Provider()
    provider.statuses = [_completed()]
    provider.results = [
        ProviderClientError(
            ProviderErrorDetail(
                ProviderErrorCategory.UNAVAILABLE,
                "provider result endpoint unavailable",
                retryable=False,
            )
        )
    ]
    clock = _Clock()

    with pytest.raises(OrchestrationError) as captured:
        asyncio.run(
            _orchestrator(tmp_path, provider, clock).run_once(_request())
        )

    error = captured.value
    assert error.category is OrchestrationErrorCategory.UNEXPECTED
    assert error.phase is OrchestrationPhase.RETRIEVING_RESULT
    assert error.provider_status == ProviderLifecycleStatus.PROVIDER_COMPLETED.value
    assert error.provider_request_id == "request-timeout"
    assert error.poll_count == 1
    assert error.last_provider_progress is not None
    assert error.last_provider_progress.percent_complete == 100.0
