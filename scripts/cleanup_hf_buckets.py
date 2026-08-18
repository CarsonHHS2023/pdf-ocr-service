"""Safely clean temporary Hugging Face Storage Bucket artifacts.

This utility is intentionally independent from the FastAPI/OCR runtime. It only
operates on the known test bucket and on two explicit production diagnostics
prefixes. Production Reader/source assets are never targeted.

The current diagnostic layouts do not carry a reliable job terminal status:
``opencv-diagnostics`` is grouped by processing attempt while
``opencv-crop-diagnostics`` is grouped by asset id. Until status metadata is
available at the storage boundary, production diagnostics use the conservative
14-day retention window for every file. Test artifacts use a 7-day window.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
from typing import Iterable, Iterator, Sequence

DEFAULT_TEST_BUCKET = "carsonhhs/pdf-ocr-service-ocrmypdf-test-storage"
DEFAULT_PRODUCTION_BUCKET = "carsonhhs/pdf-ocr-service-storage"
PRODUCTION_DIAGNOSTIC_PREFIXES = (
    "output/opencv-diagnostics/",
    "output/opencv-crop-diagnostics/",
)
DEFAULT_TEST_RETENTION_DAYS = 7
DEFAULT_PRODUCTION_DIAGNOSTICS_RETENTION_DAYS = 14
_DELETE_BATCH_SIZE = 500


@dataclass(frozen=True)
class CleanupTarget:
    bucket_id: str
    prefix: str | None
    cutoff: datetime | None
    reason: str


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def scope_items_to_prefix(items: Iterable[object], *, prefix: str | None) -> list[object]:
    """Fail closed around the remote prefix filter.

    Hugging Face lists by string prefix. Re-check every returned path locally so
    a similarly named neighboring prefix can never become a production deletion
    candidate.
    """
    materialized = list(items)
    if prefix is None:
        return materialized
    required_prefix = prefix.rstrip("/") + "/"
    return [
        item
        for item in materialized
        if isinstance((path := getattr(item, "path", None)), str)
        and path.startswith(required_prefix)
    ]


def select_expired_files(items: Iterable[object], *, cutoff: datetime | None) -> list[object]:
    """Return file entries eligible for deletion.

    ``cutoff=None`` means every file is eligible, which is used only for the
    explicitly named test bucket purge mode.
    """
    selected: list[object] = []
    normalized_cutoff = _utc(cutoff) if cutoff is not None else None
    for item in items:
        if getattr(item, "type", None) != "file":
            continue
        path = getattr(item, "path", None)
        if not isinstance(path, str) or not path:
            continue
        if normalized_cutoff is None:
            selected.append(item)
            continue
        mtime = getattr(item, "mtime", None)
        if not isinstance(mtime, datetime):
            # Unknown age must fail closed: keep the object rather than guess.
            continue
        if _utc(mtime) < normalized_cutoff:
            selected.append(item)
    return selected


def chunked(values: Sequence[str], size: int = _DELETE_BATCH_SIZE) -> Iterator[list[str]]:
    if size <= 0:
        raise ValueError("chunk size must be positive")
    for start in range(0, len(values), size):
        yield list(values[start : start + size])


def build_targets(
    *,
    mode: str,
    now: datetime,
    test_bucket: str = DEFAULT_TEST_BUCKET,
    production_bucket: str = DEFAULT_PRODUCTION_BUCKET,
    test_retention_days: int = DEFAULT_TEST_RETENTION_DAYS,
    production_diagnostics_retention_days: int = DEFAULT_PRODUCTION_DIAGNOSTICS_RETENTION_DAYS,
) -> tuple[CleanupTarget, ...]:
    if test_bucket == production_bucket:
        raise ValueError("test and production buckets must be different")
    if test_retention_days <= 0 or production_diagnostics_retention_days <= 0:
        raise ValueError("retention days must be positive")

    now_utc = _utc(now)
    if mode == "purge-test":
        return (
            CleanupTarget(
                bucket_id=test_bucket,
                prefix=None,
                cutoff=None,
                reason="manual full purge of test bucket contents",
            ),
        )
    if mode != "scheduled":
        raise ValueError(f"unsupported cleanup mode: {mode}")

    targets = [
        CleanupTarget(
            bucket_id=test_bucket,
            prefix=None,
            cutoff=now_utc - timedelta(days=test_retention_days),
            reason=f"test artifacts older than {test_retention_days} days",
        )
    ]
    production_cutoff = now_utc - timedelta(days=production_diagnostics_retention_days)
    targets.extend(
        CleanupTarget(
            bucket_id=production_bucket,
            prefix=prefix,
            cutoff=production_cutoff,
            reason=(
                "production diagnostics older than "
                f"{production_diagnostics_retention_days} days"
            ),
        )
        for prefix in PRODUCTION_DIAGNOSTIC_PREFIXES
    )
    return tuple(targets)


def _list_target_files(target: CleanupTarget, *, token: str) -> list[object]:
    from huggingface_hub import list_bucket_tree

    kwargs: dict[str, object] = {
        "recursive": True,
        "token": token,
    }
    if target.prefix:
        kwargs["prefix"] = target.prefix
    listed = list(list_bucket_tree(target.bucket_id, **kwargs))
    return scope_items_to_prefix(listed, prefix=target.prefix)


def _delete_paths(bucket_id: str, paths: Sequence[str], *, token: str) -> None:
    from huggingface_hub import batch_bucket_files

    for batch in chunked(paths):
        batch_bucket_files(bucket_id, delete=batch, token=token)


def execute_target(target: CleanupTarget, *, token: str, apply: bool) -> tuple[int, int]:
    items = _list_target_files(target, token=token)
    selected = select_expired_files(items, cutoff=target.cutoff)
    paths = [str(getattr(item, "path")) for item in selected]
    total_bytes = sum(
        int(size)
        for item in selected
        if isinstance((size := getattr(item, "size", None)), int) and size >= 0
    )
    cutoff_text = target.cutoff.isoformat() if target.cutoff is not None else "none"
    prefix_text = target.prefix or "<bucket-root>"
    print(
        "HF_BUCKET_CLEANUP_PLAN "
        f"bucket={target.bucket_id} prefix={prefix_text} cutoff={cutoff_text} "
        f"files={len(paths)} bytes={total_bytes} apply={str(apply).lower()} "
        f"reason={target.reason}",
        flush=True,
    )

    if apply and paths:
        _delete_paths(target.bucket_id, paths, token=token)
        print(
            "HF_BUCKET_CLEANUP_APPLIED "
            f"bucket={target.bucket_id} prefix={prefix_text} "
            f"files={len(paths)} bytes={total_bytes}",
            flush=True,
        )
    return len(paths), total_bytes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("scheduled", "purge-test"), default="scheduled")
    parser.add_argument("--apply", action="store_true", help="Actually delete selected objects")
    parser.add_argument("--test-bucket", default=DEFAULT_TEST_BUCKET)
    parser.add_argument("--production-bucket", default=DEFAULT_PRODUCTION_BUCKET)
    parser.add_argument("--test-retention-days", type=int, default=DEFAULT_TEST_RETENTION_DAYS)
    parser.add_argument(
        "--production-diagnostics-retention-days",
        type=int,
        default=DEFAULT_PRODUCTION_DIAGNOSTICS_RETENTION_DAYS,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = os.getenv("HF_TOKEN", "").strip()
    if not token:
        raise SystemExit("HF_TOKEN is required")

    targets = build_targets(
        mode=args.mode,
        now=datetime.now(timezone.utc),
        test_bucket=args.test_bucket,
        production_bucket=args.production_bucket,
        test_retention_days=args.test_retention_days,
        production_diagnostics_retention_days=args.production_diagnostics_retention_days,
    )
    file_count = 0
    byte_count = 0
    for target in targets:
        files, size = execute_target(target, token=token, apply=args.apply)
        file_count += files
        byte_count += size

    print(
        "HF_BUCKET_CLEANUP_SUMMARY "
        f"mode={args.mode} files={file_count} bytes={byte_count} "
        f"apply={str(args.apply).lower()}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
