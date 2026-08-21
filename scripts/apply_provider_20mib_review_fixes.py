"""Apply final review fixes for the Staging 20 MiB Provider Baseline.

This runs after the existing v5 composition and fixes review findings without
changing Provider timeout/TTL policy or adding Atlas fanout.
"""
from __future__ import annotations

from pathlib import Path

try:
    from scripts.apply_provider_20mib_observability_v5 import main as apply_v5
except ImportError:
    from apply_provider_20mib_observability_v5 import main as apply_v5


SHARDING_PATH = Path("app/processing/pdf_provider_sharding.py")
INGESTION_PATH = Path("app/processing/pdf_ingestion.py")
TEST_SHARDING_PATH = Path("tests/test_pdf_provider_sharding.py")
TEST_OBSERVABILITY_PATH = Path("tests/test_provider_20mib_observability.py")


def _replace_once(source: str, old: str, new: str, *, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one source match, found {count}")
    return source.replace(old, new, 1)


def _patch_active_ingestion_classification_context() -> None:
    """Bind run identity around the top-level function pdf_ingestion actually calls."""
    source = INGESTION_PATH.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        "from app.processing.pdf_page_classification_observability_compat import (\n"
        "    install_page_classification_observability_compat,\n"
        ")",
        "from app.processing.pdf_page_classification_observability_compat import (\n"
        "    install_page_classification_observability_compat,\n"
        "    page_classification_observation_context,\n"
        ")",
        label="classification observation context import",
    )
    old_call = '''    with pdf_resource_observation_context(
        processing_run_id=processing_attempt_id,
        document_id=descriptor.document_id,
        page_count=resolved_page_count,
    ):
        result = prepare_geometry_provider_input(
            storage=storage,
            source_pdf_bytes=source_pdf,
            original_filename=descriptor.filename,
            processing_attempt_id=processing_attempt_id,
            expected_page_count=resolved_page_count,
        )
'''
    new_call = '''    with pdf_resource_observation_context(
        processing_run_id=processing_attempt_id,
        document_id=descriptor.document_id,
        page_count=resolved_page_count,
    ):
        with page_classification_observation_context(processing_attempt_id):
            result = prepare_geometry_provider_input(
                storage=storage,
                source_pdf_bytes=source_pdf,
                original_filename=descriptor.filename,
                processing_attempt_id=processing_attempt_id,
                expected_page_count=resolved_page_count,
            )
'''
    source = _replace_once(
        source,
        old_call,
        new_call,
        label="active ingestion classification identity scope",
    )
    INGESTION_PATH.write_text(source, encoding="utf-8")


def _patch_strict_20mib_transport_ceiling() -> None:
    source = SHARDING_PATH.read_text(encoding="utf-8")
    old = '''# The planner targets 20 MiB. A narrow materialization-only ceiling
# tolerates PyMuPDF object-table/document-id serialization jitter.
# Modal independently caps each GPU compute range at 20 MiB.
PROVIDER_TRANSPORT_SHARD_MAX_BYTES = 24 * _MIB
'''
    new = '''# Baseline contract: the planner target and the bytes actually granted to
# Provider share the same 20 MiB hard ceiling. If reserialization crosses the
# limit, fail locally before Provider submission rather than silently widening
# the experiment.
PROVIDER_TRANSPORT_SHARD_MAX_BYTES = 20 * _MIB
'''
    source = _replace_once(
        source,
        old,
        new,
        label="strict 20 MiB transport hard ceiling",
    )
    SHARDING_PATH.write_text(source, encoding="utf-8")

    tests = TEST_SHARDING_PATH.read_text(encoding="utf-8")
    tests = tests.replace(
        "assert PROVIDER_TRANSPORT_SHARD_MAX_BYTES == 24 * 1024 * 1024",
        "assert PROVIDER_TRANSPORT_SHARD_MAX_BYTES == 20 * 1024 * 1024",
    )
    tests = tests.replace(
        "assert PROVIDER_TRANSPORT_SHARD_TARGET_BYTES < PROVIDER_TRANSPORT_SHARD_MAX_BYTES",
        "assert PROVIDER_TRANSPORT_SHARD_TARGET_BYTES == PROVIDER_TRANSPORT_SHARD_MAX_BYTES",
    )
    TEST_SHARDING_PATH.write_text(tests, encoding="utf-8")

    tests = TEST_OBSERVABILITY_PATH.read_text(encoding="utf-8")
    tests = tests.replace(
        "assert sharding.PROVIDER_TRANSPORT_SHARD_MAX_BYTES == 24 * _MIB",
        "assert sharding.PROVIDER_TRANSPORT_SHARD_MAX_BYTES == 20 * _MIB",
    )
    tests = tests.replace(
        "    assert sharding.PROVIDER_TRANSPORT_SHARD_TARGET_BYTES < (\n"
        "        sharding.PROVIDER_TRANSPORT_SHARD_MAX_BYTES\n"
        "    )",
        "    assert sharding.PROVIDER_TRANSPORT_SHARD_TARGET_BYTES == (\n"
        "        sharding.PROVIDER_TRANSPORT_SHARD_MAX_BYTES\n"
        "    )",
    )
    TEST_OBSERVABILITY_PATH.write_text(tests, encoding="utf-8")


def _patch_canonicalization_failure_evidence() -> None:
    source = SHARDING_PATH.read_text(encoding="utf-8")
    old = '''    batch_terminal(failed_shards=0)
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
    new = '''    batch_terminal(failed_shards=0)
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
    try:
        canonical = await asyncio.to_thread(canonicalizer.canonicalize, merged)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        diagnostic(
            "PDF_PROVIDER_SHARD_CANONICALIZATION_FAILED",
            processing_attempt_id=processing_attempt_id,
            provider_job_id=logical_provider_job_id,
            shard_count=len(plans),
            error_category=type(exc).__name__,
            raw_result_retained=True,
            shard_execution_mode=PROVIDER_TRANSPORT_SHARD_EXECUTION_MODE,
        )
        return ProviderTransportShardRunResult(
            None, merged, exc, cleanup_safe, submission_started, len(plans)
        )
    return ProviderTransportShardRunResult(
        canonical, merged, None, cleanup_safe, submission_started, len(plans)
    )
'''
    source = _replace_once(
        source,
        old,
        new,
        label="preserve merged raw result after canonicalization failure",
    )
    SHARDING_PATH.write_text(source, encoding="utf-8")


def main() -> None:
    apply_v5()
    _patch_active_ingestion_classification_context()
    _patch_strict_20mib_transport_ceiling()
    _patch_canonicalization_failure_evidence()
    print(
        "provider 20 MiB review fixes ready: actual_transport_hard_max_mib=20 "
        "canonicalization_failure_raw_result=preserved "
        "classification_identity_scope=active_ingestion"
    )


if __name__ == "__main__":
    main()
