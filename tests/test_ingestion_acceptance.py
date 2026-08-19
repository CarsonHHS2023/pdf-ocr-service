from __future__ import annotations

import os
from pathlib import Path
import uuid

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.database import SessionLocal, engine as application_engine
from app.models import Base, Document, SourceFile
from app.processing.ingestion_acceptance import (
    IngestionAcceptanceError,
    commit_retained_ingestion,
    find_accepted_ingestion,
    resumable_acceptance_key,
    retain_and_commit_ingestion,
    stable_entity_id,
)
from app.processing.ingestion_dispatch_model import IngestionDispatch
from app.storage.errors import ObjectAlreadyExists
from app.storage.local import LocalStorageProvider


def _session_factory(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'acceptance.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _counts(session_factory) -> tuple[int, int, int]:
    db = session_factory()
    try:
        return (
            int(db.scalar(select(func.count()).select_from(Document)) or 0),
            int(db.scalar(select(func.count()).select_from(SourceFile)) or 0),
            int(db.scalar(select(func.count()).select_from(IngestionDispatch)) or 0),
        )
    finally:
        db.close()


def test_resumable_acceptance_identity_is_deterministic():
    key = resumable_acceptance_key("0123456789abcdef0123456789abcdef")
    assert key == "resumable:0123456789abcdef0123456789abcdef"
    assert stable_entity_id(key, "document") == stable_entity_id(key, "document")
    assert stable_entity_id(key, "source") == stable_entity_id(key, "source")
    assert stable_entity_id(key, "document") != stable_entity_id(key, "source")


def test_same_acceptance_and_bytes_collapse_to_one_business_object(tmp_path):
    session_factory = _session_factory(tmp_path)
    storage = LocalStorageProvider(tmp_path / "storage")
    key = resumable_acceptance_key("a" * 32)
    content = b"same resumable upload"

    db = session_factory()
    try:
        first = retain_and_commit_ingestion(
            db,
            storage,
            acceptance_key=key,
            filename="book.txt",
            file_type="txt",
            mime_type="text/plain",
            content=content,
        )
    finally:
        db.close()

    db = session_factory()
    try:
        second = retain_and_commit_ingestion(
            db,
            storage,
            acceptance_key=key,
            filename="book.txt",
            file_type="txt",
            mime_type="text/plain",
            content=content,
        )
    finally:
        db.close()

    assert first.created is True
    assert second.created is False
    assert first.document_id == second.document_id
    assert first.source_file_id == second.source_file_id
    assert first.dispatch_id == second.dispatch_id
    assert _counts(session_factory) == (1, 1, 1)


def test_same_acceptance_with_different_bytes_fails_before_duplicate_metadata(tmp_path):
    session_factory = _session_factory(tmp_path)
    storage = LocalStorageProvider(tmp_path / "storage")
    key = resumable_acceptance_key("b" * 32)

    db = session_factory()
    try:
        retain_and_commit_ingestion(
            db,
            storage,
            acceptance_key=key,
            filename="book.txt",
            file_type="txt",
            mime_type="text/plain",
            content=b"first bytes",
        )
    finally:
        db.close()

    db = session_factory()
    try:
        with pytest.raises(ObjectAlreadyExists):
            retain_and_commit_ingestion(
                db,
                storage,
                acceptance_key=key,
                filename="book.txt",
                file_type="txt",
                mime_type="text/plain",
                content=b"different bytes",
            )
    finally:
        db.close()

    assert _counts(session_factory) == (1, 1, 1)


def test_existing_acceptance_identity_conflict_fails_closed(tmp_path):
    session_factory = _session_factory(tmp_path)
    storage = LocalStorageProvider(tmp_path / "storage")
    key = resumable_acceptance_key("c" * 32)

    db = session_factory()
    try:
        accepted = retain_and_commit_ingestion(
            db,
            storage,
            acceptance_key=key,
            filename="book.txt",
            file_type="txt",
            mime_type="text/plain",
            content=b"identity bytes",
        )
    finally:
        db.close()

    db = session_factory()
    try:
        with pytest.raises(IngestionAcceptanceError):
            find_accepted_ingestion(
                db,
                key,
                expected_document_id="not-the-durable-document",
            )
        row = find_accepted_ingestion(
            db,
            key,
            expected_document_id=accepted.document_id,
            expected_source_file_id=accepted.source_file_id,
        )
        assert row is not None
        assert row.dispatch_id == accepted.dispatch_id
    finally:
        db.close()


def test_commit_failure_rolls_back_document_source_and_dispatch(tmp_path, monkeypatch):
    session_factory = _session_factory(tmp_path)
    db = session_factory()
    real_commit = db.commit
    calls = 0

    def fail_first_commit():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic database commit failure")
        return real_commit()

    monkeypatch.setattr(db, "commit", fail_first_commit)
    try:
        with pytest.raises(RuntimeError, match="synthetic database commit failure"):
            commit_retained_ingestion(
                db,
                acceptance_key="legacy:failure-test",
                filename="book.txt",
                file_type="txt",
                mime_type="text/plain",
                byte_size=3,
                checksum_sha256="a" * 64,
                storage_reference="src_" + "1" * 32,
            )
    finally:
        db.close()

    assert _counts(session_factory) == (0, 0, 0)


def test_checksum_validation_rejects_non_hex_identity_before_database_changes(tmp_path):
    session_factory = _session_factory(tmp_path)
    db = session_factory()
    try:
        with pytest.raises(ValueError, match="64 hexadecimal"):
            commit_retained_ingestion(
                db,
                acceptance_key="legacy:bad-checksum",
                filename="book.txt",
                file_type="txt",
                mime_type="text/plain",
                byte_size=3,
                checksum_sha256="z" * 64,
                storage_reference="src_" + "2" * 32,
            )
    finally:
        db.close()

    assert _counts(session_factory) == (0, 0, 0)


@pytest.mark.skipif(
    os.getenv("ATLAS_POSTGRESQL_SCHEMA_TEST") != "1",
    reason="requires the disposable PostgreSQL staging CI service",
)
def test_commit_retained_ingestion_orders_parent_rows_before_dispatch_on_postgresql():
    assert application_engine.dialect.name == "postgresql"
    acceptance_key = f"ci-postgres:{uuid.uuid4().hex}"
    document_id = str(uuid.uuid4())
    source_file_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        accepted = commit_retained_ingestion(
            db,
            acceptance_key=acceptance_key,
            filename="postgres-ordering.txt",
            file_type="txt",
            mime_type="text/plain",
            byte_size=3,
            checksum_sha256="b" * 64,
            storage_reference=f"src_{uuid.uuid4().hex}",
            document_id=document_id,
            source_file_id=source_file_id,
        )
        assert accepted.created is True
        assert accepted.document_id == document_id
        assert accepted.source_file_id == source_file_id
        dispatch = db.get(IngestionDispatch, accepted.dispatch_id)
        assert dispatch is not None
        assert dispatch.document_id == document_id
        assert dispatch.source_file_id == source_file_id
        assert dispatch.status == "queued"
    finally:
        try:
            document = db.get(Document, document_id)
            if document is not None:
                db.delete(document)
                db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
