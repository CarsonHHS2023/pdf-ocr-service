"""Preserve logical Provider poll counts across sequential 20 MiB transport shards.

This overlay runs after ``apply_provider_20mib_review_fixes``. It aggregates the
real poll count from every attempted shard into the logical sharding result so
top-level Provider diagnostics remain comparable with the unchanged single-job
path. It does not change timeout, TTL, transport sizing, or execution mode.
"""
from __future__ import annotations

from pathlib import Path


SHARDING_PATH = Path("app/processing/pdf_provider_sharding.py")
COMPAT_PATH = Path("app/processing/pdf_provider_sharding_compat.py")
TEST_REVIEW_PATH = Path("tests/test_provider_20mib_review_fixes.py")
TEST_DEPLOYMENT_PATH = Path("tests/test_staging_deployment_contract.py")


def _replace_once(source: str, old: str, new: str, *, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one source match, found {count}")
    return source.replace(old, new, 1)


def _replace_exact_count(
    source: str,
    old: str,
    new: str,
    *,
    expected: int,
    label: str,
) -> str:
    if new in source and old not in source:
        return source
    count = source.count(old)
    if count != expected:
        raise RuntimeError(f"{label}: expected {expected} source matches, found {count}")
    return source.replace(old, new)


def _patch_runtime_poll_count_aggregation() -> None:
    source = SHARDING_PATH.read_text(encoding="utf-8")

    source = _replace_once(
        source,
        '''class ProviderTransportShardRunResult:\n    canonicalization: Any | None\n    raw_result: RawProcessingResultEnvelope | None = field(repr=False)\n    error: Exception | None = field(default=None, repr=False)\n    cleanup_safe: bool = False\n    submission_started: bool = False\n    shard_count: int = 0\n''',
        '''class ProviderTransportShardRunResult:\n    canonicalization: Any | None\n    raw_result: RawProcessingResultEnvelope | None = field(repr=False)\n    error: Exception | None = field(default=None, repr=False)\n    cleanup_safe: bool = False\n    submission_started: bool = False\n    shard_count: int = 0\n    poll_count: int = 0\n''',
        label="logical shard result poll count field",
    )

    source = _replace_once(
        source,
        '''    cleanup_safe = True\n    submission_started = False\n    evidence: list[ProviderShardEvidence] = []\n    from app.processing import pdf_geometry_integration as integration\n''',
        '''    cleanup_safe = True\n    submission_started = False\n    evidence: list[ProviderShardEvidence] = []\n    total_poll_count = 0\n    from app.processing import pdf_geometry_integration as integration\n''',
        label="logical poll counter initialization",
    )

    source = _replace_once(
        source,
        '''            failed_shards=failed_shards,\n            cleanup_safe=cleanup_safe,\n''',
        '''            failed_shards=failed_shards,\n            poll_count=total_poll_count,\n            cleanup_safe=cleanup_safe,\n''',
        label="batch terminal aggregate poll diagnostic",
    )

    source = _replace_once(
        source,
        '''            outcome = await service.process(request)\n        except IntegrationError as exc:\n            shard_cleanup_safe = _cleanup_safe_from_integration_error(exc)\n''',
        '''            outcome = await service.process(request)\n            total_poll_count += max(0, int(outcome.poll_count or 0))\n        except IntegrationError as exc:\n            orchestration_error = getattr(exc, "orchestration_error", None)\n            total_poll_count += max(\n                0, int(getattr(orchestration_error, "poll_count", 0) or 0)\n            )\n            shard_cleanup_safe = _cleanup_safe_from_integration_error(exc)\n''',
        label="per-shard poll accumulation",
    )

    source = _replace_exact_count(
        source,
        '''            return ProviderTransportShardRunResult(\n                None, None, exc, cleanup_safe, submission_started, len(plans)\n            )''',
        '''            return ProviderTransportShardRunResult(\n                None, None, exc, cleanup_safe, submission_started, len(plans),\n                poll_count=total_poll_count,\n            )''',
        expected=2,
        label="raised shard failure poll preservation",
    )

    source = _replace_once(
        source,
        '''            return ProviderTransportShardRunResult(\n                None,\n                outcome.raw_result,\n                outcome.error,\n                cleanup_safe,\n                submission_started,\n                len(plans),\n            )''',
        '''            return ProviderTransportShardRunResult(\n                None,\n                outcome.raw_result,\n                outcome.error,\n                cleanup_safe,\n                submission_started,\n                len(plans),\n                poll_count=total_poll_count,\n            )''',
        label="returned shard failure poll preservation",
    )

    source = _replace_once(
        source,
        '''            return ProviderTransportShardRunResult(\n                None, None, error, cleanup_safe, submission_started, len(plans)\n            )''',
        '''            return ProviderTransportShardRunResult(\n                None, None, error, cleanup_safe, submission_started, len(plans),\n                poll_count=total_poll_count,\n            )''',
        label="missing raw result poll preservation",
    )

    source = _replace_once(
        source,
        '''        return ProviderTransportShardRunResult(\n            None, None, exc, cleanup_safe, submission_started, len(plans)\n        )''',
        '''        return ProviderTransportShardRunResult(\n            None, None, exc, cleanup_safe, submission_started, len(plans),\n            poll_count=total_poll_count,\n        )''',
        label="merge failure poll preservation",
    )

    source = _replace_once(
        source,
        '''        return ProviderTransportShardRunResult(\n            None, merged, exc, cleanup_safe, submission_started, len(plans)\n        )''',
        '''        return ProviderTransportShardRunResult(\n            None, merged, exc, cleanup_safe, submission_started, len(plans),\n            poll_count=total_poll_count,\n        )''',
        label="canonicalization failure poll preservation",
    )

    source = _replace_once(
        source,
        '''    return ProviderTransportShardRunResult(\n        canonical, merged, None, cleanup_safe, submission_started, len(plans)\n    )''',
        '''    return ProviderTransportShardRunResult(\n        canonical, merged, None, cleanup_safe, submission_started, len(plans),\n        poll_count=total_poll_count,\n    )''',
        label="successful logical result poll preservation",
    )

    SHARDING_PATH.write_text(source, encoding="utf-8")

    compat = COMPAT_PATH.read_text(encoding="utf-8")
    compat = _replace_once(
        compat,
        "            poll_count=0,\n",
        "            poll_count=result.poll_count,\n",
        label="successful logical outcome aggregate polls",
    )
    compat = _replace_once(
        compat,
        '        poll_count=getattr(orchestration_error, "poll_count", 0),\n',
        "        poll_count=result.poll_count,\n",
        label="failed logical outcome aggregate polls",
    )
    COMPAT_PATH.write_text(compat, encoding="utf-8")


def _append_focused_regression() -> None:
    source = TEST_REVIEW_PATH.read_text(encoding="utf-8")
    marker = "def test_successful_sharded_outcome_aggregates_real_poll_counts(monkeypatch)"
    if marker in source:
        return
    block = r'''


def test_successful_sharded_outcome_aggregates_real_poll_counts(monkeypatch) -> None:
    plans = (
        ProviderInputShardPlan(0, 0, 0, 1, 1024),
        ProviderInputShardPlan(1, 1, 1, 1, 1024),
    )
    monkeypatch.setattr(sharding, "plan_provider_input_shards", lambda *a, **k: plans)
+
+    def materialize(storage, provider_input, plan, **kwargs):
+        return SimpleNamespace(
+            provider_byte_size=1024,
+            provider_page_count=1,
+            provider_storage_reference=SimpleNamespace(
+                value=f"poll-shard-{plan.shard_index}"
+            ),
+            provider_checksum_sha256=str(plan.shard_index + 1) * 64,
+            provider_filename=f"poll-shard-{plan.shard_index}.pdf",
+            media_type="application/pdf",
+            preprocessing=None,
+        )
+
+    monkeypatch.setattr(sharding, "materialize_provider_input_shard", materialize)
+
+    from app.processing import pdf_geometry_integration as integration
+
+    monkeypatch.setattr(
+        integration,
+        "ProviderInputChecksumProvider",
+        lambda client, provider_input: SimpleNamespace(),
+    )
+    monkeypatch.setattr(
+        integration,
+        "ProviderInputAwareProcessingOrchestrator",
+        lambda **kwargs: SimpleNamespace(),
+    )
+    monkeypatch.setattr(
+        integration,
+        "ProviderInputGrantService",
+        lambda *args, **kwargs: SimpleNamespace(),
+    )
+    monkeypatch.setattr(
+        integration,
+        "provider_delivery_descriptor",
+        lambda provider_input: SimpleNamespace(
+            storage_reference=provider_input.provider_storage_reference,
+            byte_size=provider_input.provider_byte_size,
+        ),
+    )
+    monkeypatch.setattr(sharding, "get_transport_grant_service", lambda: SimpleNamespace())
+    monkeypatch.setattr(
+        sharding,
+        "build_provider_input_source_url_factory",
+        lambda **kwargs: object(),
+    )
+
+    poll_counts = iter((2, 3))
+
+    class FakeService:
+        def __init__(self, **kwargs):
+            pass
+
+        async def process(self, request):
+            poll_count = next(poll_counts)
+            return SimpleNamespace(
+                revocation_succeeded=True,
+                grant_final_state=None,
+                integration_terminal_phase=SimpleNamespace(value="raw_result_retained"),
+                provider_terminal_status=SimpleNamespace(value="completed"),
+                error=None,
+                poll_count=poll_count,
+                raw_result=SimpleNamespace(name=f"raw-{poll_count}"),
+            )
+
+    monkeypatch.setattr(sharding, "EndToEndProcessingIntegrationService", FakeService)
+
+    merged_reference = SimpleNamespace(value="merged-poll-result")
+    merged = SimpleNamespace(
+        ingestion=SimpleNamespace(
+            storage_reference=merged_reference,
+            payload_sha256="c" * 64,
+            payload_size_bytes=2048,
+            page_summary=None,
+        )
+    )
+    monkeypatch.setattr(
+        sharding,
+        "merge_provider_shard_results",
+        lambda *args, **kwargs: merged,
+    )
+
+    canonical = SimpleNamespace(name="canonical-poll-result")
+
+    class Canonicalizer:
+        def canonicalize(self, envelope):
+            assert envelope is merged
+            return canonical
+
+    diagnostics: list[tuple[str, dict[str, object]]] = []
+    result = asyncio.run(
+        sharding.run_provider_transport_shards(
+            storage=SimpleNamespace(delete=lambda reference: None),
+            client=SimpleNamespace(),
+            provider_input=SimpleNamespace(
+                provider_byte_size=21 * _MIB,
+                provider_page_count=2,
+            ),
+            descriptor=SimpleNamespace(),
+            processing_attempt_id="attempt-poll-aggregate",
+            logical_provider_job_id="job-poll-aggregate",
+            logical_provider_request_id="request-poll-aggregate",
+            result_profile="full",
+            provider_job_options={},
+            public_origin=None,
+            polling_policy=SimpleNamespace(),
+            canonicalizer=Canonicalizer(),
+            diagnostic=lambda event, **fields: diagnostics.append((event, fields)),
+        )
+    )
+
+    assert result.error is None
+    assert result.canonicalization is canonical
+    assert result.poll_count == 5
+
+    batch_terminal = next(
+        fields
+        for event, fields in diagnostics
+        if event == "PDF_PROVIDER_SHARD_BATCH_TERMINAL"
+        and fields["failed_shards"] == 0
+    )
+    assert batch_terminal["poll_count"] == 5
+
+    outcome = sharding_compat._outcome_from_sharded_result(
+        SimpleNamespace(
+            retained_source=SimpleNamespace(
+                document_id="document-poll-aggregate",
+                source_file_id="source-poll-aggregate",
+            ),
+            provider_name="paddle-vl",
+            provider_job_id="job-poll-aggregate",
+            provider_request_id="request-poll-aggregate",
+        ),
+        result,
+        elapsed_seconds=2.5,
+    )
+    assert outcome.poll_count == 5
+'''.replace("\n+", "\n")
    TEST_REVIEW_PATH.write_text(source.rstrip() + block.rstrip() + "\n", encoding="utf-8")


def _append_authoritative_deploy_regression() -> None:
    source = TEST_DEPLOYMENT_PATH.read_text(encoding="utf-8")
    marker = "def test_pr16_shard_poll_count_aggregation_in_staging_deploy_gate()"
    if marker in source:
        return
    block = '''


def test_pr16_shard_poll_count_aggregation_in_staging_deploy_gate() -> None:
    import inspect

    from app.processing import pdf_provider_sharding as sharding
    from app.processing import pdf_provider_sharding_compat as sharding_compat

    fields = sharding.ProviderTransportShardRunResult.__dataclass_fields__
    assert "poll_count" in fields

    runner = inspect.getsource(sharding.run_provider_transport_shards)
    assert "total_poll_count += max(0, int(outcome.poll_count or 0))" in runner
    assert "poll_count=total_poll_count" in runner
    assert "poll_count=total_poll_count" in runner

    outcome_builder = inspect.getsource(sharding_compat._outcome_from_sharded_result)
    assert outcome_builder.count("poll_count=result.poll_count") == 2
'''
    TEST_DEPLOYMENT_PATH.write_text(
        source.rstrip() + block.rstrip() + "\n",
        encoding="utf-8",
    )


def main() -> None:
    _patch_runtime_poll_count_aggregation()
    _append_focused_regression()
    _append_authoritative_deploy_regression()
    print(
        "provider 20 MiB poll-count fix ready: logical_poll_count=sum(shard polls) "
        "success_and_failure_outcomes=preserved staging_deploy_gate=locked"
    )


if __name__ == "__main__":
    main()
