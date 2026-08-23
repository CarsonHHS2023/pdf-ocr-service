#!/usr/bin/env python3
"""Render read-only S0 baseline snapshots from the configured Atlas database."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import SessionLocal
from app.processing.s0_baseline import collect_s0_run_snapshot, render_s0_markdown


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
                "runs": [snapshot.to_dict() for snapshot in snapshots],
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ) + "\n"
    else:
        output = render_s0_markdown(snapshots)

    if args.output is None:
        sys.stdout.write(output)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
