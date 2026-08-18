from __future__ import annotations

from dataclasses import replace
from contextlib import contextmanager
from pathlib import Path
import tempfile

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Document, SourceFile
from app.structured_content.identity import ContentCandidateId, ContentLineageKey, DocumentRef, ProcessingRunRef
from tests.structured_content.candidate_factory import make_linear_candidate


def sqlite_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def fk(conn, rec):
        conn.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    return session, engine


def add_document(session, document_id: str, *, source_file_id: str | None = None):
    session.add(Document(id=document_id, title=document_id, file_type="pdf"))
    session.flush()
    if source_file_id is not None:
        session.add(SourceFile(id=source_file_id, document_id=document_id, original_filename=f"{source_file_id}.pdf", file_type="pdf"))
        session.flush()


def with_identity(candidate, *, doc: str | None = None, candidate_id: str, run: str | None = None):
    return replace(
        candidate,
        document_ref=DocumentRef(doc or candidate.document_ref.value),
        candidate_id=ContentCandidateId(candidate_id),
        lineage_key=ContentLineageKey(f"lineage-{candidate_id}"),
        processing_run_ref=ProcessingRunRef(run) if run else None,
    )


def candidate_for(doc: str, candidate_id: str, *, pages: int = 1, nodes: int = 1, run: str | None = None):
    return with_identity(make_linear_candidate(pages, nodes), doc=doc, candidate_id=candidate_id, run=run)


def table_names(engine):
    return set(inspect(engine).get_table_names())


@contextmanager
def temp_sqlite_url():
    with tempfile.TemporaryDirectory() as d:
        yield "sqlite:///" + str(Path(d) / "migrations.db")
