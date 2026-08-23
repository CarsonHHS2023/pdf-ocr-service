from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from scripts.cleanup_hf_buckets import (
    DEFAULT_PRODUCTION_BUCKET,
    DEFAULT_TEST_BUCKET,
    PRODUCTION_CLEANUP_TOKEN_ENV,
    PRODUCTION_DIAGNOSTIC_PREFIXES,
    STAGING_CLEANUP_TOKEN_ENV,
    build_targets,
    chunked,
    scope_items_to_prefix,
    select_expired_files,
)


def _item(path: str, *, age_days: int, now: datetime, item_type: str = "file", size: int = 10):
    return SimpleNamespace(
        type=item_type,
        path=path,
        mtime=now - timedelta(days=age_days),
        size=size,
    )


def test_scheduled_targets_keep_production_policy_and_extend_staging_retention() -> None:
    now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)

    targets = build_targets(mode="scheduled", now=now)

    staging = targets[0]
    production = targets[1:]

    assert staging.bucket_id == DEFAULT_TEST_BUCKET
    assert staging.prefix is None
    assert staging.cutoff == now - timedelta(days=30)
    assert staging.token_env == STAGING_CLEANUP_TOKEN_ENV

    assert [target.prefix for target in production] == list(PRODUCTION_DIAGNOSTIC_PREFIXES)
    assert all(target.bucket_id == DEFAULT_PRODUCTION_BUCKET for target in production)
    assert all(target.cutoff == now - timedelta(days=14) for target in production)
    assert all(target.prefix is not None for target in production)
    assert all(target.token_env == PRODUCTION_CLEANUP_TOKEN_ENV for target in production)


def test_purge_test_never_targets_production_and_uses_staging_token() -> None:
    now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)

    targets = build_targets(mode="purge-test", now=now)

    assert len(targets) == 1
    assert targets[0].bucket_id == DEFAULT_TEST_BUCKET
    assert targets[0].prefix is None
    assert targets[0].cutoff is None
    assert targets[0].token_env == STAGING_CLEANUP_TOKEN_ENV


def test_production_prefix_guard_rejects_similarly_named_neighbor() -> None:
    now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    expected = _item(
        "output/opencv-diagnostics/attempt-1/page.png",
        age_days=30,
        now=now,
    )
    neighbor = _item(
        "output/opencv-diagnostics-backup/keep.png",
        age_days=30,
        now=now,
    )

    scoped = scope_items_to_prefix(
        [expected, neighbor],
        prefix="output/opencv-diagnostics/",
    )

    assert [item.path for item in scoped] == [expected.path]


def test_select_expired_files_keeps_unknown_or_recent_objects() -> None:
    now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    cutoff = now - timedelta(days=30)
    unknown = SimpleNamespace(type="file", path="unknown.bin", mtime=None, size=10)
    directory = _item("folder", age_days=45, now=now, item_type="directory")
    recent = _item("recent.bin", age_days=29, now=now)
    boundary = _item("boundary.bin", age_days=30, now=now)
    old = _item("old.bin", age_days=31, now=now)

    selected = select_expired_files(
        [unknown, directory, recent, boundary, old],
        cutoff=cutoff,
    )

    assert [item.path for item in selected] == ["old.bin"]


def test_purge_selection_includes_all_files_but_not_directories() -> None:
    now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    file_a = _item("a.bin", age_days=0, now=now)
    file_b = SimpleNamespace(type="file", path="b.bin", mtime=None, size=10)
    directory = _item("folder", age_days=30, now=now, item_type="directory")

    selected = select_expired_files([file_a, file_b, directory], cutoff=None)

    assert [item.path for item in selected] == ["a.bin", "b.bin"]


def test_build_targets_rejects_same_bucket_for_test_and_production() -> None:
    with pytest.raises(ValueError, match="must be different"):
        build_targets(
            mode="scheduled",
            now=datetime.now(timezone.utc),
            test_bucket="same/bucket",
            production_bucket="same/bucket",
        )


def test_chunked_batches_paths() -> None:
    assert list(chunked(["a", "b", "c", "d", "e"], size=2)) == [
        ["a", "b"],
        ["c", "d"],
        ["e"],
    ]
    with pytest.raises(ValueError, match="positive"):
        list(chunked(["a"], size=0))