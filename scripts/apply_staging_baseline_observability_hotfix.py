"""Fix observability gaps found by the real 11-page Staging smoke.

This final composition layer runs after the PR #16 20 MiB/sequential Provider
contract. It does not change OCR routing, shard sizing, timeout/TTL policy, or
Provider execution. It only makes the Baseline diagnostics truthful and visible.
"""
from __future__ import annotations

from pathlib import Path


CLASSIFICATION_PATH = Path(
    "app/processing/pdf_page_classification_observability_compat.py"
)
SHARDING_PATH = Path("app/processing/pdf_provider_sharding.py")
SHARDING_COMPAT_PATH = Path("app/processing/pdf_provider_sharding_compat.py")
TEST_OBSERVABILITY_PATH = Path("tests/test_provider_20mib_observability.py")
TEST_REVIEW_PATH = Path("tests/test_provider_20mib_review_fixes.py")
TEST_DEPLOYMENT_PATH = Path("tests/test_staging_deployment_contract.py")


def _replace_once(source: str, old: str, new: str, *, label: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one source match, found {count}")
    return source.replace(old, new, 1)


def _patch_classification_runtime_sink() -> None:
    """Make bounded classifier diagnostics visible in HF runtime logs."""
    source = CLASSIFICATION_PATH.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        "from contextvars import ContextVar\nimport os\nfrom typing import Any, Iterator, Mapping\n",
        "from contextvars import ContextVar\nimport logging\nimport os\nimport sys\nfrom typing import Any, Iterator, Mapping\n",
        label="classification runtime diagnostic imports",
    )
    source = _replace_once(
        source,
        "from app.processing import pdf_page_presentation_preprocess_compat as preprocess\n\n_INSTALLED = False\n",
        "from app.processing import pdf_page_presentation_preprocess_compat as preprocess\n\n"
        "_logger = logging.getLogger(\"uvicorn.error\")\n"
        "_INSTALLED = False\n",
        label="classification runtime logger",
    )
    diagnostic = '''\n\ndef _diagnostic(event: str, **fields: object) -> None:\n    \"\"\"Emit one safe bounded event to both logger and runtime stderr.\"\"\"\n    payload = \" \".join(f\"{name}={value}\" for name, value in fields.items())\n    message = f\"{event} {payload}\".rstrip()\n    _logger.info(message)\n    print(message, file=sys.stderr, flush=True)\n'''
    if "def _diagnostic(event: str, **fields: object) -> None:" not in source:
        anchor = "\n\ndef _configured_model() -> str:\n"
        if source.count(anchor) != 1:
            raise RuntimeError("classification diagnostic helper anchor is not unique")
        source = source.replace(anchor, diagnostic + anchor, 1)

    bridge_calls = source.count("bridge._diagnostic(")
    if bridge_calls:
        if bridge_calls != 3:
            raise RuntimeError(
                f"classification diagnostic sink: expected 3 bridge calls, found {bridge_calls}"
            )
        source = source.replace("bridge._diagnostic(", "_diagnostic(")
    required = (
        '"PDF_PAGE_CLASSIFICATION_CONFIG"',
        '"PDF_PAGE_CLASSIFICATION_SUMMARY"',
        '"PDF_PAGE_CLASSIFICATION_DECISION"',
        "print(message, file=sys.stderr, flush=True)",
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise RuntimeError(f"classification runtime sink markers missing: {missing}")
    CLASSIFICATION_PATH.write_text(source, encoding="utf-8")


def _patch_existing_classification_capture_tests() -> None:
    """Keep pre-existing unit tests attached to the runtime-visible sink."""
    old = '''    monkeypatch.setattr(\n        bridge,\n        "_diagnostic",\n        lambda event, **fields: diagnostics.append((event, fields)),\n    )\n'''
    new = '''    monkeypatch.setattr(\n        classification_obs,\n        "_diagnostic",\n        lambda event, **fields: diagnostics.append((event, fields)),\n    )\n'''
    for path, label in (
        (TEST_OBSERVABILITY_PATH, "classification observability capture test"),
        (TEST_REVIEW_PATH, "classification review capture test"),
    ):
        source = path.read_text(encoding="utf-8")
        source = _replace_once(source, old, new, label=label)
        path.write_text(source, encoding="utf-8")


def _patch_logical_sharding_terminal_fields() -> None:
    """Use logical aggregate outcome fields for the sharding terminal event."""
    source = SHARDING_COMPAT_PATH.read_text(encoding="utf-8")
    helper_marker = "def _logical_terminal_diagnostic_fields(outcome: Any) -> dict[str, object]:"
    if helper_marker not in source:
        helper = '''\n\ndef _logical_terminal_diagnostic_fields(outcome: Any) -> dict[str, object]:\n    \"\"\"Overlay aggregate logical outcome fields onto failure snapshots.\"\"\"\n    fields = _provider_failure_diagnostic_fields(outcome.error)\n    status = outcome.provider_terminal_status\n    if status is not None:\n        fields[\"provider_status\"] = getattr(status, \"value\", status)\n    if outcome.provider_request_id:\n        fields[\"provider_request_id\"] = outcome.provider_request_id\n    fields[\"poll_count\"] = max(0, int(outcome.poll_count or 0))\n    fields[\"raw_result_retained\"] = outcome.raw_result is not None\n    fields[\"canonicalization_ready\"] = outcome.canonicalization is not None\n    return fields\n'''
        anchor = "\n\ndef _outcome_from_sharded_result(\n"
        if source.count(anchor) != 1:
            raise RuntimeError("logical sharding terminal helper anchor is not unique")
        source = source.replace(anchor, helper + anchor, 1)

    source = _replace_once(
        source,
        "        failure_fields = _provider_failure_diagnostic_fields(outcome.error)\n"
        "        _diagnostic(\n"
        "            \"PDF_PROVIDER_TRANSPORT_SHARDING_TERMINAL\",\n",
        "        failure_fields = _logical_terminal_diagnostic_fields(outcome)\n"
        "        _diagnostic(\n"
        "            \"PDF_PROVIDER_TRANSPORT_SHARDING_TERMINAL\",\n",
        label="logical sharding terminal aggregate fields",
    )
    SHARDING_COMPAT_PATH.write_text(source, encoding="utf-8")


def _patch_shard_cleanup_diagnostics() -> None:
    """Separate benign already-missing cleanup from real delete failures."""
    source = SHARDING_PATH.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        "from app.processing.transport.models import TransportGrantState\n"
        "from app.storage.models import StorageReference\n",
        "from app.processing.transport.models import TransportGrantState\n"
        "from app.storage.errors import ObjectNotFound\n"
        "from app.storage.models import StorageReference\n",
        label="shard cleanup ObjectNotFound import",
    )
    old = '''    try:\n        storage.delete(reference)\n    except Exception:\n        # Deletion can already have happened in deferred-subset grant failure\n        # cleanup. Do not convert a successful provider result into a failure.\n        diagnostic(\n            \"PDF_PROVIDER_SHARD_INPUT_DELETE_WARNING\",\n            processing_attempt_id=processing_attempt_id,\n            provider_job_id=provider_job_id,\n            shard_index=shard_index,\n        )\n    else:\n'''
    new = '''    try:\n        storage.delete(reference)\n    except ObjectNotFound:\n        # Another lifecycle path may already have removed the same temporary\n        # shard. Treat that as a successful idempotent cleanup outcome.\n        diagnostic(\n            \"PDF_PROVIDER_SHARD_INPUT_ALREADY_DELETED\",\n            processing_attempt_id=processing_attempt_id,\n            provider_job_id=provider_job_id,\n            shard_index=shard_index,\n            storage_backend=type(storage).__name__,\n            error_type=\"ObjectNotFound\",\n            already_missing=True,\n        )\n    except Exception as exc:\n        # Keep the successful Provider result, but make a real cleanup failure\n        # distinguishable without logging object references or signed URLs.\n        diagnostic(\n            \"PDF_PROVIDER_SHARD_INPUT_DELETE_WARNING\",\n            processing_attempt_id=processing_attempt_id,\n            provider_job_id=provider_job_id,\n            shard_index=shard_index,\n            storage_backend=type(storage).__name__,\n            error_type=type(exc).__name__,\n            already_missing=False,\n        )\n    else:\n'''
    source = _replace_once(
        source,
        old,
        new,
        label="shard cleanup diagnostic split",
    )
    SHARDING_PATH.write_text(source, encoding="utf-8")


def _append_focused_regressions() -> None:
    source = TEST_REVIEW_PATH.read_text(encoding="utf-8")
    marker = "def test_baseline_smoke_observability_hotfix_contracts(capsys)"
    if marker in source:
        return
    block = r'''


def test_baseline_smoke_observability_hotfix_contracts(capsys) -> None:
    from app.processing import pdf_page_classification_observability_compat as classification_obs
    from app.processing import pdf_provider_sharding as sharding
    from app.processing import pdf_provider_sharding_compat as sharding_compat
    from app.storage.errors import ObjectNotFound

    classification_obs._diagnostic(
        "PDF_PAGE_CLASSIFICATION_SUMMARY",
        processing_attempt_id="attempt-visible-smoke",
        candidate_count=1,
    )
    captured = capsys.readouterr()
    assert "PDF_PAGE_CLASSIFICATION_SUMMARY" in captured.err
    assert "processing_attempt_id=attempt-visible-smoke" in captured.err

    logical_fields = sharding_compat._logical_terminal_diagnostic_fields(
        SimpleNamespace(
            error=None,
            provider_terminal_status=SimpleNamespace(value="provider_completed"),
            provider_request_id="logical-request-smoke",
            poll_count=16,
            raw_result=object(),
            canonicalization=object(),
        )
    )
    assert logical_fields["provider_status"] == "provider_completed"
    assert logical_fields["provider_request_id"] == "logical-request-smoke"
    assert logical_fields["poll_count"] == 16
    assert logical_fields["raw_result_retained"] is True
    assert logical_fields["canonicalization_ready"] is True

    diagnostics: list[tuple[str, dict[str, object]]] = []
    shard_input = SimpleNamespace(provider_storage_reference=SimpleNamespace())

    class MissingStorage:
        def delete(self, reference):
            raise ObjectNotFound("already removed")

    sharding._delete_shard_provider_input_if_safe(
        MissingStorage(),
        shard_input,
        cleanup_safe=True,
        diagnostic=lambda event, **fields: diagnostics.append((event, fields)),
        processing_attempt_id="attempt-cleanup-missing",
        provider_job_id="job-cleanup-missing",
        shard_index=0,
    )
    event, fields = diagnostics.pop()
    assert event == "PDF_PROVIDER_SHARD_INPUT_ALREADY_DELETED"
    assert fields["already_missing"] is True
    assert fields["error_type"] == "ObjectNotFound"
    assert fields["storage_backend"] == "MissingStorage"

    class FailingStorage:
        def delete(self, reference):
            raise RuntimeError("backend unavailable")

    sharding._delete_shard_provider_input_if_safe(
        FailingStorage(),
        shard_input,
        cleanup_safe=True,
        diagnostic=lambda event, **fields: diagnostics.append((event, fields)),
        processing_attempt_id="attempt-cleanup-failed",
        provider_job_id="job-cleanup-failed",
        shard_index=1,
    )
    event, fields = diagnostics.pop()
    assert event == "PDF_PROVIDER_SHARD_INPUT_DELETE_WARNING"
    assert fields["already_missing"] is False
    assert fields["error_type"] == "RuntimeError"
    assert fields["storage_backend"] == "FailingStorage"


def test_sharding_terminal_event_uses_logical_aggregate_fields() -> None:
    import inspect

    from app.processing import pdf_provider_sharding_compat as sharding_compat

    process = inspect.getsource(
        sharding_compat.ShardingAwareEndToEndProcessingIntegrationService.process
    )
    terminal_start = process.index('"PDF_PROVIDER_TRANSPORT_SHARDING_TERMINAL"')
    terminal_block = process[max(0, terminal_start - 300):terminal_start + 1200]
    assert "failure_fields = _logical_terminal_diagnostic_fields(outcome)" in terminal_block
'''
    TEST_REVIEW_PATH.write_text(
        source.rstrip() + block.rstrip() + "\n",
        encoding="utf-8",
    )


def _append_authoritative_deploy_contract() -> None:
    source = TEST_DEPLOYMENT_PATH.read_text(encoding="utf-8")
    marker = "def test_baseline_smoke_observability_hotfix_in_staging_deploy_gate()"
    if marker in source:
        return
    block = '''


def test_baseline_smoke_observability_hotfix_in_staging_deploy_gate() -> None:
    import inspect

    from app.processing import pdf_page_classification_observability_compat as classification_obs
    from app.processing import pdf_provider_sharding as sharding
    from app.processing import pdf_provider_sharding_compat as sharding_compat

    classifier = inspect.getsource(classification_obs)
    assert "print(message, file=sys.stderr, flush=True)" in classifier
    assert classifier.count("_diagnostic(") >= 4

    helper = inspect.getsource(sharding_compat._logical_terminal_diagnostic_fields)
    assert 'fields["poll_count"] = max(0, int(outcome.poll_count or 0))' in helper
    assert 'fields["provider_status"] = getattr(status, "value", status)' in helper

    process = inspect.getsource(
        sharding_compat.ShardingAwareEndToEndProcessingIntegrationService.process
    )
    assert "failure_fields = _logical_terminal_diagnostic_fields(outcome)" in process

    cleanup = inspect.getsource(sharding._delete_shard_provider_input_if_safe)
    assert "PDF_PROVIDER_SHARD_INPUT_ALREADY_DELETED" in cleanup
    assert "already_missing=True" in cleanup
    assert "already_missing=False" in cleanup
    assert "storage_backend=type(storage).__name__" in cleanup
'''
    TEST_DEPLOYMENT_PATH.write_text(
        source.rstrip() + block.rstrip() + "\n",
        encoding="utf-8",
    )


def main() -> None:
    _patch_classification_runtime_sink()
    _patch_existing_classification_capture_tests()
    _patch_logical_sharding_terminal_fields()
    _patch_shard_cleanup_diagnostics()
    _append_focused_regressions()
    _append_authoritative_deploy_contract()
    print(
        "staging baseline observability hotfix ready: "
        "classification_runtime_sink=stderr "
        "sharding_terminal=logical_aggregate_fields "
        "shard_cleanup=already_missing_vs_failure"
    )


if __name__ == "__main__":
    main()
