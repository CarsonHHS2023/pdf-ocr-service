"""Fail-closed SQLite -> PostgreSQL data replay for Atlas recovery migration.

The migration deliberately treats Structured Content v2 differently from the
legacy relational tables.  Legacy rows keep their existing primary keys.  V2
candidates are reconstructed through the domain repository and re-persisted so
new internal record UUIDs are generated; selections are then resolved from the
public candidate_id instead of copying the old candidate_record_id.

The caller owns the source artifact and target database selection.  This module
never discovers Production resources and never mutates the source SQLite file.
"""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from app.database import normalize_database_url
from app.models import Base, Document
import app.models_v2  # noqa: F401 - register v2 tables in Base.metadata
import app.models_v2_selection  # noqa: F401 - register v2 selection table
import app.processing.ingestion_dispatch_model  # noqa: F401 - register dispatch table
from app.models_v2 import StructuredContentCandidateV2Record as CandidateRow
from app.models_v2_selection import StructuredContentSelectionV2Record as SelectionRow
from app.reader_v2.service import build_selected_reader_v2_document
from app.structured_content_v2.repository import StructuredContentCandidateV2Repository
from app.structured_content_v2.selection import StructuredContentV2SelectionRepository

EXPECTED_ALEMBIC_HEAD = "0006_ingestion_dispatches"
_V2_PREFIX = "structured_content_v2_"


class PostgreSQLDataMigrationError(RuntimeError):
    """Raised when the recovery migration cannot prove its safety contract."""


@dataclass(frozen=True, slots=True)
class PostgreSQLDataMigrationReport:
    source_sha256: str
    source_byte_size: int
    source_alembic_head: str
    target_alembic_head: str
    application_table_count: int
    migrated_candidate_count: int
    migrated_selection_count: int
    reader_ready_count: int
    reader_not_ready_count: int
    source_row_counts: dict[str, int]
    target_row_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _readonly_sqlite_engine(path: Path) -> Engine:
    resolved = path.resolve()
    if resolved.is_symlink() or not resolved.is_file():
        raise PostgreSQLDataMigrationError("source SQLite artifact is unavailable")

    def _connect():
        return sqlite3.connect(f"file:{resolved}?mode=ro", uri=True, timeout=30.0)

    return create_engine("sqlite://", creator=_connect)


def _application_tables():
    return tuple(table for table in Base.metadata.sorted_tables if table.name != "alembic_version")


def _row_count(connection: Connection, table) -> int:
    return int(connection.execute(select(func.count()).select_from(table)).scalar_one())


def _row_counts(connection: Connection) -> dict[str, int]:
    return {table.name: _row_count(connection, table) for table in _application_tables()}


def _database_alembic_head(connection: Connection) -> str:
    value = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    if not isinstance(value, str) or not value:
        raise PostgreSQLDataMigrationError("database has no Alembic head revision")
    return value


def _validate_source_sqlite(path: Path, connection: Connection) -> tuple[str, int]:
    raw = connection.connection.driver_connection
    quick = tuple(str(row[0]).strip().lower() for row in raw.execute("PRAGMA quick_check"))
    integrity = tuple(str(row[0]).strip().lower() for row in raw.execute("PRAGMA integrity_check"))
    foreign_keys = tuple(raw.execute("PRAGMA foreign_key_check"))
    if quick != ("ok",):
        raise PostgreSQLDataMigrationError(f"source SQLite quick_check failed: {quick!r}")
    if integrity != ("ok",):
        raise PostgreSQLDataMigrationError(f"source SQLite integrity_check failed: {integrity!r}")
    if foreign_keys:
        raise PostgreSQLDataMigrationError(
            f"source SQLite foreign_key_check found {len(foreign_keys)} violation(s)"
        )
    head = _database_alembic_head(connection)
    if head != EXPECTED_ALEMBIC_HEAD:
        raise PostgreSQLDataMigrationError(f"unexpected source Alembic head: {head}")
    return _sha256_file(path), int(path.stat().st_size)


def _validate_target_postgresql(connection: Connection) -> str:
    if connection.dialect.name != "postgresql":
        raise PostgreSQLDataMigrationError(
            f"target must be PostgreSQL, got dialect={connection.dialect.name}"
        )
    head = _database_alembic_head(connection)
    if head != EXPECTED_ALEMBIC_HEAD:
        raise PostgreSQLDataMigrationError(f"unexpected target Alembic head: {head}")

    existing_tables = set(
        connection.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE'"
            )
        ).scalars()
    )
    expected_tables = {table.name for table in _application_tables()}
    missing = sorted(expected_tables - existing_tables)
    if missing:
        raise PostgreSQLDataMigrationError(f"target PostgreSQL schema is incomplete: {missing}")

    populated = {name: count for name, count in _row_counts(connection).items() if count}
    if populated:
        raise PostgreSQLDataMigrationError(
            f"target PostgreSQL is not empty; refusing replay: {populated}"
        )
    return head


def _self_fk_order(table, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order rows so self-referenced parents are inserted before children."""
    self_constraints = [
        constraint
        for constraint in table.foreign_key_constraints
        if constraint.referred_table is table
    ]
    if not self_constraints or len(rows) < 2:
        return rows

    dependencies: list[set[int]] = [set() for _ in rows]
    for constraint in self_constraints:
        local_columns = [element.parent.name for element in constraint.elements]
        remote_columns = [element.column.name for element in constraint.elements]
        remote_index = {
            tuple(row[column] for column in remote_columns): index
            for index, row in enumerate(rows)
        }
        for index, row in enumerate(rows):
            local_key = tuple(row[column] for column in local_columns)
            if any(value is None for value in local_key):
                continue
            parent_index = remote_index.get(local_key)
            if parent_index is None:
                raise PostgreSQLDataMigrationError(
                    f"self-referential row in {table.name} points outside the copied row set"
                )
            if parent_index != index:
                dependencies[index].add(parent_index)

    remaining = set(range(len(rows)))
    ordered: list[dict[str, Any]] = []
    emitted: set[int] = set()
    while remaining:
        ready = sorted(index for index in remaining if dependencies[index] <= emitted)
        if not ready:
            raise PostgreSQLDataMigrationError(
                f"self-referential dependency cycle detected in table {table.name}"
            )
        for index in ready:
            ordered.append(rows[index])
            emitted.add(index)
            remaining.remove(index)
    return ordered


def _copy_legacy_tables(source: Connection, target: Connection) -> None:
    for table in _application_tables():
        if table.name.startswith(_V2_PREFIX):
            continue
        rows = [dict(row) for row in source.execute(select(table)).mappings().all()]
        if not rows:
            continue
        rows = _self_fk_order(table, rows)
        # Execute rows in proven dependency order.  This also avoids relying on
        # driver-specific executemany ordering for self-referential tables.
        for row in rows:
            target.execute(table.insert().values(**row))


def _reader_fingerprints(session: Session) -> dict[str, tuple[str, int, int, int] | None]:
    result: dict[str, tuple[str, int, int, int] | None] = {}
    documents = session.execute(select(Document).order_by(Document.id)).scalars().all()
    for document in documents:
        try:
            view = build_selected_reader_v2_document(session=session, document_ref=document.id)
        except Exception:  # readiness parity is checked; source errors are not hidden
            result[document.id] = None
            continue
        result[document.id] = (
            view.candidate_id,
            len(view.source_units),
            len(view.nodes),
            len(view.navigation),
        )
    return result


def _replay_v2(source_session: Session, target_session: Session) -> tuple[int, int]:
    candidates = StructuredContentCandidateV2Repository()
    selections = StructuredContentV2SelectionRepository(candidates)

    source_candidate_rows = source_session.execute(
        select(CandidateRow).order_by(CandidateRow.created_at, CandidateRow.candidate_id)
    ).scalars().all()
    for source_row in source_candidate_rows:
        candidate = candidates.get_candidate(source_session, source_row.candidate_id)
        candidates.create_candidate(target_session, candidate)
        target_row = target_session.execute(
            select(CandidateRow).where(CandidateRow.candidate_id == source_row.candidate_id)
        ).scalar_one()
        # Internal record IDs deliberately differ; preserve only durable metadata.
        if target_row.id == source_row.id:
            raise PostgreSQLDataMigrationError(
                f"v2 candidate internal ID was not regenerated: {source_row.candidate_id}"
            )
        target_row.created_at = source_row.created_at
        target_session.flush()

    source_selection_rows = source_session.execute(
        select(SelectionRow).order_by(SelectionRow.document_id)
    ).scalars().all()
    for source_selection in source_selection_rows:
        source_candidate = source_session.get(CandidateRow, source_selection.candidate_record_id)
        if source_candidate is None or source_candidate.document_id != source_selection.document_id:
            raise PostgreSQLDataMigrationError(
                f"source v2 selection is inconsistent for document {source_selection.document_id}"
            )
        if int(source_selection.selection_version) < 1:
            raise PostgreSQLDataMigrationError(
                f"source v2 selection version is invalid for document {source_selection.document_id}"
            )
        selections.set_selection(
            target_session,
            document_ref=source_selection.document_id,
            candidate_id=source_candidate.candidate_id,
            expected_version=0,
            selection_actor_ref=source_selection.selection_actor_ref,
            reason=source_selection.reason,
        )
        target_selection = target_session.get(SelectionRow, source_selection.document_id)
        if target_selection is None:
            raise PostgreSQLDataMigrationError("target v2 selection was not created")
        if target_selection.candidate_record_id == source_selection.candidate_record_id:
            raise PostgreSQLDataMigrationError(
                f"v2 selection reused source internal candidate ID: {source_selection.document_id}"
            )
        target_selection.selection_version = source_selection.selection_version
        target_selection.selected_at = source_selection.selected_at
        target_selection.selection_actor_ref = source_selection.selection_actor_ref
        target_selection.reason = source_selection.reason
        target_session.flush()

    return len(source_candidate_rows), len(source_selection_rows)


def migrate_sqlite_to_postgresql(
    *,
    source_sqlite_path: str | Path,
    target_database_url: str,
    expected_source_sha256: str | None = None,
) -> PostgreSQLDataMigrationReport:
    """Replay one clean SQLite recovery artifact into one empty PostgreSQL DB.

    The PostgreSQL transaction commits only after row-count and Reader parity
    validation succeeds.  Any exception rolls back the target replay.
    """
    source_path = Path(source_sqlite_path)
    source_engine = _readonly_sqlite_engine(source_path)
    target_engine = create_engine(
        normalize_database_url(target_database_url),
        pool_pre_ping=True,
    )

    try:
        with source_engine.connect() as source_connection:
            source_sha256, source_size = _validate_source_sqlite(source_path, source_connection)
            if expected_source_sha256 and source_sha256 != expected_source_sha256:
                raise PostgreSQLDataMigrationError(
                    f"source SHA-256 mismatch: {source_sha256} != {expected_source_sha256}"
                )
            source_head = _database_alembic_head(source_connection)
            source_counts = _row_counts(source_connection)

            with target_engine.begin() as target_connection:
                target_head = _validate_target_postgresql(target_connection)
                _copy_legacy_tables(source_connection, target_connection)

                source_session = Session(bind=source_connection)
                # rollback_only makes Session.commit() flush/end its unit of work
                # without committing the enclosing PostgreSQL Connection txn.
                target_session = Session(
                    bind=target_connection,
                    join_transaction_mode="rollback_only",
                )
                try:
                    source_reader = _reader_fingerprints(source_session)
                    candidate_count, selection_count = _replay_v2(
                        source_session, target_session
                    )
                    target_session.commit()

                    target_counts = _row_counts(target_connection)
                    if source_counts != target_counts:
                        differences = {
                            name: (source_counts.get(name), target_counts.get(name))
                            for name in sorted(set(source_counts) | set(target_counts))
                            if source_counts.get(name) != target_counts.get(name)
                        }
                        raise PostgreSQLDataMigrationError(
                            f"source/target row-count mismatch: {differences}"
                        )

                    target_reader = _reader_fingerprints(target_session)
                    if source_reader != target_reader:
                        differences = {
                            document_id: (source_reader.get(document_id), target_reader.get(document_id))
                            for document_id in sorted(set(source_reader) | set(target_reader))
                            if source_reader.get(document_id) != target_reader.get(document_id)
                        }
                        raise PostgreSQLDataMigrationError(
                            f"source/target Reader fingerprint mismatch: {differences}"
                        )
                    reader_ready = sum(value is not None for value in target_reader.values())
                    reader_not_ready = len(target_reader) - reader_ready
                finally:
                    source_session.close()
                    target_session.close()

                # Leaving target_engine.begin() commits only after every proof above.
                return PostgreSQLDataMigrationReport(
                    source_sha256=source_sha256,
                    source_byte_size=source_size,
                    source_alembic_head=source_head,
                    target_alembic_head=target_head,
                    application_table_count=len(source_counts),
                    migrated_candidate_count=candidate_count,
                    migrated_selection_count=selection_count,
                    reader_ready_count=reader_ready,
                    reader_not_ready_count=reader_not_ready,
                    source_row_counts=source_counts,
                    target_row_counts=target_counts,
                )
    finally:
        source_engine.dispose()
        target_engine.dispose()


__all__ = [
    "EXPECTED_ALEMBIC_HEAD",
    "PostgreSQLDataMigrationError",
    "PostgreSQLDataMigrationReport",
    "migrate_sqlite_to_postgresql",
]
