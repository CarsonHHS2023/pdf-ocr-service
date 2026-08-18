from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Document
from app.models_v2 import (
    StructuredContentAnchorV2Record,
    StructuredContentCandidateV2Record,
    StructuredContentNodeSourceUnitV2Record,
    StructuredContentNodeV2Record,
    StructuredContentSourceUnitV2Record,
)


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def _candidate(session) -> StructuredContentCandidateV2Record:
    session.add(Document(id="doc-v2", title="V2", file_type="txt", status="processing"))
    row = StructuredContentCandidateV2Record(
        id="candidate-row",
        candidate_id="candidate-v2",
        document_id="doc-v2",
        lineage_key="lineage-v2",
        schema_id="atlas.structured-content-candidate",
        schema_version=2,
        recovery_state="complete",
        total_source_unit_count=4,
        complete_source_unit_count=4,
        degraded_source_unit_count=0,
        no_usable_source_unit_count=0,
        unavailable_source_unit_count=0,
    )
    session.add(row)
    session.flush()
    return row


def test_v2_schema_has_source_units_and_no_page_requirement() -> None:
    engine, session = _session()
    try:
        _candidate(session)
        units = [
            StructuredContentSourceUnitV2Record(
                id="pdf-page",
                candidate_id="candidate-row",
                source_unit_id="page-1",
                kind="physical_page",
                source_order=0,
                source_ref="source-pdf",
                recovery_state="complete",
                width=1000,
                height=1400,
                dimension_unit="pixel",
                rotation_degrees=0,
            ),
            StructuredContentSourceUnitV2Record(
                id="txt-flow",
                candidate_id="candidate-row",
                source_unit_id="flow-1",
                kind="text_flow",
                source_order=1,
                source_ref="source-txt",
                recovery_state="complete",
                source_span_start=0,
                source_span_end=5000,
            ),
            StructuredContentSourceUnitV2Record(
                id="html-section",
                candidate_id="candidate-row",
                source_unit_id="html-1",
                kind="html_section",
                source_order=2,
                source_ref="source-html",
                recovery_state="complete",
            ),
            StructuredContentSourceUnitV2Record(
                id="audio-segment",
                candidate_id="candidate-row",
                source_unit_id="audio-1",
                kind="audio_segment",
                source_order=3,
                source_ref="source-audio",
                recovery_state="complete",
                duration_ms=12000,
            ),
        ]
        session.add_all(units)
        session.flush()

        node = StructuredContentNodeV2Record(
            id="node-row",
            candidate_id="candidate-row",
            node_id="node-1",
            lineage_key="node-lineage-1",
            node_type="paragraph",
            sibling_order=0,
            recovery_state="complete",
            text="text",
        )
        session.add(node)
        session.flush()
        session.add_all(
            [
                StructuredContentNodeSourceUnitV2Record(
                    id="node-unit-1", node_record_id="node-row", source_unit_record_id="txt-flow", association_order=0
                ),
                StructuredContentNodeSourceUnitV2Record(
                    id="node-unit-2", node_record_id="node-row", source_unit_record_id="html-section", association_order=1
                ),
            ]
        )
        session.flush()

        # StaticPool-backed in-memory SQLite uses one DBAPI connection. Introspecting
        # through inspect(engine) opens a separate Connection wrapper around that same
        # DBAPI connection; when the wrapper closes it can roll back this session's
        # uncommitted fixture rows. Inspect through the active Session connection so
        # schema introspection stays inside the same transaction.
        node_columns = {
            column["name"]
            for column in inspect(session.connection()).get_columns("structured_content_v2_nodes")
        }
        assert "page_id" not in node_columns
        assert "source_page_index" not in node_columns
        assert session.query(StructuredContentNodeSourceUnitV2Record).count() == 2
    finally:
        session.close()
        engine.dispose()


def test_typed_anchor_rows_cover_spatial_text_dom_and_temporal_without_fake_pages() -> None:
    engine, session = _session()
    try:
        _candidate(session)
        session.add_all(
            [
                StructuredContentSourceUnitV2Record(id="u1", candidate_id="candidate-row", source_unit_id="page", kind="physical_page", source_order=0, source_ref="pdf", recovery_state="complete", width=100, height=200),
                StructuredContentSourceUnitV2Record(id="u2", candidate_id="candidate-row", source_unit_id="flow", kind="text_flow", source_order=1, source_ref="txt", recovery_state="complete", source_span_start=0, source_span_end=100),
                StructuredContentSourceUnitV2Record(id="u3", candidate_id="candidate-row", source_unit_id="html", kind="html_section", source_order=2, source_ref="html", recovery_state="complete"),
                StructuredContentSourceUnitV2Record(id="u4", candidate_id="candidate-row", source_unit_id="audio", kind="audio_segment", source_order=3, source_ref="audio", recovery_state="complete", duration_ms=10000),
            ]
        )
        session.add(StructuredContentNodeV2Record(id="n1", candidate_id="candidate-row", node_id="n1", lineage_key="l1", node_type="paragraph", sibling_order=0, recovery_state="complete"))
        session.flush()
        session.add_all(
            [
                StructuredContentAnchorV2Record(id="a1", candidate_id="candidate-row", source_unit_record_id="u1", owner_type="node", owner_record_id="n1", anchor_order=0, anchor_kind="spatial", bbox_left=0.1, bbox_top=0.1, bbox_right=0.9, bbox_bottom=0.2),
                StructuredContentAnchorV2Record(id="a2", candidate_id="candidate-row", source_unit_record_id="u2", owner_type="node", owner_record_id="n1", anchor_order=1, anchor_kind="text_span", text_start=10, text_end=20),
                StructuredContentAnchorV2Record(id="a3", candidate_id="candidate-row", source_unit_record_id="u3", owner_type="node", owner_record_id="n1", anchor_order=2, anchor_kind="dom", dom_path="body/main/p[1]", dom_text_start=0, dom_text_end=5),
                StructuredContentAnchorV2Record(id="a4", candidate_id="candidate-row", source_unit_record_id="u4", owner_type="node", owner_record_id="n1", anchor_order=3, anchor_kind="temporal", start_ms=100, end_ms=900),
            ]
        )
        session.flush()
        assert session.query(StructuredContentAnchorV2Record).count() == 4
    finally:
        session.close()
        engine.dispose()


def test_typed_anchor_constraint_rejects_mixed_coordinate_systems() -> None:
    engine, session = _session()
    try:
        _candidate(session)
        session.add(StructuredContentSourceUnitV2Record(id="u1", candidate_id="candidate-row", source_unit_id="flow", kind="text_flow", source_order=0, source_ref="txt", recovery_state="complete", source_span_start=0, source_span_end=100))
        session.flush()
        session.add(
            StructuredContentAnchorV2Record(
                id="bad-anchor",
                candidate_id="candidate-row",
                source_unit_record_id="u1",
                owner_type="node",
                owner_record_id="n1",
                anchor_order=0,
                anchor_kind="text_span",
                text_start=1,
                text_end=2,
                bbox_left=0.1,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
    finally:
        session.rollback()
        session.close()
        engine.dispose()


def test_v2_table_registry_contains_no_v2_page_table() -> None:
    v2_tables = {name for name in Base.metadata.tables if name.startswith("structured_content_v2_")}
    assert "structured_content_v2_source_units" in v2_tables
    assert "structured_content_v2_nodes" in v2_tables
    assert "structured_content_v2_pages" not in v2_tables
