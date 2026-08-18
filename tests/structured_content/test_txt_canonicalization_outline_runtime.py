from __future__ import annotations

import hashlib
import json

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
    TxtHeadingLevelAssignment,
    TxtLineStructureAssignment,
    TxtOutlineWindowResult,
    TxtStructureKind,
    TxtStructureWindowResult,
)
from app.storage.local import LocalStorageProvider
from app.storage.models import StorageReference


class _OutlineAwareAnalyzer:
    def __init__(self) -> None:
        self.local_calls = 0
        self.outline_calls = 0

    def analyze(self, window):
        self.local_calls += 1
        assignments = []
        for line in window.lines:
            if line.is_empty:
                continue
            if line.line_id == "L000001":
                kind, level = TxtStructureKind.TITLE, None
            elif line.line_id in {"L000002", "L000003"}:
                kind, level = TxtStructureKind.HEADING, 1
            else:
                kind, level = TxtStructureKind.PARAGRAPH, None
            assignments.append(TxtLineStructureAssignment(line.line_id, kind, True, level))
        return TxtStructureWindowResult(window.window_id, tuple(assignments))

    def reconcile_outline(self, window):
        self.outline_calls += 1
        levels = {
            "L000001": 1,
            "L000002": 1,
            "L000003": 2,
        }
        return TxtOutlineWindowResult(
            window.window_id,
            tuple(
                TxtHeadingLevelAssignment(candidate.line_id, levels[candidate.line_id])
                for candidate in window.candidates
            ),
        )


def test_canonicalization_runs_outline_reconciliation_before_shared_transformer(tmp_path) -> None:
    raw = "Book\nChapter 1\n1.1 Detail\nBody\n".encode("utf-8")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    storage = LocalStorageProvider(tmp_path)
    source_ref = StorageReference.parse("src_" + "4" * 32)
    checksum = hashlib.sha256(raw).hexdigest()
    storage.put(raw, source_ref, expected_size=len(raw), expected_sha256=checksum)

    with factory.begin() as session:
        session.add(Document(id="doc-outline-runtime", title="Outline", file_type="txt", status="processing"))
        session.add(
            SourceFile(
                id="source-outline-runtime",
                document_id="doc-outline-runtime",
                original_filename="outline.txt",
                file_type="txt",
                mime_type="text/plain",
                byte_size=len(raw),
                checksum_sha256=checksum,
                storage_reference=str(source_ref),
                retained=1,
                is_primary=1,
            )
        )

    analyzer = _OutlineAwareAnalyzer()
    service = TxtCanonicalizationService(
        storage=storage,
        session_factory=factory,
        analyzer=analyzer,
    )
    try:
        outcome = service.canonicalize(
            RetainedTxtCanonicalizationRequest(
                "doc-outline-runtime",
                "source-outline-runtime",
                "txt-outline-runtime-run",
            )
        )
        assert analyzer.local_calls >= 1
        assert analyzer.outline_calls == 1

        spr = json.loads(storage.get(outcome.structured_processing_result_ref).decode("utf-8"))
        by_text = {node["text"]: node for node in spr["nodes"]}
        assert by_text["Chapter 1"]["heading_level"] == 1
        assert by_text["1.1 Detail"]["heading_level"] == 2
        assert by_text["1.1 Detail"]["parent_id"] == by_text["Chapter 1"]["node_id"]
        assert by_text["Body"]["parent_id"] == by_text["1.1 Detail"]["node_id"]
        assert by_text["Body"]["text"] == "Body"
    finally:
        engine.dispose()
