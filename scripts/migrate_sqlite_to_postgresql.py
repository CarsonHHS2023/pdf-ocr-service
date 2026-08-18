#!/usr/bin/env python3
"""Replay one vetted SQLite recovery artifact into an empty PostgreSQL database."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.postgresql_data_migration import migrate_sqlite_to_postgresql


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-sqlite", required=True, type=Path)
    parser.add_argument(
        "--target-database-url",
        default=os.getenv("DATABASE_URL", ""),
        help="PostgreSQL URL; defaults to DATABASE_URL",
    )
    parser.add_argument(
        "--expected-source-sha256",
        default=None,
        help="Optional fail-closed SHA-256 pin for the source recovery artifact",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if not args.target_database_url:
        raise SystemExit("target PostgreSQL URL is required")
    report = migrate_sqlite_to_postgresql(
        source_sqlite_path=args.source_sqlite,
        target_database_url=args.target_database_url,
        expected_source_sha256=args.expected_source_sha256,
    )
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
