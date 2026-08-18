"""Bounded, read-only database integrity diagnostics for production triage."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Iterable

from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.database import engine

_MAX_INTEGRITY_ERRORS = 100


@dataclass(frozen=True, slots=True)
class DatabaseIntegritySnapshot:
    status: str
    backend: str
    quick_check: str
    integrity_check: str
    classification: str
    issue_count: int
    truncated: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _issues(rows: Iterable[str]) -> tuple[str, ...]:
    values = tuple(str(value).strip() for value in rows if str(value).strip())
    if len(values) == 1 and values[0].lower() == "ok":
        return ()
    return tuple(value for value in values if value.lower() != "ok")


def _is_index_only_issue(message: str) -> bool:
    text = message.lower()
    return "index" in text and (
        "missing from index" in text
        or "wrong # of entries in index" in text
        or "wrong number of entries in index" in text
    )


def _classify(quick_rows: Iterable[str], integrity_rows: Iterable[str]) -> tuple[str, int, bool]:
    quick_issues = _issues(quick_rows)
    integrity_issues = _issues(integrity_rows)
    issue_count = len(integrity_issues) if integrity_issues else len(quick_issues)
    truncated = issue_count >= _MAX_INTEGRITY_ERRORS

    if not quick_issues and not integrity_issues:
        return "ok", 0, False

    # A clean quick_check plus only index-consistency findings from integrity_check
    # is the narrow case where REINDEX may be a safe next candidate after backup.
    if (
        not quick_issues
        and integrity_issues
        and all(_is_index_only_issue(message) for message in integrity_issues)
    ):
        return "index_only", issue_count, truncated

    return "table_or_page_or_unknown", issue_count, truncated


def database_integrity_snapshot(target_engine: Engine = engine) -> DatabaseIntegritySnapshot:
    """Run bounded SQLite checks without modifying application data.

    Raw SQLite messages can contain internal table/index names and are therefore
    never part of the returned snapshot.
    """
    backend = str(target_engine.dialect.name or "unknown")
    if backend != "sqlite":
        return DatabaseIntegritySnapshot(
            status="not_applicable",
            backend=backend,
            quick_check="not_applicable",
            integrity_check="not_applicable",
            classification="not_applicable",
            issue_count=0,
            truncated=False,
        )

    quick_rows: tuple[str, ...] = ()
    integrity_rows: tuple[str, ...] = ()
    try:
        with target_engine.connect() as connection:
            # query_only is connection-local and provides an additional fail-closed
            # guard that this diagnostic cannot mutate application data. Restore it
            # before returning the pooled connection so later requests can still write.
            connection.exec_driver_sql("PRAGMA query_only = ON")
            try:
                quick_rows = tuple(
                    row[0]
                    for row in connection.exec_driver_sql(
                        f"PRAGMA quick_check({_MAX_INTEGRITY_ERRORS})"
                    ).fetchall()
                )
                integrity_rows = tuple(
                    row[0]
                    for row in connection.exec_driver_sql(
                        f"PRAGMA integrity_check({_MAX_INTEGRITY_ERRORS})"
                    ).fetchall()
                )
            finally:
                connection.exec_driver_sql("PRAGMA query_only = OFF")
    except SQLAlchemyError:
        return DatabaseIntegritySnapshot(
            status="error",
            backend="sqlite",
            quick_check="error",
            integrity_check="error",
            classification="table_or_page_or_unknown",
            issue_count=0,
            truncated=False,
        )

    classification, issue_count, truncated = _classify(quick_rows, integrity_rows)
    return DatabaseIntegritySnapshot(
        status="healthy" if classification == "ok" else "corrupt",
        backend="sqlite",
        quick_check="ok" if not _issues(quick_rows) else "issues",
        integrity_check="ok" if not _issues(integrity_rows) else "issues",
        classification=classification,
        issue_count=issue_count,
        truncated=truncated,
    )


@lru_cache(maxsize=1)
def production_database_integrity_snapshot() -> DatabaseIntegritySnapshot:
    """Scan the production engine at most once per process lifetime.

    The health route is intentionally callable without the shared user token so
    operators can diagnose access-gate incidents. Caching prevents repeated
    public requests from repeatedly scanning the SQLite database.
    """
    return database_integrity_snapshot(engine)


__all__ = [
    "DatabaseIntegritySnapshot",
    "database_integrity_snapshot",
    "production_database_integrity_snapshot",
]
