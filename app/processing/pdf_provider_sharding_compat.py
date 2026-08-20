"""Compatibility install for byte-bounded provider transport sharding.

The production PDF ingestion runner still constructs one
``EndToEndProcessingIntegrationService``. This compatibility layer preserves that
contract for normal inputs and transparently fan-outs only oversized preprocessed
provider PDFs into sequential transport shards. Modal's own ``batch_size`` and
worker scaling are intentionally untouched.
"""
from __future__ import annotations

import logging
from typing import Any

from app.processing.integration import (
    EndToEndProcessingIntegrationService as _BaseIntegrationService,
    IntegrationError,
    IntegrationErrorCategory,
    ProcessingIntegrationOutcome,
)
from app.processing.models import ProviderLifecycleStatus
from app.processing.orchestration import OrchestrationPhase
from app.processing.pdf_geometry_integration import provider_delivery_descriptor
from app.processing.pdf_page_presentation_bridge import PresentationProviderInput
from app.processing.pdf_provider_sharding import (
    PROVIDER_TRANSPORT_SHARD_TARGET_BYTES,
    ProviderTransportShardError,
    ProviderTransportShardRunResult,
    provider_transport_sharding_required,
    run_provider_transport_shards,
)
from app.processing.transport.models import TransportGrantState

_logger = logging.getLogger("uvicorn.error")
_INSTALLED = False


def _diagnostic(event: str, **fields: object) -> None:
    payload = " ".join(f"{name}={value}" for name, value in fields.items())
    _logger.info("%s %s", event, payload)


def _identity_provider_page_map(page_count: int) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "provider_page_index": index,
            "original_page_index": index,
            "original_page_number": index + 1,
            "source_unit_id": f"pdf-page:{index + 1:06d}",
        }
        for index in range(page_count)
    )


def _normalize_legacy_provider_input(provider_input: Any) -> PresentationProviderInput:
    """Adapt a validated legacy provider input to the sharding contract.

    Geometry-only ingestion predates presentation routing and carries provider
    identity as ``storage_reference/checksum_sha256/byte_size``. Resolve that
    identity through the shared delivery descriptor, then normalize once at this
    boundary instead of teaching every sharding helper a second field vocabulary.
    """
    delivery = provider_delivery_descriptor(provider_input)
    preprocessing = getattr(provider_input, "preprocessing", None)
    page_count = getattr(preprocessing, "page_count", None)
    if not isinstance(page_count, int) or isinstance(page_count, bool) or page_count <= 0:
        raise ProviderTransportShardError(
            "legacy provider input page count is invalid for transport sharding"
        )

    page_map = _identity_provider_page_map(page_count)
    pages = [
        {
            "page_number": index + 1,
            "source_unit_id": f"pdf-page:{index + 1:06d}",
            "ocr_route": "modal_paddle_ocr",
        }
        for index in range(page_count)
    ]
    manifest = {
        "page_count": page_count,
        "provider_page_count": page_count,
        "presentation_page_count": 0,
        "native_text_page_count": 0,
        "local_result_page_count": 0,
        "pages": pages,
        "provider_page_map": [dict(item) for item in page_map],
    }
    return PresentationProviderInput(
        processing_attempt_id=str(getattr(provider_input, "processing_attempt_id")),
        storage_reference=delivery.storage_reference,
        checksum_sha256=delivery.checksum_sha256,
        byte_size=delivery.byte_size,
        media_type=delivery.media_type,
        filename=delivery.filename,
        preprocessing=preprocessing,
        provider_storage_reference=delivery.storage_reference,
        provider_checksum_sha256=delivery.checksum_sha256,
        provider_byte_size=delivery.byte_size,
        provider_filename=delivery.filename,
        provider_page_count=page_count,
        provider_page_map=page_map,
        presentation_manifest=manifest,
    )


def _provider_input_for(service: Any) -> Any | None:
    orchestrator = getattr(service, "orchestrator", None)
    provider_input = getattr(orchestrator, "provider_input", None)
    if provider_input is None:
        return None

    provider_fields = (
        "provider_byte_size",
        "provider_page_count",
        "provider_page_map",
        "provider_checksum_sha256",
    )
    provider_present = tuple(hasattr(provider_input, name) for name in provider_fields)
    if all(provider_present):
        return provider_input
    if any(provider_present):
        raise ProviderTransportShardError(
            "provider transport sharding input has partial provider identity"
        )

    try:
        provider_delivery_descriptor(provider_input)
    except (TypeError, ValueError):
        return None
    return _normalize_legacy_provider_input(provider_input)


def _raw_client_for(service: Any) -> Any:
    orchestrator = getattr(service, "orchestrator", None)
    provider = getattr(orchestrator, "provider", None)
    delegate = getattr(provider, "_delegate", None)
    if delegate is None:
        raise ProviderTransportShardError(
            "provider transport sharding could not resolve the raw provider client"
        )
    required = ("submit_job", "get_job_status", "get_job_result", "get_job_artifact")
    if any(not hasattr(delegate, name) for name in required):
        raise ProviderTransportShardError(
            "provider transport sharding resolved an incompatible provider client"
        )
    return delegate


def _raw_result_fields(raw_result: Any | None) -> tuple[Any, str | None, int | None]:
    if raw_result is None:
        return None, None, None
    ingestion = raw_result.ingestion
    return ingestion.storage_reference, ingestion.payload_sha256, ingestion.payload_size_bytes


def _bounded_integration_error(exc: Exception) -> IntegrationError:
    if isinstance(exc, IntegrationError):
        return exc
    return IntegrationError(
        IntegrationErrorCategory.UNEXPECTED,
        "provider transport sharding failed before canonical content became ready",
    )


def _outcome_from_sharded_result(request: Any, result: ProviderTransportShardRunResult, *, elapsed_seconds: float) -> ProcessingIntegrationOutcome:
    raw_reference, raw_checksum, raw_size = _raw_result_fields(result.raw_result)
    grant_state = TransportGrantState.REVOKED if result.cleanup_safe else None
    if result.error is None and result.canonicalization is not None:
        return ProcessingIntegrationOutcome(
            document_id=request.retained_source.document_id,
            source_file_id=request.retained_source.source_file_id,
            provider_name=request.provider_name,
            provider_job_id=request.provider_job_id,
            provider_request_id=request.provider_request_id,
            integration_terminal_phase=OrchestrationPhase.RAW_RESULT_RETAINED,
            provider_terminal_status=ProviderLifecycleStatus.PROVIDER_COMPLETED,
            orchestration_outcome=None,
            raw_result=result.raw_result,
            raw_result_storage_reference=raw_reference,
            raw_result_checksum_sha256=raw_checksum,
            raw_result_size_bytes=raw_size,
            elapsed_seconds=elapsed_seconds,
            poll_count=0,
            warnings=(),
            grant_id=f"provider-transport-shards:{result.shard_count}",
            grant_final_state=grant_state,
            revocation_succeeded=result.cleanup_safe,
            error=None,
            canonicalization=result.canonicalization,
        )

    error = _bounded_integration_error(
        result.error if isinstance(result.error, Exception)
        else ProviderTransportShardError("provider transport sharding did not complete")
    )
    return ProcessingIntegrationOutcome(
        document_id=request.retained_source.document_id,
        source_file_id=request.retained_source.source_file_id,
        provider_name=request.provider_name,
        provider_job_id=request.provider_job_id,
        provider_request_id=request.provider_request_id,
        integration_terminal_phase=OrchestrationPhase.FAILED,
        provider_terminal_status=None,
        orchestration_outcome=None,
        raw_result=result.raw_result,
        raw_result_storage_reference=raw_reference,
        raw_result_checksum_sha256=raw_checksum,
        raw_result_size_bytes=raw_size,
        elapsed_seconds=elapsed_seconds,
        poll_count=0,
        warnings=(),
        grant_id=f"provider-transport-shards:{result.shard_count}",
        grant_final_state=grant_state,
        revocation_succeeded=result.cleanup_safe,
        error=error,
        canonicalization=None,
    )


class ShardingAwareEndToEndProcessingIntegrationService(_BaseIntegrationService):
    """Preserve the single-job path unless the provider artifact exceeds 80 MiB."""

    async def process(self, request):
        provider_input = _provider_input_for(self)
        if provider_input is None:
            _diagnostic(
                "PDF_PROVIDER_TRANSPORT_SHARDING_DECISION",
                processing_attempt_id=request.processing_attempt_id,
                provider_job_id=request.provider_job_id,
                recognized_provider_input=False,
                sharding_required=False,
            )
            return await super().process(request)

        sharding_required = provider_transport_sharding_required(provider_input)
        _diagnostic(
            "PDF_PROVIDER_TRANSPORT_SHARDING_DECISION",
            processing_attempt_id=request.processing_attempt_id,
            provider_job_id=request.provider_job_id,
            recognized_provider_input=True,
            provider_input_size_bytes=provider_input.provider_byte_size,
            provider_input_page_count=provider_input.provider_page_count,
            shard_target_bytes=PROVIDER_TRANSPORT_SHARD_TARGET_BYTES,
            sharding_required=sharding_required,
        )
        if not sharding_required:
            return await super().process(request)
        if self.canonicalizer is None:
            raise ProviderTransportShardError(
                "provider transport sharding requires a canonicalizer"
            )

        started = self.monotonic()
        _diagnostic(
            "PDF_PROVIDER_TRANSPORT_SHARDING_STARTED",
            processing_attempt_id=request.processing_attempt_id,
            provider_job_id=request.provider_job_id,
            provider_input_size_bytes=provider_input.provider_byte_size,
            provider_input_page_count=provider_input.provider_page_count,
        )
        try:
            result = await run_provider_transport_shards(
                storage=self.orchestrator.storage,
                client=_raw_client_for(self),
                provider_input=provider_input,
                descriptor=request.retained_source,
                processing_attempt_id=request.processing_attempt_id,
                logical_provider_job_id=request.provider_job_id,
                logical_provider_request_id=request.provider_request_id or request.processing_attempt_id,
                result_profile=request.result_profile,
                provider_job_options=dict(request.provider_job_options),
                public_origin=self._origin_value,
                polling_policy=self.polling_policy,
                canonicalizer=self.canonicalizer,
                diagnostic=_diagnostic,
            )
        except Exception as exc:
            result = ProviderTransportShardRunResult(None, None, exc, True, False, 0)

        elapsed = max(0.0, self.monotonic() - started)
        outcome = _outcome_from_sharded_result(request, result, elapsed_seconds=elapsed)
        _diagnostic(
            "PDF_PROVIDER_TRANSPORT_SHARDING_TERMINAL",
            processing_attempt_id=request.processing_attempt_id,
            provider_job_id=request.provider_job_id,
            shard_count=result.shard_count,
            elapsed_seconds=round(elapsed, 6),
            succeeded=outcome.error is None,
            cleanup_safe=result.cleanup_safe,
        )
        return outcome


def install_provider_transport_sharding_compat() -> None:
    """Replace only pdf_ingestion's integration-service constructor."""
    global _INSTALLED
    if _INSTALLED:
        return
    from app.processing import pdf_ingestion

    current = pdf_ingestion.EndToEndProcessingIntegrationService
    if current is ShardingAwareEndToEndProcessingIntegrationService:
        _INSTALLED = True
        return
    if current is not _BaseIntegrationService:
        raise RuntimeError("provider transport sharding integration service has an unexpected base")
    pdf_ingestion.EndToEndProcessingIntegrationService = ShardingAwareEndToEndProcessingIntegrationService
    _INSTALLED = True


__all__ = ["ShardingAwareEndToEndProcessingIntegrationService", "install_provider_transport_sharding_compat"]
