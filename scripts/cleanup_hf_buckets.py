"""Clean expired artifacts from the Staging Hugging Face Storage Bucket.

Staging is a development/test environment, so objects in its dedicated private
bucket are temporary by policy. Scheduled cleanup deletes only files older than
the configured retention window (30 days by default). Production storage is not
referenced or targeted by this utility.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
from typing import Iterable, Iterator, Sequence

DEFAULT_STAGING_BUCKET = "carsonhhs/pdf-ocr-service-ocrmypdf-test-storage"
DEFAULT_STAGING_RETENTION_DAYS = 30
_DELETE_BATCH_SIZE = 500


@dataclass(frozen=True)
class CleanupTarget:
    bucket_id: str
    cutoff: datetime
    reason: str


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def select_expired_files(items: Iterable[object], *, cutoff: datetime) -> list[object]:
    """Return Staging file entries older than ``cutoff``.

    Unknown timestamps fail closed: the object is retained rather than deleted.
    Directories are never deletion candidates.
    """
    selected: list[object] = []
    normalized_cutoff = _utc(cutoff)
    for item in items:
        if getattr(item, "type", None) != "file":
            continue
        path = getattr(item, "path", None)
        if not isinstance(path, str) or not path:
            continue
        mtime = getattr(item, "mtime", None)
        if not isinstance(mtime, datetime):
            continue
        if _utc(mtime) < normalized_cutoff:
            selected.append(item)
    return selected


def chunked(values: Sequence[str], size: int = _DELETE_BATCH_SIZE) -> Iterator[list[str]]:
    if size <= 0:
        raise ValueError("chunk size must be positive")
    for start in range(0, len(values), size):
        yield list(values[start : start + size])


def build_target(
    *,
    now: datetime,
    staging_bucket: str = DEFAULT_STAGING_BUCKET,
    retention_days: int = DEFAULT_STAGING_RETENTION_DAYS,
) -> CleanupTarget:
    if not isinstance(staging_bucket, str) or not staging_bucket.strip():
        raise ValueError("staging bucket must be non-empty")
    if retention_days <= 0:
        raise ValueError("retention days must be positive")
    return CleanupTarget(
        bucket_id=staging_bucket.strip(),
        cutoff=_utc(now) - timedelta(days=retention_days),
        reason=f"Staging artifacts older than {retention_days} days",
    )


def _list_target_files(target: CleanupTarget, *, token: str) -> list[object]:
    from huggingface_hub import list_bucket_tree

    return list(
        list_bucket_tree(
            target.bucket_id,
            recursive=True,
            token=token,
        )
    )


def _delete_paths(bucket_id: str, paths: Sequence[str], *, token: str) -> None:
    from huggingface_hub import batch_bucket_files

    for batch in chunked(paths):
        batch_bucket_files(bucket_id, delete=batch, token=token)


def _is_bucket_not_found(exc: BaseException) -> bool:
    try:
        from huggingface_hub.errors import BucketNotFoundError
    except ImportError:
        return False
    return isinstance(exc, BucketNotFoundError)


def execute_target(target: CleanupTarget, *, token: str, apply: bool) -> tuple[int, int]:
    try:
        items = _list_target_files(target, token=token)
    except Exception as exc:
        if _is_bucket_not_found(exc):
            raise RuntimeError(
                "Staging bucket is not accessible to the configured HF_TOKEN: "
                f"{target.bucket_id}. Verify the bucket id and grant the token "
                "read/delete access to this private bucket."
            ) from exc
        raise

    selected = select_expired_files(items, cutoff=target.cutoff)
    paths = [str(getattr(item, "path")) for item in selected]
    total_bytes = sum(
        int(size)
        for item in selected
        if isinstance((size := getattr(item, "size", None)), int) and size >= 0
    )
    print(
        "HF_BUCKET_CLEANUP_PLAN "
        f"environment=staging bucket={target.bucket_id} prefix=<bucket-root> "
        f"cutoff={target.cutoff.isoformat()} files={len(paths)} bytes={total_bytes} "
        f"apply={str(apply).lower()} reason={target.reason}",
        flush=True,
    )

    if apply and paths:
        _delete_paths(target.bucket_id, paths, token=token)
        print(
            "HF_BUCKET_CLEANUP_APPLIED "
            f"environment=staging bucket={target.bucket_id} prefix=<bucket-root> "
            f"files={len(paths)} bytes={total_bytes}",
            flush=True,
        )
    return len(paths), total_bytes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Actually delete selected objects")
    parser.add_argument("--staging-bucket", default=DEFAULT_STAGING_BUCKET)
    parser.add_argument("--retention-days", type=int, default=DEFAULT_STAGING_RETENTION_DAYS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = os.getenv("HF_TOKEN", "").strip()
    if not token:
        raise SystemExit("HF_TOKEN is required")

    target = build_target(
        now=datetime.now(timezone.utc),
        staging_bucket=args.staging_bucket,
        retention_days=args.retention_days,
    )
    files, size = execute_target(target, token=token, apply=args.apply)
    print(
        "HF_BUCKET_CLEANUP_SUMMARY "
        f"environment=staging files={files} bytes={size} "
        f"apply={str(args.apply).lower()}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
