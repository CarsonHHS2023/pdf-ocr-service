"""OpenAI-specific batched refinement with one loop-local HTTP client per document."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import sys
from time import perf_counter
from typing import AsyncContextManager, Callable, Mapping, Sequence

import httpx

from app.processing.batched_structure_refinement import BatchedStructureRefiner
from app.processing.llm_structure_refinement import (
    DEFAULT_STRUCTURE_REFINEMENT_PROMPT_VERSION,
    StructureRefinementPatch,
)
from app.processing.openai_structure_refinement_provider import (
    OpenAIResponsesStructureRefiner,
    StructureRefinementProviderError,
)
from app.processing.structured_result_v2.model import StructuredProcessingResultV2

ClientFactory = Callable[[float], AsyncContextManager[httpx.AsyncClient]]
RefinementEventSink = Callable[[str, Mapping[str, object]], None]

_logger = logging.getLogger("uvicorn.error")
_RETRYABLE_STATUS_CODES = frozenset({408, 409, 429, 500, 502, 503, 504})
_LEGACY_DEFAULT_PROMPT_VERSIONS = frozenset(
    {
        "pdf_structure_refinement_v2",
        "pdf_structure_refinement_v3_summary_peer_consistency",
    }
)


def _log_refinement_event(event: str, fields: Mapping[str, object]) -> None:
    payload = " ".join(f"{name}={value}" for name, value in sorted(fields.items()))
    message = f"{event} {payload}".rstrip()
    _logger.info(message)
    print(message, file=sys.stderr, flush=True)


def _default_client_factory(timeout_seconds: float) -> AsyncContextManager[httpx.AsyncClient]:
    return httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds))


def _effective_prompt_version(configured: str) -> str:
    """Upgrade historical defaults while preserving explicit custom versions."""
    if configured in _LEGACY_DEFAULT_PROMPT_VERSIONS:
        return DEFAULT_STRUCTURE_REFINEMENT_PROMPT_VERSION
    return configured


def _document_boundary_positions(spr: StructuredProcessingResultV2) -> dict[str, str]:
    ordered = sorted(
        spr.source_units,
        key=lambda unit: (unit.source_order, unit.source_unit_id),
    )
    if not ordered:
        return {}
    first_id = ordered[0].source_unit_id
    last_id = ordered[-1].source_unit_id
    if first_id == last_id:
        return {first_id: "first_and_last_page"}
    return {first_id: "first_page", last_id: "last_page"}


def _retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value.strip())
    except (TypeError, ValueError):
        return None
    return max(0.0, parsed)


async def _post_with_client(
    client: httpx.AsyncClient,
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, object],
    timeout_seconds: float,
) -> Mapping[str, object]:
    try:
        response = await client.post(
            url,
            headers=dict(headers),
            json=payload,
            timeout=httpx.Timeout(timeout_seconds),
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        raise StructureRefinementProviderError(
            f"structure refinement provider HTTP {status_code}",
            retryable=status_code in _RETRYABLE_STATUS_CODES,
            status_code=status_code,
            retry_after_seconds=_retry_after_seconds(exc.response.headers.get("Retry-After")),
        ) from exc
    except httpx.RequestError as exc:
        raise StructureRefinementProviderError(
            "structure refinement provider unavailable",
            retryable=True,
        ) from exc

    try:
        decoded = response.json()
    except ValueError as exc:
        raise StructureRefinementProviderError(
            "structure refinement provider returned invalid JSON",
            retryable=False,
            status_code=response.status_code,
        ) from exc
    if not isinstance(decoded, Mapping):
        raise StructureRefinementProviderError(
            "structure refinement provider response must be an object",
            retryable=False,
            status_code=response.status_code,
        )
    return decoded


@dataclass(slots=True)
class StructureRefinementDocumentMetrics:
    """Aggregate low-cardinality metrics from existing refinement events."""

    batch_count: int = 0
    page_count: int = 0
    successful_batch_count: int = 0
    failed_batch_count: int = 0
    operation_count: int = 0
    page_role_review_count: int = 0
    provider_failure_count: int = 0
    retry_count: int = 0
    rate_limit_count: int = 0
    server_error_count: int = 0
    provider_unavailable_count: int = 0

    def record(self, event: str, fields: Mapping[str, object]) -> None:
        if event == "PDF_STRUCTURE_REFINEMENT_PLANNED":
            self.batch_count = _non_negative_int(fields.get("batch_count"))
            self.page_count = _non_negative_int(fields.get("page_count"))
        elif event == "PDF_STRUCTURE_REFINEMENT_PROVIDER_FAILURE":
            self.provider_failure_count += 1
            status_code = _optional_int(fields.get("status_code"))
            if status_code == 429:
                self.rate_limit_count += 1
            elif status_code is not None and status_code >= 500:
                self.server_error_count += 1
            elif status_code is None:
                self.provider_unavailable_count += 1
        elif event == "PDF_STRUCTURE_REFINEMENT_PROVIDER_RETRY_SCHEDULED":
            self.retry_count += 1
        elif event == "PDF_STRUCTURE_REFINEMENT_COMPLETED":
            self.successful_batch_count = _non_negative_int(
                fields.get("successful_batch_count")
            )
            self.failed_batch_count = _non_negative_int(fields.get("failed_batch_count"))
            self.operation_count = _non_negative_int(fields.get("operation_count"))
            self.page_role_review_count = _non_negative_int(
                fields.get("page_role_review_count")
            )

    def snapshot(
        self,
        *,
        model_id: str,
        prompt_version: str,
        outcome: str,
        duration_ms: int,
        error_type: str | None,
    ) -> dict[str, object]:
        return {
            "provider": "openai",
            "model_id": model_id,
            "prompt_version": prompt_version,
            "outcome": outcome,
            "duration_ms": max(0, duration_ms),
            "batch_count": self.batch_count,
            "page_count": self.page_count,
            "successful_batch_count": self.successful_batch_count,
            "failed_batch_count": self.failed_batch_count,
            "operation_count": self.operation_count,
            "page_role_review_count": self.page_role_review_count,
            "provider_failure_count": self.provider_failure_count,
            "retry_count": self.retry_count,
            "rate_limit_count": self.rate_limit_count,
            "server_error_count": self.server_error_count,
            "provider_unavailable_count": self.provider_unavailable_count,
            "error_type": error_type,
        }


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _non_negative_int(value: object) -> int:
    parsed = _optional_int(value)
    return max(0, parsed) if parsed is not None else 0


def _fanout_event_sinks(
    primary: RefinementEventSink,
    metrics: StructureRefinementDocumentMetrics,
) -> RefinementEventSink:
    def emit(event: str, fields: Mapping[str, object]) -> None:
        primary(event, fields)
        metrics.record(event, fields)

    return emit


@dataclass(frozen=True, slots=True)
class OpenAIBatchedStructureRefiner:
    """Reuse one AsyncClient across all batches and retries for one document."""

    probe: OpenAIResponsesStructureRefiner
    batch_planner: Callable[[StructuredProcessingResultV2], Sequence[Mapping[str, str]]]
    max_concurrent_batches: int
    batch_timeout_seconds: float
    global_semaphore: object | None = None
    client_factory: ClientFactory = _default_client_factory
    event_sink: RefinementEventSink = _log_refinement_event

    async def propose_async(self, spr: StructuredProcessingResultV2) -> StructureRefinementPatch:
        started = perf_counter()
        metrics = StructureRefinementDocumentMetrics()
        batch_event_sink = _fanout_event_sinks(self.event_sink, metrics)
        provider_event_sink = _fanout_event_sinks(self.probe.event_sink, metrics)
        prompt_version = _effective_prompt_version(self.probe.prompt_version)
        boundary_positions = _document_boundary_positions(spr)
        outcome = "failed"
        error_type: str | None = None

        try:
            async with self.client_factory(self.probe.timeout_seconds) as client:
                async def shared_post(url, headers, payload, timeout_seconds):
                    return await _post_with_client(
                        client,
                        url,
                        headers,
                        payload,
                        timeout_seconds,
                    )

                def factory(images: Mapping[str, str]) -> OpenAIResponsesStructureRefiner:
                    scoped_page_roles = {
                        source_unit_id: position
                        for source_unit_id, position in boundary_positions.items()
                        if source_unit_id in images
                    }
                    return OpenAIResponsesStructureRefiner(
                        api_key=self.probe.api_key,
                        model_id=self.probe.model_id,
                        page_image_resolver=lambda _spr: dict(images),
                        page_role_review_positions=scoped_page_roles,
                        endpoint=self.probe.endpoint,
                        timeout_seconds=self.probe.timeout_seconds,
                        prompt_version=prompt_version,
                        async_http_post=shared_post,
                        max_attempts=self.probe.max_attempts,
                        initial_backoff_seconds=self.probe.initial_backoff_seconds,
                        max_backoff_seconds=self.probe.max_backoff_seconds,
                        sleep=self.probe.sleep,
                        event_sink=provider_event_sink,
                    )

                refiner = BatchedStructureRefiner(
                    model_id=self.probe.model_id,
                    batch_planner=self.batch_planner,
                    refiner_factory=factory,
                    prompt_version=prompt_version,
                    max_concurrent_batches=self.max_concurrent_batches,
                    batch_timeout_seconds=self.batch_timeout_seconds,
                    global_semaphore=self.global_semaphore,  # type: ignore[arg-type]
                    event_sink=batch_event_sink,
                )
                patch = await refiner.propose_async(spr)
                outcome = "succeeded"
                return patch
        except Exception as exc:
            error_type = type(exc).__name__
            raise
        finally:
            self.event_sink(
                "PDF_STRUCTURE_REFINEMENT_DOCUMENT_METRICS",
                metrics.snapshot(
                    model_id=self.probe.model_id,
                    prompt_version=prompt_version,
                    outcome=outcome,
                    duration_ms=round((perf_counter() - started) * 1000),
                    error_type=error_type,
                ),
            )

    def propose(self, spr: StructuredProcessingResultV2) -> StructureRefinementPatch:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.propose_async(spr))
        raise RuntimeError(
            "OpenAIBatchedStructureRefiner.propose() cannot run inside an active event loop; "
            "await propose_async() instead"
        )


__all__ = [
    "ClientFactory",
    "OpenAIBatchedStructureRefiner",
    "StructureRefinementDocumentMetrics",
]
