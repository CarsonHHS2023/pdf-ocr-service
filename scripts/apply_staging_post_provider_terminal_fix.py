"""Keep logical Provider terminal status truthful for all post-Provider failures.

Staging-only follow-up to PR #17. It preserves ProcessingIntegrationOutcome
semantics and records explicit internal evidence that every Provider shard
completed before merge/canonicalization post-processing begins. Only logical
terminal diagnostics consume that evidence.
"""
from __future__ import annotations

from pathlib import Path


SHARDING_PATH = Path("app/processing/pdf_provider_sharding.py")
SHARDING_COMPAT_PATH = Path("app/processing/pdf_provider_sharding_compat.py")
TEST_REVIEW_PATH = Path("tests/test_provider_20mib_review_fixes.py")
TEST_DEPLOYMENT_PATH = Path("tests/test_staging_deployment_contract.py")


def _replace_once(source: str, old: str, new: str, *, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one source match, found {count}")
    return source.replace(old, new, 1)


def _patch_shard_run_phase_evidence() -> None:
    source = SHARDING_PATH.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        "    shard_count: int = 0\n    poll_count: int = 0\n",
        "    shard_count: int = 0\n    poll_count: int = 0\n"
        "    provider_phase_completed: bool = False\n",
        label="shard run Provider-phase evidence field",
    )

    # These are the only three returns after the sequential Provider loop has
    # completed successfully: merge failure, canonicalization failure, success.
    merge_failure = '''        return ProviderTransportShardRunResult(\n            None, None, exc, cleanup_safe, submission_started, len(plans),\n            poll_count=total_poll_count,\n        )\n\n    diagnostic(\n        "PDF_PROVIDER_SHARDS_MERGED",\n'''
    source = _replace_once(
        source,
        merge_failure,
        '''        return ProviderTransportShardRunResult(\n            None, None, exc, cleanup_safe, submission_started, len(plans),\n            poll_count=total_poll_count,\n            provider_phase_completed=True,\n        )\n\n    diagnostic(\n        "PDF_PROVIDER_SHARDS_MERGED",\n''',
        label="merge-failure Provider-phase evidence",
    )

    canonical_failure = '''        return ProviderTransportShardRunResult(\n            None, merged, exc, cleanup_safe, submission_started, len(plans),\n            poll_count=total_poll_count,\n        )\n    return ProviderTransportShardRunResult(\n        canonical, merged, None, cleanup_safe, submission_started, len(plans),\n        poll_count=total_poll_count,\n    )\n'''
    source = _replace_once(
        source,
        canonical_failure,
        '''        return ProviderTransportShardRunResult(\n            None, merged, exc, cleanup_safe, submission_started, len(plans),\n            poll_count=total_poll_count,\n            provider_phase_completed=True,\n        )\n    return ProviderTransportShardRunResult(\n        canonical, merged, None, cleanup_safe, submission_started, len(plans),\n        poll_count=total_poll_count,\n        provider_phase_completed=True,\n    )\n''',
        label="canonical/success Provider-phase evidence",
    )
    SHARDING_PATH.write_text(source, encoding="utf-8")


def _patch_logical_terminal_diagnostics() -> None:
    source = SHARDING_COMPAT_PATH.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        "def _logical_terminal_diagnostic_fields(outcome: Any) -> dict[str, object]:\n",
        "def _logical_terminal_diagnostic_fields(\n"
        "    outcome: Any,\n"
        "    *,\n"
        "    provider_phase_completed: bool = False,\n"
        ") -> dict[str, object]:\n",
        label="logical terminal Provider-phase evidence parameter",
    )
    source = _replace_once(
        source,
        '''    elif (\n        isinstance(outcome.error, IntegrationError)\n        and outcome.error.category is IntegrationErrorCategory.CANONICALIZATION_FAILURE\n        and outcome.raw_result is not None\n    ):\n        # Merged-result canonicalization runs only after every Provider shard\n        # completed. Keep the outcome untouched and enrich only diagnostics.\n        fields["provider_status"] = ProviderLifecycleStatus.PROVIDER_COMPLETED.value\n''',
        '''    elif provider_phase_completed:\n        # The sequential Provider loop completed before merge/canonicalization\n        # post-processing began. Keep outcome semantics untouched and enrich only\n        # the logical terminal diagnostic for failures in that later phase.\n        fields["provider_status"] = ProviderLifecycleStatus.PROVIDER_COMPLETED.value\n''',
        label="logical terminal post-Provider status rule",
    )
    source = _replace_once(
        source,
        "        failure_fields = _logical_terminal_diagnostic_fields(outcome)\n",
        "        failure_fields = _logical_terminal_diagnostic_fields(\n"
        "            outcome,\n"
        "            provider_phase_completed=result.provider_phase_completed,\n"
        "        )\n",
        label="logical terminal runtime evidence wiring",
    )
    SHARDING_COMPAT_PATH.write_text(source, encoding="utf-8")


def _patch_existing_canonicalization_runtime_fixture() -> None:
    source = TEST_REVIEW_PATH.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        '            error=PdfCanonicalizationError("canonicalization failed after merge"),\n'
        '            cleanup_safe=True,\n'
        '            submission_started=True,\n'
        '            shard_count=2,\n'
        '            poll_count=16,\n',
        '            error=PdfCanonicalizationError("canonicalization failed after merge"),\n'
        '            cleanup_safe=True,\n'
        '            submission_started=True,\n'
        '            shard_count=2,\n'
        '            poll_count=16,\n'
        '            provider_phase_completed=True,\n',
        label="canonicalization runtime fixture Provider-phase evidence",
    )
    TEST_REVIEW_PATH.write_text(source, encoding="utf-8")


def _append_runtime_regressions() -> None:
    source = TEST_REVIEW_PATH.read_text(encoding="utf-8")
    marker = "def test_shard_merge_failure_reports_completed_provider_phase_without_changing_outcome("
    if marker in source:
        return
    block = r'''


def test_shard_merge_failure_reports_completed_provider_phase_without_changing_outcome(
    monkeypatch,
) -> None:
    plan = ProviderInputShardPlan(0, 0, 0, 1, 1024)
    shard_input = SimpleNamespace(
        provider_byte_size=1024,
        provider_page_count=1,
        provider_storage_reference=SimpleNamespace(value="merge-failure-shard"),
        provider_checksum_sha256="d" * 64,
        provider_filename="merge-failure-shard.pdf",
        media_type="application/pdf",
        preprocessing=None,
    )
    monkeypatch.setattr(sharding, "plan_provider_input_shards", lambda *a, **k: (plan,))
    monkeypatch.setattr(
        sharding,
        "materialize_provider_input_shard",
        lambda *a, **k: shard_input,
    )

    from app.processing import pdf_geometry_integration as integration

    monkeypatch.setattr(
        integration,
        "ProviderInputChecksumProvider",
        lambda client, provider_input: SimpleNamespace(),
    )
    monkeypatch.setattr(
        integration,
        "ProviderInputAwareProcessingOrchestrator",
        lambda **kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        integration,
        "ProviderInputGrantService",
        lambda *args, **kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        integration,
        "provider_delivery_descriptor",
        lambda provider_input: SimpleNamespace(
            storage_reference=provider_input.provider_storage_reference,
            byte_size=provider_input.provider_byte_size,
        ),
    )
    monkeypatch.setattr(sharding, "get_transport_grant_service", lambda: SimpleNamespace())
    monkeypatch.setattr(
        sharding,
        "build_provider_input_source_url_factory",
        lambda **kwargs: object(),
    )

    class FakeService:
        def __init__(self, **kwargs):
            pass

        async def process(self, request):
            return SimpleNamespace(
                revocation_succeeded=True,
                grant_final_state=None,
                integration_terminal_phase=SimpleNamespace(value="raw_result_retained"),
                provider_terminal_status=SimpleNamespace(value="completed"),
                error=None,
                poll_count=4,
                raw_result=SimpleNamespace(name="raw-before-merge-failure"),
            )

    monkeypatch.setattr(sharding, "EndToEndProcessingIntegrationService", FakeService)

    def fail_merge(*args, **kwargs):
        raise RuntimeError("merged result assembly failed")

    monkeypatch.setattr(sharding, "merge_provider_shard_results", fail_merge)
    diagnostics: list[tuple[str, dict[str, object]]] = []
    result = asyncio.run(
        sharding.run_provider_transport_shards(
            storage=SimpleNamespace(delete=lambda reference: None),
            client=SimpleNamespace(),
            provider_input=SimpleNamespace(
                provider_byte_size=21 * _MIB,
                provider_page_count=1,
            ),
            descriptor=SimpleNamespace(),
            processing_attempt_id="attempt-merge-terminal",
            logical_provider_job_id="job-merge-terminal",
            logical_provider_request_id="request-merge-terminal",
            result_profile="full",
            provider_job_options={},
            public_origin=None,
            polling_policy=SimpleNamespace(),
            canonicalizer=SimpleNamespace(),
            diagnostic=lambda event, **fields: diagnostics.append((event, fields)),
        )
    )

    assert isinstance(result.error, RuntimeError)
    assert result.raw_result is None
    assert result.canonicalization is None
    assert result.poll_count == 4
    assert result.provider_phase_completed is True
    assert any(event == "PDF_PROVIDER_SHARD_MERGE_FAILED" for event, _ in diagnostics)

    terminal_diagnostics: list[tuple[str, dict[str, object]]] = []
    provider_input = SimpleNamespace(provider_page_count=1, byte_size=21 * _MIB)
    delivery = SimpleNamespace(byte_size=21 * _MIB)
    monkeypatch.setattr(sharding_compat, "_provider_input_for", lambda service: provider_input)
    monkeypatch.setattr(sharding_compat, "provider_delivery_descriptor", lambda value: delivery)
    monkeypatch.setattr(
        sharding_compat,
        "_provider_page_route_counts",
        lambda value: {
            "presentation_page_count": 0,
            "native_text_page_count": 0,
            "full_document_page_count": 1,
            "provider_excluded_page_count": 0,
            "provider_route_page_count": 1,
        },
    )
    monkeypatch.setattr(sharding_compat, "provider_transport_sharding_required", lambda value: True)
    monkeypatch.setattr(sharding_compat, "_delivery_is_full_render", lambda *args: False)
    monkeypatch.setattr(sharding_compat, "_raw_client_for", lambda service: object())
    monkeypatch.setattr(
        sharding_compat,
        "_diagnostic",
        lambda event, **fields: terminal_diagnostics.append((event, fields)),
    )

    async def fake_run_provider_transport_shards(**kwargs):
        return result

    monkeypatch.setattr(
        sharding_compat,
        "run_provider_transport_shards",
        fake_run_provider_transport_shards,
    )
    ticks = iter((30.0, 31.25))
    service = SimpleNamespace(
        orchestrator=SimpleNamespace(storage=SimpleNamespace()),
        canonicalizer=object(),
        monotonic=lambda: next(ticks),
        _origin_value=None,
        polling_policy=SimpleNamespace(),
    )
    request = SimpleNamespace(
        retained_source=SimpleNamespace(
            document_id="document-merge-terminal",
            source_file_id="source-merge-terminal",
        ),
        processing_attempt_id="attempt-merge-terminal",
        provider_name="paddle-vl",
        provider_job_id="job-merge-terminal",
        provider_request_id="request-merge-terminal",
        result_profile="full",
        provider_job_options={},
    )
    outcome = asyncio.run(
        sharding_compat.ShardingAwareEndToEndProcessingIntegrationService.process(
            service,
            request,
        )
    )
    terminal = next(
        fields
        for event, fields in terminal_diagnostics
        if event == "PDF_PROVIDER_TRANSPORT_SHARDING_TERMINAL"
    )

    # Outcome remains bounded UNEXPECTED; only diagnostic Provider state is enriched.
    assert outcome.provider_terminal_status is None
    assert outcome.error is not None
    assert outcome.error.category is IntegrationErrorCategory.UNEXPECTED
    assert outcome.raw_result is None
    assert outcome.canonicalization is None
    assert outcome.poll_count == 4
    assert terminal["provider_status"] == "provider_completed"
    assert terminal["provider_request_id"] == "request-merge-terminal"
    assert terminal["error_category"] == "unexpected_integration_failure"
    assert terminal["poll_count"] == 4
    assert terminal["raw_result_retained"] is False
    assert terminal["canonicalization_ready"] is False
    assert terminal["succeeded"] is False


def test_provider_phase_evidence_does_not_mark_early_shard_failure_completed() -> None:
    error = RuntimeError("provider failed before all shards completed")
    result = sharding.ProviderTransportShardRunResult(
        canonicalization=None,
        raw_result=None,
        error=error,
        cleanup_safe=False,
        submission_started=True,
        shard_count=2,
        poll_count=3,
        provider_phase_completed=False,
    )
    outcome = sharding_compat._outcome_from_sharded_result(
        SimpleNamespace(
            retained_source=SimpleNamespace(
                document_id="document-early-failure",
                source_file_id="source-early-failure",
            ),
            provider_name="paddle-vl",
            provider_job_id="job-early-failure",
            provider_request_id="request-early-failure",
        ),
        result,
        elapsed_seconds=1.0,
    )
    fields = sharding_compat._logical_terminal_diagnostic_fields(
        outcome,
        provider_phase_completed=result.provider_phase_completed,
    )
    assert fields["provider_status"] is None
    assert fields["poll_count"] == 3
'''
    TEST_REVIEW_PATH.write_text(source.rstrip() + block.rstrip() + "\n", encoding="utf-8")


def _patch_authoritative_deploy_contract() -> None:
    source = TEST_DEPLOYMENT_PATH.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        '    assert "IntegrationErrorCategory.CANONICALIZATION_FAILURE" in helper\n'
        '    assert "ProviderLifecycleStatus.PROVIDER_COMPLETED.value" in helper\n\n'
        '    process = inspect.getsource(\n',
        '    assert "provider_phase_completed" in helper\n'
        '    assert "ProviderLifecycleStatus.PROVIDER_COMPLETED.value" in helper\n\n'
        '    runner = inspect.getsource(sharding.run_provider_transport_shards)\n'
        '    assert "provider_phase_completed=True" in runner\n\n'
        '    process = inspect.getsource(\n',
        label="staging deploy post-Provider terminal evidence contract",
    )
    source = _replace_once(
        source,
        '    assert "failure_fields = _logical_terminal_diagnostic_fields(outcome)" in process\n',
        '    assert "provider_phase_completed=result.provider_phase_completed" in process\n',
        label="staging deploy runtime evidence wiring contract",
    )
    TEST_DEPLOYMENT_PATH.write_text(source, encoding="utf-8")


def main() -> None:
    _patch_shard_run_phase_evidence()
    _patch_logical_terminal_diagnostics()
    _patch_existing_canonicalization_runtime_fixture()
    _append_runtime_regressions()
    _patch_authoritative_deploy_contract()
    print(
        "staging post-Provider terminal diagnostic fix ready: "
        "provider_phase_completed=evidence outcome_contract=unchanged"
    )


if __name__ == "__main__":
    main()
