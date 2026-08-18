from __future__ import annotations

import hashlib

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Document, SourceFile
import app.models_v2  # noqa: F401
import app.models_v2_selection  # noqa: F401
from app.processing.txt.canonicalization import (
    RetainedTxtCanonicalizationRequest,
    TxtCanonicalizationService,
)
from app.processing.txt.structure_recovery import (
    TxtLineStructureAssignment,
    TxtStructureKind,
    TxtStructureWindowResult,
)
from app.reader_v2.service import build_selected_reader_v2_document
from app.storage.local import LocalStorageProvider
from app.storage.models import StorageReference
from app.structured_content_v2.model import ContentNodeTypeV2
from app.structured_content_v2.repository import StructuredContentCandidateV2Repository


class _SemanticAnalyzer:
    def analyze(self, window):
        structure = {
            "L000001": (TxtStructureKind.TITLE, True, None),
            "L000002": (TxtStructureKind.TOC, True, None),
            "L000003": (TxtStructureKind.LIST, True, None),
            "L000004": (TxtStructureKind.LIST_ITEM, True, None),
            "L000005": (TxtStructureKind.HEADING, True, 1),
            "L000006": (TxtStructureKind.PARAGRAPH, True, None),
        }
        assignments = []
        for line in window.lines:
            if line.is_empty:
                continue
            kind, starts, level = structure[line.line_id]
            assignments.append(TxtLineStructureAssignment(line.line_id, kind, starts, level))
        return TxtStructureWindowResult(window.window_id, tuple(assignments))


def test_txt_semantic_markers_survive_spr_candidate_and_reader_projection(tmp_path) -> None:
    raw = (
        "Book Title\n"
        "Contents\n"
        "TOC Entries\n"
        "Chapter 1 .... 1\n"
        "1 Introduction\n"
        "Body text\n"
    ).encode("utf-8")
    checksum = hashlib.sha256(raw).hexdigest()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    storage = LocalStorageProvider(tmp_path)
    source_ref = StorageReference.parse("src_" + "5" * 32)
    storage.put(raw, source_ref, expected_size=len(raw), expected_sha256=checksum)

    with factory.begin() as session:
        session.add(Document(id="doc-semantics", title="Semantics", file_type="txt", status="processing"))
        session.add(
            SourceFile(
                id="source-semantics",
                document_id="doc-semantics",
                original_filename="semantics.txt",
                file_type="txt",
                mime_type="text/plain",
                byte_size=len(raw),
                checksum_sha256=checksum,
                storage_reference=str(source_ref),
                retained=1,
                is_primary=1,
            )
        )

    service = TxtCanonicalizationService(
        storage=storage,
        session_factory=factory,
        analyzer=_SemanticAnalyzer(),
    )
    try:
        outcome = service.canonicalize(
            RetainedTxtCanonicalizationRequest(
                "doc-semantics",
                "source-semantics",
                "txt-semantics-run",
            )
        )
        with factory() as session:
            candidate = StructuredContentCandidateV2Repository().get_candidate(session, outcome.candidate_id)
            candidate_by_text = {node.text: node for node in candidate.nodes}

            title = candidate_by_text["Book Title"]
            assert title.node_type is ContentNodeTypeV2.HEADING
            assert title.heading_level == 1
            assert title.metadata["spr_node_kind"] == "title"
            assert title.metadata["txt_structure_kind"] == "title"

            toc = candidate_by_text["Contents"]
            assert toc.node_type is ContentNodeTypeV2.REFERENCE
            assert toc.metadata["spr_node_kind"] == "reference"
            assert toc.metadata["txt_structure_kind"] == "toc"

            list_node = candidate_by_text["TOC Entries"]
            assert list_node.node_type is ContentNodeTypeV2.LIST
            assert list_node.metadata["txt_structure_kind"] == "list"

            toc_entry = candidate_by_text["Chapter 1 .... 1"]
            assert toc_entry.node_type is ContentNodeTypeV2.LIST_ITEM
            assert toc_entry.metadata["txt_structure_kind"] == "list_item"

            reader = build_selected_reader_v2_document(session=session, document_ref="doc-semantics")
            reader_by_text = {node.text: node for node in reader.nodes}
            assert reader_by_text["Book Title"].metadata["txt_structure_kind"] == "title"
            assert reader_by_text["Contents"].metadata["txt_structure_kind"] == "toc"
            assert reader_by_text["Chapter 1 .... 1"].metadata["txt_structure_kind"] == "list_item"
            assert all(unit.source_unit.kind.value == "text_flow" for unit in reader.source_units)
    finally:
        engine.dispose()
