from __future__ import annotations

import hashlib

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
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
from app.storage.local import LocalStorageProvider
from app.storage.models import StorageReference


class _TrackingSession(Session):
    created: list["_TrackingSession"] = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.was_closed = False
        type(self).created.append(self)

    def close(self) -> None:
        self.was_closed = True
        super().close()


class _BoundaryCheckingAnalyzer:
    def __init__(self, sessions: list[_TrackingSession]) -> None:
        self.sessions = sessions
        self.calls = 0

    def analyze(self, window):
        self.calls += 1
        # The only database session created by canonicalization before provider
        # work is the retained-source read session, and it must already be closed.
        assert len(self.sessions) == 1
        assert self.sessions[0].was_closed is True
        assert self.sessions[0].in_transaction() is False

        assignments = []
        for line in window.lines:
            if line.is_empty:
                continue
            if line.line_id == "L000001":
                assignments.append(
                    TxtLineStructureAssignment(
                        line.line_id,
                        TxtStructureKind.TITLE,
                        True,
                        None,
                    )
                )
            else:
                assignments.append(
                    TxtLineStructureAssignment(
                        line.line_id,
                        TxtStructureKind.PARAGRAPH,
                        True,
                        None,
                    )
                )
        return TxtStructureWindowResult(window.window_id, tuple(assignments))


def test_txt_analysis_closes_source_session_before_provider_and_uses_fresh_write_session(tmp_path) -> None:
    raw = "Book\nFirst paragraph.\nSecond paragraph.\n".encode("utf-8")
    checksum = hashlib.sha256(raw).hexdigest()

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=_TrackingSession)
    storage = LocalStorageProvider(tmp_path)
    source_ref = StorageReference.parse("src_" + "8" * 32)
    storage.put(raw, source_ref, expected_size=len(raw), expected_sha256=checksum)

    with factory.begin() as session:
        session.add(Document(id="doc-boundary", title="Boundary", file_type="txt", status="processing"))
        session.add(
            SourceFile(
                id="source-boundary",
                document_id="doc-boundary",
                original_filename="boundary.txt",
                file_type="txt",
                mime_type="text/plain",
                byte_size=len(raw),
                checksum_sha256=checksum,
                storage_reference=str(source_ref),
                retained=1,
                is_primary=1,
            )
        )

    _TrackingSession.created.clear()
    analyzer = _BoundaryCheckingAnalyzer(_TrackingSession.created)
    service = TxtCanonicalizationService(
        storage=storage,
        session_factory=factory,
        analyzer=analyzer,
    )

    try:
        outcome = service.canonicalize(
            RetainedTxtCanonicalizationRequest(
                document_ref="doc-boundary",
                source_file_ref="source-boundary",
                processing_run_ref="txt-boundary-run",
            )
        )
        assert outcome.candidate_id.startswith("scv2_txt_")
        assert analyzer.calls >= 1
        assert len(_TrackingSession.created) == 2
        assert _TrackingSession.created[0].was_closed is True
        assert _TrackingSession.created[1].was_closed is True
    finally:
        engine.dispose()
