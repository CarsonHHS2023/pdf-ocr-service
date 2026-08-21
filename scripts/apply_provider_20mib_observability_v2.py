"""Apply the final 20 MiB Provider transport and observability contract.

The overlay runs after all existing Staging production-equivalent overlays. It
keeps the tested/deployed artifact deterministic while avoiding changes to the
Production branch until this PR is explicitly merged.
"""
from __future__ import annotations

from pathlib import Path


MIB = 1024 * 1024
SHARDING_PATH = Path("app/processing/pdf_provider_sharding.py")
COMPAT_PATH = Path("app/processing/pdf_provider_sharding_compat.py")
PREPROCESS_PATH = Path("app/processing/pdf_page_presentation_preprocess_compat.py")
INGESTION_PATH = Path("app/processing/pdf_ingestion.py")
TEST_SHARDING_PATH = Path("tests/test_pdf_provider_sharding.py")
TEST_COMPAT_PATH = Path("tests/test_pdf_provider_sharding_compat.py")


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
    if replacement in source:
        return source
    if source.count(start_marker) != 1 or source.count(end_marker) != 1:
        raise RuntimeError(f"{label}: function boundary is not unique")
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[:start] + replacement.rstrip() + "\n\n" + source[end + 1 :]


def _patch_transport_sharding() -> None:
    source = SHARDING_PATH.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        "PROVIDER_TRANSPORT_SHARD_TARGET_BYTES = 80 * _MIB\n"
        "PROVIDER_TRANSPORT_SHARD_MAX_BYTES = 95 * _MIB",
        "PROVIDER_TRANSPORT_SHARD_TARGET_BYTES = 20 * _MIB\n"
        "# The planner targets 20 MiB. A narrow materialization-only ceiling\n"
        "# tolerates PyMuPDF object-table/document-id serialization jitter.\n"
        "# Modal independently caps each GPU compute range at 20 MiB.\n"
        "PROVIDER_TRANSPORT_SHARD_MAX_BYTES = 24 * _MIB\n"
        "PROVIDER_TRANSPORT_SHARD_MAX_CONCURRENCY = 5",
        label="provider transport limits",
    )
    source = _replace_once(
        source,
        '            "provider_transport_shard_count": len(ordered),\n'
        '            "provider_transport_shards": [',
        '            "provider_transport_shard_count": len(ordered),\n'
        '            "provider_transport_shard_max_concurrency": '
        'PROVIDER_TRANSPORT_SHARD_MAX_CONCURRENCY,\n'
        '            "provider_transport_shards": [',
        label="provider shard provenance concurrency",
    )

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
    """Run <=20 MiB planned transport shards with bounded concurrency."""
    plans = plan_provider_input_shards(
        storage,
        provider_input,
        target_bytes=target_bytes,
        max_bytes=max_bytes,
    )
    if not plans:
        raise ProviderTransportShardError("provider transport sharding was not required")

    max_concurrency = max(
        1,
        min(PROVIDER_TRANSPORT_SHARD_MAX_CONCURRENCY, len(plans)),
    )
    diagnostic(
        "PDF_PROVIDER_SHARD_PLAN_CREATED",
        processing_attempt_id=processing_attempt_id,
        provider_input_size_bytes=_provider_byte_size(provider_input),
        provider_input_page_count=_provider_page_count(provider_input),
        shard_count=len(plans),
        shard_target_bytes=target_bytes,
        shard_max_bytes=max_bytes,
        shard_max_concurrency=max_concurrency,
    )

    from app.processing import pdf_geometry_integration as integration

    semaphore = asyncio.Semaphore(max_concurrency)

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

    async def run_one(plan: ProviderInputShardPlan):
        shard_number = plan.shard_index + 1
        job_id = f"{logical_provider_job_id}-s{shard_number:03d}"
        request_id = f"{logical_provider_request_id}-s{shard_number:03d}"
        shard_input = None
        submission_started = False
        started = asyncio.get_running_loop().time()

        async with semaphore:
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
                service = EndToEndProcessingIntegrationService(
                    grant_service=grant_service,
                    orchestrator=orchestrator,
                    canonicalizer=None,
                    public_origin=public_origin,
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
                    shard_max_concurrency=max_concurrency,
                )
                submission_started = True
                try:
                    outcome = await service.process(request)
                except IntegrationError as exc:
                    shard_cleanup_safe = _cleanup_safe_from_integration_error(exc)
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
                        "PDF_PROVIDER_SHARD_FAILED",
                        processing_attempt_id=processing_attempt_id,
                        provider_job_id=job_id,
                        shard_index=actual_plan.shard_index,
                        cleanup_safe=shard_cleanup_safe,
                        elapsed_seconds=round(
                            asyncio.get_running_loop().time() - started, 6
                        ),
                        **failure_fields(exc),
                    )
                    return (
                        None,
                        None,
                        exc,
                        shard_cleanup_safe,
                        submission_started,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    diagnostic(
                        "PDF_PROVIDER_SHARD_FAILED",
                        processing_attempt_id=processing_attempt_id,
                        provider_job_id=job_id,
                        shard_index=actual_plan.shard_index,
                        cleanup_safe=False,
                        elapsed_seconds=round(
                            asyncio.get_running_loop().time() - started, 6
                        ),
                        **failure_fields(exc),
                    )
                    return (None, None, exc, False, submission_started)

                shard_cleanup_safe = bool(
                    outcome.revocation_succeeded
                    or outcome.grant_final_state is TransportGrantState.REVOKED
                )
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
                        if outcome.provider_terminal_status is not None
                        else None
                    ),
                    error_category=(
                        outcome.error.category.value
                        if outcome.error is not None else None
                    ),
                    poll_count=outcome.poll_count,
                    raw_result_retained=outcome.raw_result is not None,
                    cleanup_safe=shard_cleanup_safe,
                    elapsed_seconds=round(
                        asyncio.get_running_loop().time() - started, 6
                    ),
                )
                if outcome.error is not None:
                    return (
                        None,
                        outcome.raw_result,
                        outcome.error,
                        shard_cleanup_safe,
                        submission_started,
                    )
                if outcome.raw_result is None:
                    return (
                        None,
                        None,
                        ProviderTransportShardError(
                            "provider shard completed without retained raw result"
                        ),
                        shard_cleanup_safe,
                        submission_started,
                    )
                return (
                    ProviderShardEvidence(
                        actual_plan,
                        job_id,
                        request_id,
                        outcome.raw_result,
                    ),
                    outcome.raw_result,
                    None,
                    shard_cleanup_safe,
                    submission_started,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                cleanup_safe = not submission_started
                if shard_input is not None:
                    _delete_shard_provider_input_if_safe(
                        storage,
                        shard_input,
                        cleanup_safe=cleanup_safe,
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
                    cleanup_safe=cleanup_safe,
                    elapsed_seconds=round(
                        asyncio.get_running_loop().time() - started, 6
                    ),
                    **failure_fields(exc),
                )
                return (None, None, exc, cleanup_safe, submission_started)

    tasks = [asyncio.create_task(run_one(plan)) for plan in plans]
    try:
        results = await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise

    cleanup_safe = all(bool(item[3]) for item in results)
    submission_started = any(bool(item[4]) for item in results)
    evidence: list[ProviderShardEvidence] = []
    first_raw_result = None
    first_error: Exception | None = None
    succeeded_shards = 0
    failed_shards = 0
    for shard_evidence, raw_result, error, _safe, _started in results:
        if first_raw_result is None and raw_result is not None:
            first_raw_result = raw_result
        if error is not None:
            failed_shards += 1
            if first_error is None:
                first_error = error
            continue
        if shard_evidence is not None:
            evidence.append(shard_evidence)
            succeeded_shards += 1

    evidence.sort(key=lambda item: item.plan.shard_index)
    diagnostic(
        "PDF_PROVIDER_SHARD_BATCH_TERMINAL",
        processing_attempt_id=processing_attempt_id,
        provider_job_id=logical_provider_job_id,
        shard_count=len(plans),
        succeeded_shards=succeeded_shards,
        failed_shards=failed_shards,
        cleanup_safe=cleanup_safe,
        submission_started=submission_started,
        shard_max_concurrency=max_concurrency,
    )
    if first_error is not None:
        return ProviderTransportShardRunResult(
            None,
            first_raw_result,
            first_error,
            cleanup_safe,
            submission_started,
            len(plans),
        )

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
        )
        canonical = await asyncio.to_thread(canonicalizer.canonicalize, merged)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
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
        label="bounded concurrent provider shard runner",
    )
    SHARDING_PATH.write_text(source, encoding="utf-8")


def _patch_provider_diagnostics() -> None:
    source = COMPAT_PATH.read_text(encoding="utf-8")
    source = source.replace(
        "Preserve the single-job path unless the provider artifact exceeds 80 MiB.",
        "Preserve the single-job path unless the provider artifact exceeds 20 MiB.",
    )
    helper = '''def _provider_page_route_counts(provider_input: Any) -> dict[str, int | None]:
    manifest = getattr(provider_input, "presentation_manifest", None)
    pages = manifest.get("pages") if isinstance(manifest, Mapping) else None
    if isinstance(pages, list) and pages:
        presentation = native_text = provider = 0
        for page in pages:
            if not isinstance(page, Mapping):
                continue
            route = page.get("ocr_route")
            if route == "skipped_presentation_image":
                presentation += 1
            elif route == "native_pdf_text":
                native_text += 1
            elif route == "modal_paddle_ocr":
                provider += 1
        return {
            "full_document_page_count": len(pages),
            "presentation_page_count": presentation,
            "native_text_page_count": native_text,
            "provider_route_page_count": provider,
            "provider_excluded_page_count": presentation + native_text,
        }

    provider_count = getattr(provider_input, "provider_page_count", None)
    return {
        "full_document_page_count": None,
        "presentation_page_count": _presentation_page_count(provider_input),
        "native_text_page_count": None,
        "provider_route_page_count": (
            provider_count
            if isinstance(provider_count, int) and not isinstance(provider_count, bool)
            else None
        ),
        "provider_excluded_page_count": None,
    }
'''
    anchor = "def _delivery_is_full_render(provider_input: Any, delivery: Any) -> bool:\n"
    if helper not in source:
        if source.count(anchor) != 1:
            raise RuntimeError("provider route-count helper anchor is not unique")
        source = source.replace(anchor, helper + "\n\n" + anchor, 1)

    source = _replace_once(
        source,
        "        presentation_page_count = _presentation_page_count(provider_input)\n"
        "        sharding_required = provider_transport_sharding_required(provider_input)",
        "        route_counts = _provider_page_route_counts(provider_input)\n"
        "        presentation_page_count = route_counts[\"presentation_page_count\"]\n"
        "        sharding_required = provider_transport_sharding_required(provider_input)",
        label="provider delivery route counts",
    )
    source = _replace_once(
        source,
        "            presentation_page_count=presentation_page_count,\n"
        "            delivery_is_full_render=delivery_is_full_render,",
        "            presentation_page_count=presentation_page_count,\n"
        "            native_text_page_count=route_counts[\"native_text_page_count\"],\n"
        "            full_document_page_count=route_counts[\"full_document_page_count\"],\n"
        "            provider_excluded_page_count=route_counts[\"provider_excluded_page_count\"],\n"
        "            provider_route_page_count=route_counts[\"provider_route_page_count\"],\n"
        "            provider_input_type=type(provider_input).__name__,\n"
        "            delivery_is_full_render=delivery_is_full_render,",
        label="provider delivery detailed route diagnostics",
    )
    source = _replace_once(
        source,
        "            max_bytes=PROVIDER_TRANSPORT_SHARD_MAX_BYTES,\n"
        "            route=\"sharded\" if sharding_required else \"single\",",
        "            max_bytes=PROVIDER_TRANSPORT_SHARD_MAX_BYTES,\n"
        "            shard_max_concurrency=5,\n"
        "            route=\"sharded\" if sharding_required else \"single\",",
        label="provider sharding concurrency diagnostic",
    )
    COMPAT_PATH.write_text(source, encoding="utf-8")


def _patch_presentation_native_counts() -> None:
    source = PREPROCESS_PATH.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        "        provider_page_count = len(provider_map)\n"
        "        presentation_count = page_count - provider_page_count",
        "        provider_page_count = len(provider_map)\n"
        "        native_text_count = sum(\n"
        "            1 for decision in decisions\n"
        "            if bool(decision.get(\"native_text_accepted\"))\n"
        "        )\n"
        "        presentation_count = sum(\n"
        "            1 for decision in decisions\n"
        "            if bool(decision.get(\"skip_ocr\"))\n"
        "            and not bool(decision.get(\"native_text_accepted\"))\n"
        "        )\n"
        "        excluded_from_provider_count = presentation_count + native_text_count\n"
        "        if provider_page_count + excluded_from_provider_count != page_count:\n"
        "            raise RuntimeError(\"page route counts do not cover the document\")",
        label="presentation/native route counting",
    )
    source = _replace_once(
        source,
        "        elif presentation_count == 0:\n            provider_put = render_put",
        "        elif excluded_from_provider_count == 0:\n            provider_put = render_put",
        label="provider subset reuse decision",
    )
    source = _replace_once(
        source,
        '            "presentation_page_count": presentation_count,\n'
        '            "pages": page_entries,',
        '            "presentation_page_count": presentation_count,\n'
        '            "native_text_page_count": native_text_count,\n'
        '            "provider_excluded_page_count": excluded_from_provider_count,\n'
        '            "pages": page_entries,',
        label="presentation/native manifest counters",
    )
    source = _replace_once(
        source,
        "            presentation_page_count=presentation_count,\n        )",
        "            presentation_page_count=presentation_count,\n"
        "            native_text_page_count=native_text_count,\n"
        "            provider_excluded_page_count=excluded_from_provider_count,\n"
        "        )",
        label="provider page-map route diagnostics",
    )
    PREPROCESS_PATH.write_text(source, encoding="utf-8")


def _install_classification_observability() -> None:
    source = INGESTION_PATH.read_text(encoding="utf-8")
    install = (
        "from app.processing.pdf_page_classification_observability_compat import (\n"
        "    install_page_classification_observability_compat,\n"
        ")\n\n"
        "install_page_classification_observability_compat()\n\n"
    )
    if install not in source:
        anchor = 'logger = logging.getLogger("uvicorn.error")\n'
        if source.count(anchor) != 1:
            raise RuntimeError("classification observability install anchor is not unique")
        source = source.replace(anchor, install + anchor, 1)
    INGESTION_PATH.write_text(source, encoding="utf-8")


def _patch_existing_tests() -> None:
    source = TEST_SHARDING_PATH.read_text(encoding="utf-8")
    source = source.replace(
        "assert PROVIDER_TRANSPORT_SHARD_TARGET_BYTES == 80 * 1024 * 1024",
        "assert PROVIDER_TRANSPORT_SHARD_TARGET_BYTES == 20 * 1024 * 1024",
    )
    source = source.replace(
        "assert PROVIDER_TRANSPORT_SHARD_MAX_BYTES == 95 * 1024 * 1024",
        "assert PROVIDER_TRANSPORT_SHARD_MAX_BYTES == 24 * 1024 * 1024",
    )
    TEST_SHARDING_PATH.write_text(source, encoding="utf-8")

    source = TEST_COMPAT_PATH.read_text(encoding="utf-8")
    for old, new in (
        ("provider_size=70 * _MIB", "provider_size=19 * _MIB"),
        ('assert delivery["provider_byte_size"] == 70 * _MIB', 'assert delivery["provider_byte_size"] == 19 * _MIB'),
        ("provider_size=81 * _MIB", "provider_size=21 * _MIB"),
        ("byte_size=81 * _MIB", "byte_size=21 * _MIB"),
        ("full_size=80 * _MIB", "full_size=20 * _MIB"),
        ("byte_size=80 * _MIB", "byte_size=20 * _MIB"),
    ):
        source = source.replace(old, new)
    TEST_COMPAT_PATH.write_text(source, encoding="utf-8")


def main() -> None:
    _patch_transport_sharding()
    _patch_provider_diagnostics()
    _patch_presentation_native_counts()
    _install_classification_observability()
    _patch_existing_tests()
    print(
        "provider runtime overlay ready: transport_target_mib=20 "
        "materialization_safety_mib=24 transport_concurrency=5 "
        "presentation_native_counts=separate classification_diagnostics=detailed"
    )


if __name__ == "__main__":
    main()
