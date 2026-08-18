"""Real-PostgreSQL integration test for recovery data replay."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.database import normalize_database_url
from app.models import Base, Document
import app.models_v2  # noqa: F401
import app.models_v2_selection  # noqa: F401
from app.models_v2 import StructuredContentCandidateV2Record as CandidateRow
from app.models_v2_selection import StructuredContentSelectionV2Record as SelectionRow
from app.postgresql_data_migration import migrate_sqlite_to_postgresql
from app.source_units import SourceUnit, SourceUnitKind, TextSpanAnchor
from app.structured_content_v2.model import (
    ContentNodeTypeV2,
    ContentNodeV2,
    ContentRecoveryStateV2,
    ContentRecoverySummaryV2,
    StructuredContentCandidateV2,
    StructuredSourceUnit,
    normalize_candidate_v2,
)
from app.structured_content_v2.repository import StructuredContentCandidateV2Repository
from app.structured_content_v2.selection import StructuredContentV2SelectionRepository

pytestmark = pytest.mark.skipif(
    os.getenv("ATLAS_POSTGRESQL_SCHEMA_TEST") != "1",
    reason="requires the disposable PostgreSQL CI service",
)


def _candidate() -> StructuredContentCandidateV2:
    unit = SourceUnit(
        "flow-1",
        SourceUnitKind.TEXT_FLOW,
        0,
        "source-test",
        source_span=TextSpanAnchor("flow-1", 0, 100),
    )
    heading_anchor = TextSpanAnchor("flow-1", 0, 10)
    body_anchor = TextSpanAnchor("flow-1", 11, 100)
    return StructuredContentCandidateV2(
        document_ref="migration-doc",
        candidate_id="migration-candidate",
        lineage_key="migration-lineage",
        recovery_summary=ContentRecoverySummaryV2(
            ContentRecoveryStateV2.COMPLETE,
            1,
            complete_source_units=1,
        ),
        source_units=(StructuredSourceUnit(unit),),
        nodes=(
            ContentNodeV2(
                "heading-1",
                "heading-lineage",
                ContentNodeTypeV2.HEADING,
                ("flow-1",),
                0,
                text="Chapter",
                heading_level=1,
                source_anchors=(heading_anchor,),
            ),
            ContentNodeV2(
                "body-1",
                "body-lineage",
                ContentNodeTypeV2.PARAGRAPH,
                ("flow-1",),
                0,
                parent_id="heading-1",
                text="Migration body",
                source_anchors=(body_anchor,),
            ),
        ),
        transformer_ref="migration-test-transformer",
        transformation_policy_ref="migration-test-policy",
        structured_processing_result_ref="migration-spr",
    )


def _build_source(path: Path) -> tuple[str, datetime, datetime]:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(255) NOT NULL PRIMARY KEY)")
        )
        connection.execute(
            text("INSERT INTO alembic_version(version_num) VALUES ('0005_structured_content_v2_selection')")
        )

    candidate_created_at = datetime(2026, 8, 15, 12, 0, 0)
    selection_selected_at = datetime(2026, 8, 15, 12, 5, 0)
    session = Session(engine)
    try:
        session.add(
            Document(
                id="migration-doc",
                title="Migration Test",
                file_type="txt",
                status="completed",
            )
        )
        session.flush()
        candidates = StructuredContentCandidateV2Repository()
        selections = StructuredContentV2SelectionRepository(candidates)
        candidates.create_candidate(session, _candidate())
        source_candidate_row = session.execute(
            select(CandidateRow).where(CandidateRow.candidate_id == "migration-candidate")
        ).scalar_one()
        source_candidate_row.created_at = candidate_created_at
        selections.set_selection(
            session,
            document_ref="migration-doc",
            candidate_id="migration-candidate",
            expected_version=0,
            selection_actor_ref="migration-source",
            reason="preserve source selection metadata",
        )
        source_selection = session.get(SelectionRow, "migration-doc")
        assert source_selection is not None
        source_selection.selection_version = 3
        source_selection.selected_at = selection_selected_at
        source_internal_id = source_selection.candidate_record_id
        session.commit()
        return source_internal_id, candidate_created_at, selection_selected_at
    finally:
        session.close()
        engine.dispose()


def test_replay_regenerates_v2_internal_ids_and_preserves_reader_content(tmp_path: Path) -> None:
    source_path = tmp_path / "source.db"
    source_internal_id, candidate_created_at, selection_selected_at = _build_source(source_path)
    target_url = os.environ["DATABASE_URL"]

    report = migrate_sqlite_to_postgresql(
        source_sqlite_path=source_path,
        target_database_url=target_url,
    )

    assert report.source_alembic_head == "0005_structured_content_v2_selection"
    assert report.target_alembic_head == "0005_structured_content_v2_selection"
    assert report.migrated_candidate_count == 1
    assert report.migrated_selection_count == 1
    assert report.reader_ready_count == 1
    assert report.reader_not_ready_count == 0
    assert report.source_row_counts == report.target_row_counts

    engine = create_engine(normalize_database_url(target_url))
    session = Session(engine)
    try:
        target_candidate_row = session.execute(
            select(CandidateRow).where(CandidateRow.candidate_id == "migration-candidate")
        ).scalar_one()
        target_selection = session.get(SelectionRow, "migration-doc")
        assert target_selection is not None
        assert target_candidate_row.id != source_internal_id
        assert target_selection.candidate_record_id == target_candidate_row.id
        assert target_selection.candidate_record_id != source_internal_id
        assert target_selection.selection_version == 3
        assert target_selection.selection_actor_ref == "migration-source"
        assert target_selection.reason == "preserve source selection metadata"
        assert target_selection.selected_at == selection_selected_at
        assert target_candidate_row.created_at == candidate_created_at

        repo = StructuredContentCandidateV2Repository()
        selected_repo = StructuredContentV2SelectionRepository(repo)
        assert normalize_candidate_v2(
            selected_repo.get_selected_candidate(session, "migration-doc")
        ) == normalize_candidate_v2(_candidate())
    finally:
        session.close()
        engine.dispose()
