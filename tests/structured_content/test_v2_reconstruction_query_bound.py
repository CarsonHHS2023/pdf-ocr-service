from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Document
import app.models_v2  # noqa: F401
import app.models_v2_selection  # noqa: F401
from app.source_units import SourceUnit, SourceUnitDimensions, SourceUnitKind
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


def _large_candidate(node_count: int = 201) -> StructuredContentCandidateV2:
    page = SourceUnit(
        "page-1",
        SourceUnitKind.PHYSICAL_PAGE,
        0,
        "source-pdf",
        dimensions=SourceUnitDimensions(1000, 1400),
    )
    root = ContentNodeV2(
        "node-root",
        "lineage-root",
        ContentNodeTypeV2.HEADING,
        ("page-1",),
        0,
        text="Chapter",
        heading_level=1,
    )
    children = tuple(
        ContentNodeV2(
            f"node-{index}",
            f"lineage-{index}",
            ContentNodeTypeV2.PARAGRAPH,
            ("page-1",),
            index,
            parent_id="node-root",
            text=f"Paragraph {index}",
        )
        for index in range(node_count - 1)
    )
    summary = ContentRecoverySummaryV2(
        ContentRecoveryStateV2.COMPLETE,
        1,
        complete_source_units=1,
    )
    return StructuredContentCandidateV2(
        document_ref="doc-query-bound",
        candidate_id="candidate-query-bound",
        lineage_key="lineage-query-bound",
        recovery_summary=summary,
        source_units=(StructuredSourceUnit(page),),
        nodes=(root, *children),
        evidence=(),
        assets=(),
        warnings=(),
        renditions=(),
    )


def test_candidate_reconstruction_query_count_is_bounded_by_association_types() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        session.add(
            Document(
                id="doc-query-bound",
                title="Query bound",
                file_type="pdf",
                status="processing",
            )
        )
        session.flush()
        repo = StructuredContentCandidateV2Repository()
        original = _large_candidate()
        repo.create_candidate(session, original)
        session.commit()
        session.expire_all()

        selects: list[str] = []

        def count_selects(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(statement)

        event.listen(engine, "before_cursor_execute", count_selects)
        try:
            reconstructed = repo.get_candidate(session, original.candidate_id)
        finally:
            event.remove(engine, "before_cursor_execute", count_selects)

        assert normalize_candidate_v2(reconstructed) == normalize_candidate_v2(original)
        assert len(reconstructed.nodes) == 201
        # Candidate/base rows + anchors + one query per association type. This
        # bound must stay independent of node count; the old per-node lookup path
        # executed more than 800 SELECTs for this fixture.
        assert len(selects) <= 20, len(selects)
    finally:
        session.close()
        engine.dispose()
