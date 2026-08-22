"""Keep logical Provider terminal status truthful after canonicalization failure.

This Staging-only follow-up addresses the PR #17 Codex P2 without changing the
ProcessingIntegrationOutcome contract. When merged-result canonicalization fails
after all Provider shards completed, only the logical terminal diagnostic is
enriched to report ``provider_completed``.
"""
from __future__ import annotations

from pathlib import Path


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


def _patch_logical_canonicalization_provider_status() -> None:
    source = SHARDING_COMPAT_PATH.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        '    status = outcome.provider_terminal_status\n'
        '    if status is not None:\n'
        '        fields["provider_status"] = getattr(status, "value", status)\n'
        '    if outcome.provider_request_id:\n',
        '    status = outcome.provider_terminal_status\n'
        '    if status is not None:\n'
        '        fields["provider_status"] = getattr(status, "value", status)\n'
        '    elif (\n'
        '        isinstance(outcome.error, IntegrationError)\n'
        '        and outcome.error.category is IntegrationErrorCategory.CANONICALIZATION_FAILURE\n'
        '        and outcome.raw_result is not None\n'
        '    ):\n'
        '        # Merged-result canonicalization runs only after every Provider shard\n'
        '        # completed. Keep the outcome untouched and enrich only diagnostics.\n'
        '        fields["provider_status"] = ProviderLifecycleStatus.PROVIDER_COMPLETED.value\n'
        '    if outcome.provider_request_id:\n',
        label="logical canonicalization-failure Provider status",
    )
    SHARDING_COMPAT_PATH.write_text(source, encoding="utf-8")


def _append_runtime_regression() -> None:
    source = TEST_REVIEW_PATH.read_text(encoding="utf-8")
    marker = (
        "def test_sharding_terminal_preserves_completed_provider_status_after_canonicalization_failure("
    )
    if marker in source:
        return
    block = r'''


def test_sharding_terminal_preserves_completed_provider_status_after_canonicalization_failure(
    monkeypatch,
) -> None:
    from app.processing import pdf_provider_sharding as sharding
    from app.processing import pdf_provider_sharding_compat as sharding_compat
    from app.processing.integration import IntegrationErrorCategory
    from app.processing.pdf_canonicalization import PdfCanonicalizationError

    diagnostics: list[tuple[str, dict[str, object]]] = []
    provider_input = SimpleNamespace(provider_page_count=7, byte_size=28_425_561)
    delivery = SimpleNamespace(byte_size=28_425_561)
    merged_raw_result = SimpleNamespace(
        ingestion=SimpleNamespace(
            storage_reference=SimpleNamespace(),
            payload_sha256="b" * 64,
            payload_size_bytes=2345,
        )
    )

    monkeypatch.setattr(
        sharding_compat,
        "_provider_input_for",
        lambda service: provider_input,
    )
    monkeypatch.setattr(
        sharding_compat,
        "provider_delivery_descriptor",
        lambda value: delivery,
    )
    monkeypatch.setattr(
        sharding_compat,
        "_provider_page_route_counts",
        lambda value: {
            "presentation_page_count": 0,
            "native_text_page_count": 0,
            "full_document_page_count": 7,
            "provider_excluded_page_count": 0,
            "provider_route_page_count": 7,
        },
    )
    monkeypatch.setattr(
        sharding_compat,
        "provider_transport_sharding_required",
        lambda value: True,
    )
    monkeypatch.setattr(
        sharding_compat,
        "_delivery_is_full_render",
        lambda *args: False,
    )
    monkeypatch.setattr(
        sharding_compat,
        "_raw_client_for",
        lambda service: object(),
    )
    monkeypatch.setattr(
        sharding_compat,
        "_diagnostic",
        lambda event, **fields: diagnostics.append((event, fields)),
    )

    async def fake_run_provider_transport_shards(**kwargs):
        return sharding.ProviderTransportShardRunResult(
            canonicalization=None,
            raw_result=merged_raw_result,
            error=PdfCanonicalizationError("canonicalization failed after merge"),
            cleanup_safe=True,
            submission_started=True,
            shard_count=2,
            poll_count=16,
        )

    monkeypatch.setattr(
        sharding_compat,
        "run_provider_transport_shards",
        fake_run_provider_transport_shards,
    )

    ticks = iter((20.0, 21.5))
    service = SimpleNamespace(
        orchestrator=SimpleNamespace(storage=SimpleNamespace()),
        canonicalizer=object(),
        monotonic=lambda: next(ticks),
        _origin_value=None,
        polling_policy=SimpleNamespace(),
    )
    request = SimpleNamespace(
        retained_source=SimpleNamespace(
            document_id="document-canonicalization-terminal",
            source_file_id="source-canonicalization-terminal",
        ),
        processing_attempt_id="attempt-canonicalization-terminal",
        provider_name="paddle-vl",
        provider_job_id="job-canonicalization-terminal",
        provider_request_id="request-canonicalization-terminal",
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
        for event, fields in diagnostics
        if event == "PDF_PROVIDER_TRANSPORT_SHARDING_TERMINAL"
    )

    # Outcome semantics stay unchanged; only the logical diagnostic is enriched.
    assert outcome.provider_terminal_status is None
    assert outcome.error is not None
    assert outcome.error.category is IntegrationErrorCategory.CANONICALIZATION_FAILURE
    assert outcome.raw_result is merged_raw_result
    assert outcome.canonicalization is None
    assert outcome.poll_count == 16

    assert terminal["provider_status"] == "provider_completed"
    assert terminal["provider_request_id"] == "request-canonicalization-terminal"
    assert terminal["error_category"] == "canonicalization_failure"
    assert terminal["poll_count"] == 16
    assert terminal["raw_result_retained"] is True
    assert terminal["canonicalization_ready"] is False
    assert terminal["succeeded"] is False
'''
    TEST_REVIEW_PATH.write_text(
        source.rstrip() + block.rstrip() + "\n",
        encoding="utf-8",
    )


def _patch_authoritative_deploy_contract() -> None:
    source = TEST_DEPLOYMENT_PATH.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        '    assert \'fields["provider_status"] = getattr(status, "value", status)\' in helper\n'
        "\n"
        "    process = inspect.getsource(\n",
        '    assert \'fields["provider_status"] = getattr(status, "value", status)\' in helper\n'
        '    assert "IntegrationErrorCategory.CANONICALIZATION_FAILURE" in helper\n'
        '    assert "ProviderLifecycleStatus.PROVIDER_COMPLETED.value" in helper\n'
        "\n"
        "    process = inspect.getsource(\n",
        label="staging deploy canonicalization terminal diagnostic contract",
    )
    TEST_DEPLOYMENT_PATH.write_text(source, encoding="utf-8")


def main() -> None:
    _patch_logical_canonicalization_provider_status()
    _append_runtime_regression()
    _patch_authoritative_deploy_contract()
    print(
        "staging canonicalization terminal diagnostic fix ready: "
        "provider_status=provider_completed outcome_contract=unchanged"
    )


if __name__ == "__main__":
    main()
