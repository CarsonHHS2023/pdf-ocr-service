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
from app.processing.s0_baseline import collect_s0_run_snapshot, render_s0_markdown


_SAFE_RECORD_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+~-]{0,159}$")


def _validated_record_token(option: str, value: str) -> str:
    if not isinstance(value, str) or _SAFE_RECORD_TOKEN.fullmatch(value) is None:
        raise SystemExit(
            f"{option} must be a privacy-safe token using only letters, digits, "
            ". _ : @ / + ~ - (maximum 160 characters)"
        )
    return value


def _benchmark_record_metadata(args: argparse.Namespace) -> dict[str, object]:
    if len(args.fixture_ids) != len(args.processing_run_ids):
        raise SystemExit(
            "supply exactly one --fixture-id for each --processing-run-id, in the same order"
        )

    fixture_registry_version = _validated_record_token(
        "--fixture-registry-version", args.fixture_registry_version
    )
    backend_git_revision = _validated_record_token(
        "--backend-git-revision", args.backend_git_revision
    )
    staging_runtime_revision = _validated_record_token(
        "--staging-runtime-revision", args.staging_runtime_revision
    )
    runs = []
    for run_id, fixture_id in zip(args.processing_run_ids, args.fixture_ids, strict=True):
        runs.append(
            {
                "processing_run_id": _validated_record_token("--processing-run-id", run_id),
                "fixture_id": _validated_record_token("--fixture-id", fixture_id),
            }
        )

    return {
        "fixture_registry_version": fixture_registry_version,
        "backend_git_revision": backend_git_revision,
        "staging_runtime_revision": staging_runtime_revision,
        "runs": runs,
    }


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
        help="Fixture registry version for this benchmark record, for example v1",
    )
    parser.add_argument(
        "--backend-git-revision",
        required=True,
        help="Exact backend Git revision used by the measured Staging runtime",
    )
    parser.add_argument(
        "--staging-runtime-revision",
        required=True,
        help="Explicit Staging deployment/runtime revision for the measured run",
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
