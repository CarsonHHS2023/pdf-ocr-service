from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import sys

import pytest

import scripts.cleanup_hf_buckets as cleanup
from scripts.cleanup_hf_buckets import (
    DEFAULT_STAGING_BUCKET,
    DEFAULT_STAGING_RETENTION_DAYS,
    CleanupTarget,
    build_target,
    chunked,
    execute_target,
    select_expired_files,
)


def _item(path: str, *, age_days: int, now: datetime, item_type: str = "file", size: int = 10):
    return SimpleNamespace(
        type=item_type,
        path=path,
        mtime=now - timedelta(days=age_days),
        size=size,
    )


def test_target_is_hard_locked_to_staging_bucket_with_30_day_retention() -> None:
    now = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)

    target = build_target(now=now)

    assert DEFAULT_STAGING_BUCKET == "carsonhhs/pdf-ocr-service-ocrmypdf-test-storage"
    assert DEFAULT_STAGING_RETENTION_DAYS == 30
    assert target.bucket_id == DEFAULT_STAGING_BUCKET
    assert target.cutoff == now - timedelta(days=30)
    assert target.reason == "Staging artifacts older than 30 days"


def test_cli_rejects_bucket_and_retention_overrides(monkeypatch) -> None:
    for argv in (
        ["cleanup_hf_buckets.py", "--staging-bucket", "carsonhhs/pdf-ocr-service-storage"],
        ["cleanup_hf_buckets.py", "--retention-days", "1"],
    ):
        monkeypatch.setattr(sys, "argv", argv)
        with pytest.raises(SystemExit) as caught:
            cleanup.parse_args()
        assert caught.value.code == 2


def test_select_expired_files_deletes_only_files_older_than_30_days() -> None:
    now = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    cutoff = now - timedelta(days=30)
    unknown = SimpleNamespace(type="file", path="unknown.bin", mtime=None, size=10)
    directory = _item("folder", age_days=100, now=now, item_type="directory")
    recent = _item("recent.bin", age_days=29, now=now)
    boundary = _item("boundary.bin", age_days=30, now=now)
    old = _item("old.bin", age_days=31, now=now)

    selected = select_expired_files(
        [unknown, directory, recent, boundary, old],
        cutoff=cutoff,
    )

    assert [item.path for item in selected] == ["old.bin"]


def test_execute_target_rejects_any_non_staging_bucket_before_listing(monkeypatch) -> None:
    target = CleanupTarget(
        bucket_id="carsonhhs/pdf-ocr-service-storage",
        cutoff=datetime(2026, 7, 24, tzinfo=timezone.utc),
        reason="tampered target",
    )
    listed = False

    def should_not_list(*_args, **_kwargs):
        nonlocal listed
        listed = True
        return []

    monkeypatch.setattr(cleanup, "_list_target_files", should_not_list)

    with pytest.raises(ValueError, match="exact Staging bucket"):
        execute_target(target, token="test-token", apply=True)

    assert listed is False


def test_delete_paths_rejects_non_staging_bucket() -> None:
    with pytest.raises(ValueError, match="exact Staging bucket"):
        cleanup._delete_paths(
            "carsonhhs/pdf-ocr-service-storage",
            ["old.bin"],
            token="test-token",
        )


def test_inaccessible_private_staging_bucket_fails_with_actionable_error(monkeypatch) -> None:
    target = build_target(now=datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc))
    inaccessible = RuntimeError("bucket hidden by private access")

    def raise_inaccessible(*_args, **_kwargs):
        raise inaccessible

    monkeypatch.setattr(cleanup, "_list_target_files", raise_inaccessible)
    monkeypatch.setattr(cleanup, "_is_bucket_not_found", lambda exc: exc is inaccessible)

    with pytest.raises(RuntimeError, match="not accessible to the configured HF_TOKEN") as caught:
        execute_target(target, token="test-token", apply=True)

    assert DEFAULT_STAGING_BUCKET in str(caught.value)
    assert "read/delete access" in str(caught.value)


def test_dry_run_reports_expired_staging_files_without_deleting(monkeypatch, capsys) -> None:
    now = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    target = build_target(now=now)
    old = _item("output/test.bin", age_days=31, now=now, size=123)
    deleted: list[str] = []

    monkeypatch.setattr(cleanup, "_list_target_files", lambda *_args, **_kwargs: [old])
    monkeypatch.setattr(
        cleanup,
        "_delete_paths",
        lambda _bucket, paths, **_kwargs: deleted.extend(paths),
    )

    assert execute_target(target, token="test-token", apply=False) == (1, 123)
    assert deleted == []
    output = capsys.readouterr().out
    assert "environment=staging" in output
    assert f"bucket={DEFAULT_STAGING_BUCKET}" in output
    assert "apply=false" in output


def test_apply_deletes_only_expired_staging_files(monkeypatch) -> None:
    now = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    target = build_target(now=now)
    recent = _item("recent.bin", age_days=2, now=now)
    old = _item("old.bin", age_days=45, now=now)
    deleted: list[str] = []

    monkeypatch.setattr(
        cleanup,
        "_list_target_files",
        lambda *_args, **_kwargs: [recent, old],
    )
    monkeypatch.setattr(
        cleanup,
        "_delete_paths",
        lambda bucket, paths, **_kwargs: deleted.extend([bucket, *paths]),
    )

    assert execute_target(target, token="test-token", apply=True) == (1, 10)
    assert deleted == [DEFAULT_STAGING_BUCKET, "old.bin"]


def test_chunked_batches_paths() -> None:
    assert list(chunked(["a", "b", "c", "d", "e"], size=2)) == [
        ["a", "b"],
        ["c", "d"],
        ["e"],
    ]
    with pytest.raises(ValueError, match="positive"):
        list(chunked(["a"], size=0))
