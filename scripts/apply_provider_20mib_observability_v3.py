"""Final review wrapper for the 20 MiB Staging Provider overlay."""
from __future__ import annotations

from pathlib import Path

try:
    from scripts.apply_provider_20mib_observability_v2 import main as apply_v2
except ImportError:
    from apply_provider_20mib_observability_v2 import main as apply_v2


SHARDING_PATH = Path("app/processing/pdf_provider_sharding.py")
_MARKER = "first_error_raw_result = None"


def _patch_failed_shard_raw_result_identity() -> None:
    source = SHARDING_PATH.read_text(encoding="utf-8")
    if _MARKER in source:
        return

    old_state = '''    evidence: list[ProviderShardEvidence] = []
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
'''
    new_state = '''    evidence: list[ProviderShardEvidence] = []
    first_error_raw_result = None
    first_error: Exception | None = None
    succeeded_shards = 0
    failed_shards = 0
    for shard_evidence, raw_result, error, _safe, _started in results:
        if error is not None:
            failed_shards += 1
            if first_error is None:
                first_error = error
                first_error_raw_result = raw_result
            continue
'''
    if source.count(old_state) != 1:
        raise RuntimeError("failed-shard aggregation block is not unique")
    source = source.replace(old_state, new_state, 1)

    old_return = '''        return ProviderTransportShardRunResult(
            None,
            first_raw_result,
            first_error,
            cleanup_safe,
            submission_started,
            len(plans),
        )
'''
    new_return = '''        return ProviderTransportShardRunResult(
            None,
            first_error_raw_result,
            first_error,
            cleanup_safe,
            submission_started,
            len(plans),
        )
'''
    if source.count(old_return) != 1:
        raise RuntimeError("failed-shard result block is not unique")
    source = source.replace(old_return, new_return, 1)
    SHARDING_PATH.write_text(source, encoding="utf-8")


def main() -> None:
    apply_v2()
    _patch_failed_shard_raw_result_identity()
    print("provider 20 MiB final-review overlay ready: failed_shard_identity=preserved")


if __name__ == "__main__":
    main()
