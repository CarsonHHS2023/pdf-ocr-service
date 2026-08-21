"""Final ownership split for 20 MiB Provider transport sharding.

Atlas owns transport sharding, source access, lifecycle, and merge semantics.
Modal owns compute fanout. The effective Staging artifact therefore submits
Provider transport shards strictly sequentially and contains no Atlas task fanout.
"""
from __future__ import annotations

from pathlib import Path

try:
    from scripts.apply_provider_20mib_observability_v4 import main as apply_v4
except ImportError:
    from apply_provider_20mib_observability_v4 import main as apply_v4


SHARDING_PATH = Path("app/processing/pdf_provider_sharding.py")
COMPAT_PATH = Path("app/processing/pdf_provider_sharding_compat.py")


def _replace_once(source: str, old: str, new: str, *, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one source match, found {count}")
    return source.replace(old, new, 1)


def _replace_function(
    source: str,
    *,
    start_marker: str,
    end_marker: str,
    replacement: str,
    label: str,
) -> str:
    if source.count(start_marker) != 1 or source.count(end_marker) != 1:
        raise RuntimeError(f"{label}: function boundary is not unique")
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[:start] + replacement.rstrip() + "\n\n" + source[end + 1 :]


def _patch_sequential_contract() -> None:
    source = SHARDING_PATH.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        "PROVIDER_TRANSPORT_SHARD_MAX_BYTES = 24 * _MIB\n"
        "PROVIDER_TRANSPORT_SHARD_MAX_CONCURRENCY = 5",
        "PROVIDER_TRANSPORT_SHARD_MAX_BYTES = 24 * _MIB\n"
        'PROVIDER_TRANSPORT_SHARD_EXECUTION_MODE = "sequential"',
        label="sequential transport execution constant",
    )
    source = source.replace(
        '            "provider_transport_shard_max_concurrency": '
        'PROVIDER_TRANSPORT_SHARD_MAX_CONCURRENCY,\n',
        '            "provider_transport_shard_execution_mode": '
        'PROVIDER_TRANSPORT_SHARD_EXECUTION_MODE,\n',
        1,
    )
    if '    "PROVIDER_TRANSPORT_SHARD_EXECUTION_MODE",\n' not in source:
        source = _replace_once(
            source,
            '    "PROVIDER_TRANSPORT_SHARD_MAX_BYTES",\n',
            '    "PROVIDER_TRANSPORT_SHARD_MAX_BYTES",\n'
            '    "PROVIDER_TRANSPORT_SHARD_EXECUTION_MODE",\n',
            label="sequential execution export",
        )

    required_source_access = (
        "build_provider_input_source_url_factory",
        "PROVIDER_SOURCE_ACCESS_TTL_SECONDS",
        "from datetime import timedelta",
    )
    missing = [marker for marker in required_source_access if marker not in source]
    if missing:
        raise RuntimeError(f"sequential shard source-access imports are missing: {missing}")

    runner = '''async def run_provider_transport_shards(
    *,
    storage: Any,
    client: Any,
    provider_input: Any,
    descriptor: RetainedSourceDescriptor,
    processing_attempt_id: str,
    logical_provider_job_id: str,
    logical_provider_request_id: str,
    result_profile: str,
    provider_job_options: dict[str, Any],
    public_origin: str | None,
    polling_policy: PollingPolicy,
    canonicalizer: Any,
    diagnostic: Diagnostic,
    target_bytes: int = PROVIDER_TRANSPORT_SHARD_TARGET_BYTES,
    max_bytes: int = PROVIDER_TRANSPORT_SHARD_MAX_BYTES,
) -> ProviderTransportShardRunResult:
    """Submit transport shards sequentially; Modal owns compute fanout."""
    plans = plan_provider_input_shards(
        storage,
        provider_input,
        target_bytes=target_bytes,
        max_bytes=max_bytes,
    )
    if not plans:
        raise ProviderTransportShardError("provider transport sharding was not required")

    diagnostic(
        "PDF_PROVIDER_SHARD_PLAN_CREATED",
        processing_attempt_id=processing_attempt_id,
        provider_input_size_bytes=_provider_byte_size(provider_input),
        provider_input_page_count=_provider_page_count(provider_input),
        shard_count=len(plans),
        shard_target_bytes=target_bytes,
        shard_max_bytes=max_bytes,
        shard_execution_mode=PROVIDER_TRANSPORT_SHARD_EXECUTION_MODE,
    )

    cleanup_safe = True
    submission_started = False
    evidence: list[ProviderShardEvidence] = []
    from app.processing import pdf_geometry_integration as integration

    def elapsed_seconds(started: float | None) -> float | None:
        if started is None:
            return None
        return round(asyncio.get_running_loop().time() - started, 6)

    def failure_fields(error: Exception) -> dict[str, object]:
        orchestration_error = (
            error.orchestration_error if isinstance(error, IntegrationError) else None
        )
        progress = getattr(orchestration_error, "last_provider_progress", None)
        return {
            "error_category": (
                error.category.value if isinstance(error, IntegrationError)
                else type(error).__name__
            ),
            "error_phase": getattr(
                getattr(orchestration_error, "phase", None), "value", None
            ),
            "provider_status": getattr(orchestration_error, "provider_status", None),
            "provider_request_id": getattr(
                orchestration_error, "provider_request_id", None
            ),
            "poll_count": getattr(orchestration_error, "poll_count", 0),
            "retryable": getattr(orchestration_error, "retryable", False),
            "last_successful_poll_elapsed_seconds": getattr(
                orchestration_error,
                "last_successful_poll_elapsed_seconds",
                None,
            ),
            "provider_pages_total": getattr(progress, "pages_total", None),
            "provider_pages_completed": getattr(progress, "pages_completed", None),
            "provider_percent_complete": getattr(progress, "percent_complete", None),
        }

    def batch_terminal(*, failed_shards: int) -> None:
        diagnostic(
            "PDF_PROVIDER_SHARD_BATCH_TERMINAL",
            processing_attempt_id=processing_attempt_id,
            provider_job_id=logical_provider_job_id,
            shard_count=len(plans),
            succeeded_shards=len(evidence),
            failed_shards=failed_shards,
            cleanup_safe=cleanup_safe,
            submission_started=submission_started,
            shard_execution_mode=PROVIDER_TRANSPORT_SHARD_EXECUTION_MODE,
        )

    for plan in plans:
        shard_number = plan.shard_index + 1
        job_id = f"{logical_provider_job_id}-s{shard_number:03d}"
        request_id = f"{logical_provider_request_id}-s{shard_number:03d}"
        shard_input = None
        shard_submission_started = False
        request_started_at: float | None = None
        try:
            shard_input = materialize_provider_input_shard(
                storage,
                provider_input,
                plan,
                shard_count=len(plans),
                max_bytes=max_bytes,
            )
            actual_plan = replace(
                plan,
                serialized_size_bytes=_provider_byte_size(shard_input),
            )
            provider = integration.ProviderInputChecksumProvider(client, shard_input)
            orchestrator = integration.ProviderInputAwareProcessingOrchestrator(
                provider=provider,
                storage=storage,
                provider_input=shard_input,
            )
            grant_service = integration.ProviderInputGrantService(
                get_transport_grant_service(),
                shard_input,
            )
            shard_delivery = integration.provider_delivery_descriptor(shard_input)
            shard_source_url_factory = build_provider_input_source_url_factory(
                storage=storage,
                reference=shard_delivery.storage_reference,
                byte_size=shard_delivery.byte_size,
            )
            service = EndToEndProcessingIntegrationService(
                grant_service=grant_service,
                orchestrator=orchestrator,
                canonicalizer=None,
                public_origin=public_origin,
                source_transport_url_factory=shard_source_url_factory,
                source_access_ttl=timedelta(
                    seconds=PROVIDER_SOURCE_ACCESS_TTL_SECONDS,
                ),
                polling_policy=polling_policy,
            )
            request = ProcessingIntegrationRequest(
                processing_attempt_id=processing_attempt_id,
                correlation_id=request_id,
                retained_source=descriptor,
                provider_name="paddle-vl",
                provider_job_id=job_id,
                provider_request_id=request_id,
                result_profile=result_profile,
                provider_job_options=provider_job_options,
            )
            request_started_at = asyncio.get_running_loop().time()
            diagnostic(
                "PDF_PROVIDER_SHARD_REQUEST_STARTED",
                processing_attempt_id=processing_attempt_id,
                provider_job_id=job_id,
                shard_index=actual_plan.shard_index,
                shard_count=len(plans),
                provider_page_start=actual_plan.provider_page_start,
                provider_page_end=actual_plan.provider_page_end,
                provider_page_count=actual_plan.provider_page_count,
                shard_planned_size_bytes=plan.serialized_size_bytes,
                shard_size_bytes=actual_plan.serialized_size_bytes,
                shard_target_bytes=target_bytes,
                shard_execution_mode=PROVIDER_TRANSPORT_SHARD_EXECUTION_MODE,
            )
            shard_submission_started = True
            submission_started = True
            outcome = await service.process(request)
        except IntegrationError as exc:
            shard_cleanup_safe = _cleanup_safe_from_integration_error(exc)
            cleanup_safe = cleanup_safe and shard_cleanup_safe
            if shard_input is not None:
                _delete_shard_provider_input_if_safe(
                    storage,
                    shard_input,
                    cleanup_safe=shard_cleanup_safe,
                    diagnostic=diagnostic,
                    processing_attempt_id=processing_attempt_id,
                    provider_job_id=job_id,
                    shard_index=plan.shard_index,
                )
            diagnostic(
                "PDF_PROVIDER_SHARD_FAILED",
                processing_attempt_id=processing_attempt_id,
                provider_job_id=job_id,
                shard_index=plan.shard_index,
                cleanup_safe=shard_cleanup_safe,
                elapsed_seconds=elapsed_seconds(request_started_at),
                shard_execution_mode=PROVIDER_TRANSPORT_SHARD_EXECUTION_MODE,
                **failure_fields(exc),
            )
            batch_terminal(failed_shards=1)
            return ProviderTransportShardRunResult(
                None, None, exc, cleanup_safe, submission_started, len(plans)
            )
        except asyncio.CancelledError:
            shard_cleanup_safe = not shard_submission_started
            cleanup_safe = cleanup_safe and shard_cleanup_safe
            if shard_input is not None:
                _delete_shard_provider_input_if_safe(
                    storage,
                    shard_input,
                    cleanup_safe=shard_cleanup_safe,
                    diagnostic=diagnostic,
                    processing_attempt_id=processing_attempt_id,
                    provider_job_id=job_id,
                    shard_index=plan.shard_index,
                )
            diagnostic(
                "PDF_PROVIDER_SHARD_CANCELLED",
                processing_attempt_id=processing_attempt_id,
                provider_job_id=job_id,
                shard_index=plan.shard_index,
                submission_started=shard_submission_started,
                cleanup_safe=shard_cleanup_safe,
                elapsed_seconds=elapsed_seconds(request_started_at),
                shard_execution_mode=PROVIDER_TRANSPORT_SHARD_EXECUTION_MODE,
            )
            raise
        except Exception as exc:
            shard_cleanup_safe = not shard_submission_started
            cleanup_safe = cleanup_safe and shard_cleanup_safe
            if shard_input is not None:
                _delete_shard_provider_input_if_safe(
                    storage,
                    shard_input,
                    cleanup_safe=shard_cleanup_safe,
                    diagnostic=diagnostic,
                    processing_attempt_id=processing_attempt_id,
                    provider_job_id=job_id,
                    shard_index=plan.shard_index,
                )
            diagnostic(
                "PDF_PROVIDER_SHARD_FAILED",
                processing_attempt_id=processing_attempt_id,
                provider_job_id=job_id,
                shard_index=plan.shard_index,
                cleanup_safe=shard_cleanup_safe,
                elapsed_seconds=elapsed_seconds(request_started_at),
                shard_execution_mode=PROVIDER_TRANSPORT_SHARD_EXECUTION_MODE,
                **failure_fields(exc),
            )
            batch_terminal(failed_shards=1)
            return ProviderTransportShardRunResult(
                None, None, exc, cleanup_safe, submission_started, len(plans)
            )

        shard_cleanup_safe = bool(
            outcome.revocation_succeeded
            or outcome.grant_final_state is TransportGrantState.REVOKED
        )
        cleanup_safe = cleanup_safe and shard_cleanup_safe
        _delete_shard_provider_input_if_safe(
            storage,
            shard_input,
            cleanup_safe=shard_cleanup_safe,
            diagnostic=diagnostic,
            processing_attempt_id=processing_attempt_id,
            provider_job_id=job_id,
            shard_index=actual_plan.shard_index,
        )
        diagnostic(
            "PDF_PROVIDER_SHARD_TERMINAL",
            processing_attempt_id=processing_attempt_id,
            provider_job_id=job_id,
            shard_index=actual_plan.shard_index,
            provider_page_start=actual_plan.provider_page_start,
            provider_page_end=actual_plan.provider_page_end,
            provider_page_count=actual_plan.provider_page_count,
            shard_size_bytes=actual_plan.serialized_size_bytes,
            phase=outcome.integration_terminal_phase.value,
            provider_status=(
                outcome.provider_terminal_status.value
                if outcome.provider_terminal_status is not None else None
            ),
            error_category=(
                outcome.error.category.value if outcome.error is not None else None
            ),
            poll_count=outcome.poll_count,
            raw_result_retained=outcome.raw_result is not None,
            cleanup_safe=shard_cleanup_safe,
            elapsed_seconds=elapsed_seconds(request_started_at),
            shard_execution_mode=PROVIDER_TRANSPORT_SHARD_EXECUTION_MODE,
        )
        if outcome.error is not None:
            diagnostic(
                "PDF_PROVIDER_SHARD_FAILED",
                processing_attempt_id=processing_attempt_id,
                provider_job_id=job_id,
                shard_index=actual_plan.shard_index,
                cleanup_safe=shard_cleanup_safe,
                elapsed_seconds=elapsed_seconds(request_started_at),
                shard_execution_mode=PROVIDER_TRANSPORT_SHARD_EXECUTION_MODE,
                **failure_fields(outcome.error),
            )
            batch_terminal(failed_shards=1)
            return ProviderTransportShardRunResult(
                None,
                outcome.raw_result,
                outcome.error,
                cleanup_safe,
                submission_started,
                len(plans),
            )
        if outcome.raw_result is None:
            error = ProviderTransportShardError(
                "provider shard completed without retained raw result"
            )
            diagnostic(
                "PDF_PROVIDER_SHARD_FAILED",
                processing_attempt_id=processing_attempt_id,
                provider_job_id=job_id,
                shard_index=actual_plan.shard_index,
                cleanup_safe=shard_cleanup_safe,
                elapsed_seconds=elapsed_seconds(request_started_at),
                shard_execution_mode=PROVIDER_TRANSPORT_SHARD_EXECUTION_MODE,
                **failure_fields(error),
            )
            batch_terminal(failed_shards=1)
            return ProviderTransportShardRunResult(
                None, None, error, cleanup_safe, submission_started, len(plans)
            )
        evidence.append(
            ProviderShardEvidence(actual_plan, job_id, request_id, outcome.raw_result)
        )

    batch_terminal(failed_shards=0)
    try:
        merged = merge_provider_shard_results(
            storage,
            provider_input,
            evidence,
            logical_provider_job_id=logical_provider_job_id,
            logical_provider_request_id=logical_provider_request_id,
            target_bytes=target_bytes,
            max_bytes=max_bytes,
        )
        diagnostic(
            "PDF_PROVIDER_SHARDS_MERGED",
            processing_attempt_id=processing_attempt_id,
            provider_job_id=logical_provider_job_id,
            shard_count=len(plans),
            payload_size_bytes=merged.ingestion.payload_size_bytes,
            page_count_observed=(
                merged.ingestion.page_summary.page_count_observed
                if merged.ingestion.page_summary is not None else None
            ),
            shard_execution_mode=PROVIDER_TRANSPORT_SHARD_EXECUTION_MODE,
        )
        canonical = await asyncio.to_thread(canonicalizer.canonicalize, merged)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        diagnostic(
            "PDF_PROVIDER_SHARD_MERGE_FAILED",
            processing_attempt_id=processing_attempt_id,
            provider_job_id=logical_provider_job_id,
            shard_count=len(plans),
            error_category=type(exc).__name__,
            shard_execution_mode=PROVIDER_TRANSPORT_SHARD_EXECUTION_MODE,
        )
        return ProviderTransportShardRunResult(
            None, None, exc, cleanup_safe, submission_started, len(plans)
        )
    return ProviderTransportShardRunResult(
        canonical, merged, None, cleanup_safe, submission_started, len(plans)
    )
'''
    source = _replace_function(
        source,
        start_marker="async def run_provider_transport_shards(\n",
        end_marker="\ndef _delete_shard_provider_input_if_safe(\n",
        replacement=runner,
        label="sequential provider transport shard runner",
    )
    SHARDING_PATH.write_text(source, encoding="utf-8")

    compat = COMPAT_PATH.read_text(encoding="utf-8")
    compat = compat.replace(
        "            shard_max_concurrency=5,\n",
        '            shard_execution_mode="sequential",\n',
        1,
    )
    COMPAT_PATH.write_text(compat, encoding="utf-8")


def main() -> None:
    apply_v4()
    _patch_sequential_contract()
    print(
        "provider 20 MiB ownership split ready: atlas_transport=sequential "
        "modal_compute_fanout=external"
    )


if __name__ == "__main__":
    main()
