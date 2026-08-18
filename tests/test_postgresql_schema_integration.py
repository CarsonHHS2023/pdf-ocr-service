"""Real-PostgreSQL Alembic/schema smoke for Production stabilization."""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.database import engine

EXPECTED_HEAD = "0005_structured_content_v2_selection"
EXPECTED_ALEMBIC_VERSION_LENGTH = 255
EXPECTED_TABLES = {
    "alembic_version",
    "documents",
    "source_files",
    "processing_runs",
    "structured_content_candidates",
    "structured_content_selection",
    "structured_content_v2_candidates",
    "structured_content_v2_source_units",
    "structured_content_v2_nodes",
    "structured_content_v2_selection",
}

pytestmark = pytest.mark.skipif(
    os.getenv("ATLAS_POSTGRESQL_SCHEMA_TEST") != "1",
    reason="requires the disposable PostgreSQL CI service",
)


def test_alembic_head_and_required_tables_exist_on_postgresql():
    assert engine.dialect.name == "postgresql"
    inspector = inspect(engine)
    assert EXPECTED_TABLES <= set(inspector.get_table_names())

    version_columns = {
        column["name"]: column
        for column in inspector.get_columns("alembic_version")
    }
    assert version_columns["version_num"]["type"].length == EXPECTED_ALEMBIC_VERSION_LENGTH

    with engine.connect() as connection:
        current = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    assert current == EXPECTED_HEAD


def test_v2_selection_has_database_enforced_candidate_document_fk():
    inspector = inspect(engine)
    foreign_keys = inspector.get_foreign_keys("structured_content_v2_selection")
    composite = [
        fk
        for fk in foreign_keys
        if fk.get("name") == "fk_scv2_selection_candidate_document"
    ]
    assert len(composite) == 1
    assert composite[0]["constrained_columns"] == ["candidate_record_id", "document_id"]
    assert composite[0]["referred_table"] == "structured_content_v2_candidates"
    assert composite[0]["referred_columns"] == ["id", "document_id"]


def test_v2_selection_round_trip_and_invalid_reference_rejected():
    document_id = str(uuid.uuid4())
    candidate_record_id = str(uuid.uuid4())
    candidate_id = f"ci-{uuid.uuid4()}"

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO documents (
                    id, document_type, title, file_type, status, created_at, updated_at
                ) VALUES (
                    :id, 'book', 'PostgreSQL CI', 'txt', 'completed', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            ),
            {"id": document_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO structured_content_v2_candidates (
                    id, candidate_id, document_id, lineage_key, schema_id, schema_version,
                    recovery_state, total_source_unit_count, complete_source_unit_count,
                    degraded_source_unit_count, no_usable_source_unit_count,
                    unavailable_source_unit_count, created_at
                ) VALUES (
                    :id, :candidate_id, :document_id, 'ci-lineage', 'atlas.structured-content', 2,
                    'complete', 0, 0, 0, 0, 0, CURRENT_TIMESTAMP
                )
                """
            ),
            {
                "id": candidate_record_id,
                "candidate_id": candidate_id,
                "document_id": document_id,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO structured_content_v2_selection (
                    document_id, candidate_record_id, selection_version, selected_at
                ) VALUES (:document_id, :candidate_record_id, 1, CURRENT_TIMESTAMP)
                """
            ),
            {"document_id": document_id, "candidate_record_id": candidate_record_id},
        )

    with engine.connect() as connection:
        selected = connection.execute(
            text(
                """
                SELECT candidate_record_id, selection_version
                FROM structured_content_v2_selection
                WHERE document_id = :document_id
                """
            ),
            {"document_id": document_id},
        ).one()
    assert selected.candidate_record_id == candidate_record_id
    assert selected.selection_version == 1

    invalid_document_id = str(uuid.uuid4())
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO documents (
                    id, document_type, title, file_type, status, created_at, updated_at
                ) VALUES (
                    :id, 'book', 'Invalid FK Probe', 'txt', 'completed', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            ),
            {"id": invalid_document_id},
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO structured_content_v2_selection (
                        document_id, candidate_record_id, selection_version, selected_at
                    ) VALUES (:document_id, :candidate_record_id, 1, CURRENT_TIMESTAMP)
                    """
                ),
                {
                    "document_id": invalid_document_id,
                    "candidate_record_id": candidate_record_id,
                },
            )
