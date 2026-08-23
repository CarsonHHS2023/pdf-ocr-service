#!/usr/bin/env python3
"""Render read-only S0 baseline snapshots from the configured Atlas database."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import SessionLocal
from app.processing.s0_baseline import (
    S0RunSnapshot,
    collect_s0_run_snapshot,
    render_s0_markdown,
)


_SUPPORTED_FIXTURE_REGISTRY_VERSION = "v1"
_SUPPORTED_FIXTURE_IDS = frozenset(
    {
        "pdf-small-v1",
        "pdf-medium-v1",
        "pdf-large-v1",
        "txt-small-v1",
        "txt-medium-v1",
    }
)
_PROCESSING_RUN_ID = re.compile(r"^(?:pdf|txt)-ingest-[0-9a-f]{32}$")
_GIT_REVISION = re.compile(r"^[0-9A-Fa-f]{40}$")
_STAGING_RUNTIME_REVISION = re.compile(r"^staging-[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def _validated_processing_run_id(value: str) -> str:
    if not isinstance(value, str) or _PROCESSING_RUN_ID.fullmatch(value) is None:
        raise SystemExit(
            "--processing-run-id must match Atlas ingestion identity "
            "pdf-ingest-<32 lowercase hex> or txt-ingest-<32 lowercase hex>"
        )
    return value


def _validated_fixture_registry_version(value: str) -> str:
    if value != _SUPPORTED_FIXTURE_REGISTRY_VERSION:
        raise SystemExit(
            f"--fixture-registry-version must be {_SUPPORTED_FIXTURE_REGISTRY_VERSION}"
        )
    return value


def _validated_fixture_id(value: str) -> str:
    if value not in _SUPPORTED_FIXTURE_IDS:
        allowed = ", ".join(sorted(_SUPPORTED_FIXTURE_IDS))
        raise SystemExit(f"--fixture-id must be a registered v1 fixture: {allowed}")
    return value


def _validated_backend_git_revision(value: str) -> str:
    if not isinstance(value, str) or _GIT_REVISION.fullmatch(value) is None:
        raise SystemExit("--backend-git-revision must be a full 40-hex Git commit SHA")
    return value.lower()


def _validated_staging_runtime_revision(value: str) -> str:
    if not isinstance(value, str) or _STAGING_RUNTIME_REVISION.fullmatch(value) is None:
        raise SystemExit(
            "--staging-runtime-revision must start with staging- and contain only "
            "letters, digits, hyphens, or underscores"
        )
    return value


def _run_media_type(run_id: str) -> str:
    return run_id.split("-", 1)[0]


def _fixture_media_type(fixture_id: str) -> str:
    return fixture_id.split("-", 1)[0]


def _benchmark_record_metadata(args: argparse.Namespace) -> dict[str, object]:
    if len(args.fixture_ids) != len(args.processing_run_ids):
        raise SystemExit(
            "supply exactly one --fixture-id for each --processing-run-id, in the same order"
        )

    processing_run_ids = [
        _validated_processing_run_id(run_id) for run_id in args.processing_run_ids
    ]
    if len(set(processing_run_ids)) != len(processing_run_ids):
        raise SystemExit(
            "--processing-run-id values must be unique; one durable run may map to only one fixture"
        )

    fixture_registry_version = _validated_fixture_registry_version(
        args.fixture_registry_version
    )
    fixture_ids = [_validated_fixture_id(fixture_id) for fixture_id in args.fixture_ids]
    backend_git_revision = _validated_backend_git_revision(args.backend_git_revision)
    staging_runtime_revision = _validated_staging_runtime_revision(
        args.staging_runtime_revision
    )

    runs = []
    for run_id, fixture_id in zip(processing_run_ids, fixture_ids, strict=True):
        if _run_media_type(run_id) != _fixture_media_type(fixture_id):
            raise SystemExit(
                "--processing-run-id and --fixture-id must have matching pdf/txt media types"
            )
        runs.append({"processing_run_id": run_id, "fixture_id": fixture_id})

    return {
        "fixture_registry_version": fixture_registry_version,
        "backend_git_revision": backend_git_revision,
        "staging_runtime_revision": staging_runtime_revision,
        "runs": runs,
    }


def _validate_snapshot_assignments(
    metadata: dict[str, object],
    snapshots: list[S0RunSnapshot],
) -> None:
    assignments = metadata["runs"]
    if not isinstance(assignments, list) or len(assignments) != len(snapshots):
        raise RuntimeError("benchmark run assignments do not match collected snapshots")

    for assignment, snapshot in zip(assignments, snapshots, strict=True):
        if not isinstance(assignment, dict):
            raise RuntimeError("benchmark run assignment is malformed")
        run_id = assignment.get("processing_run_id")
        fixture_id = assignment.get("fixture_id")
        if snapshot.processing_run_id != run_id:
            raise RuntimeError("benchmark run assignment order does not match collected snapshots")
        expected_media_type = _fixture_media_type(str(fixture_id))
        if snapshot.file_type is None:
            raise SystemExit(
                "collected document file type is unavailable; benchmark media identity cannot be verified"
            )
        if snapshot.file_type != expected_media_type:
            raise SystemExit(
                "collected document file type does not match the processing-run/fixture media type"
            )


def _render_benchmark_record_markdown(metadata: dict[str, object]) -> str:
    lines = [
        "# Atlas S0 Benchmark Run Record",
        "",
        f"- fixture registry version: `{metadata['fixture_registry_version']}`",
        f"- backend Git revision: `{metadata['backend_git_revision']}`",
        f"- Staging runtime revision: `{metadata['staging_runtime_revision']}`",
        "",
        "## Fixture assignments",
        "",
        "| Processing run ID | Fixture ID |",
        "|---|---|",
    ]
    for run in metadata["runs"]:
        lines.append(f"| `{run['processing_run_id']}` | `{run['fixture_id']}` |")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--processing-run-id",
        action="append",
        dest="processing_run_ids",
        required=True,
        help="ProcessingRun id to include; repeat for multiple runs",
    )
    parser.add_argument(
        "--fixture-id",
        action="append",
        dest="fixture_ids",
        required=True,
        help="Fixture registry id paired by position with --processing-run-id; repeat together",
    )
    parser.add_argument(
        "--fixture-registry-version",
        required=True,
        help="Fixture registry version for this benchmark record; currently v1",
    )
    parser.add_argument(
        "--backend-git-revision",
        required=True,
        help="Exact full backend Git commit SHA used by the measured Staging runtime",
    )
    parser.add_argument(
        "--staging-runtime-revision",
        required=True,
        help="Explicit non-path Staging runtime label beginning with staging-",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional output path; stdout is used when omitted",
    )
    parser.add_argument(
        "--max-events",
        type=int,
        default=5000,
        help="Maximum durable events loaded per run (default: 5000)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.max_events <= 0:
        raise SystemExit("--max-events must be positive")
    record_metadata = _benchmark_record_metadata(args)

    db = SessionLocal()
    try:
        snapshots = [
            collect_s0_run_snapshot(
                db,
                processing_run_id=run_id,
                max_events=args.max_events,
            )
            for run_id in args.processing_run_ids
        ]
    finally:
        db.close()

    _validate_snapshot_assignments(record_metadata, snapshots)

    if args.format == "json":
        output = json.dumps(
            {
                "schema_version": "atlas.s0.baseline.collection.v1",
                "benchmark_record": record_metadata,
                "runs": [snapshot.to_dict() for snapshot in snapshots],
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ) + "\n"
    else:
        output = (
            _render_benchmark_record_markdown(record_metadata)
            + "\n"
            + render_s0_markdown(snapshots)
        )

    if args.output is None:
        sys.stdout.write(output)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
