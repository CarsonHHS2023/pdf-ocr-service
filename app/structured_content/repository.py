from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.models import Document, ProcessingRun, SourceFile, StructuredContentCandidate as CandidateRow
from .errors import *
from .identity import ContentCandidateId, DocumentRef
from .model import StructuredContentCandidate
from .persistence_mapping import insert_graph, reconstruct, sval
from .rendition_persistence import persist_rendition_metadata, reconstruct_rendition_registry
from .serialization import serialize_structured_content_candidate
from .validation import validate_content_candidate

@dataclass(frozen=True, slots=True)
class StructuredContentCandidateSummary:
    candidate_id: str
    document_ref: str
    lineage_key: str
    schema_id: str
    schema_version: int
    recovery_state: str
    total_page_count: int
    complete_page_count: int
    degraded_page_count: int
    no_usable_page_count: int
    unavailable_page_count: int
    created_at: datetime
    source_file_ref: str | None = None
    processing_run_ref: str | None = None
    raw_result_ref: str | None = None
    structured_processing_result_ref: str | None = None

class StructuredContentCandidateRepository:
    """Repository for immutable Structured Content candidates.

    The caller owns the outer transaction. Methods flush but never commit. On
    persistence failure callers should rollback their transaction/session.
    """
    def create_candidate(self, session, candidate: StructuredContentCandidate) -> StructuredContentCandidate:
        result = validate_content_candidate(candidate)
        if not result.is_valid:
            raise InvalidStructuredContentCandidate([f"{i.code}:{i.safe_summary}" for i in result.issues])
        if session.get(Document, sval(candidate.document_ref)) is None:
            raise CandidateDocumentNotFound(f"document not found: {sval(candidate.document_ref)}")
        self._validate_processing_run(session, candidate)
        existing = self._row(session, sval(candidate.candidate_id))
        if existing is not None:
            persisted = self.get_candidate(session, candidate.candidate_id)
            if serialize_structured_content_candidate(persisted) == serialize_structured_content_candidate(candidate):
                return persisted
            raise StructuredContentCandidateConflict(f"candidate_id already exists: {sval(candidate.candidate_id)}")
        try:
            with session.begin_nested():
                insert_graph(session, candidate)
                persist_rendition_metadata(session, candidate)
        except IntegrityError as exc:
            session.rollback()
            try:
                persisted = self.get_candidate(session, candidate.candidate_id)
            except StructuredContentCandidateNotFound:
                raise CandidatePersistenceError("failed to persist candidate graph") from exc
            if serialize_structured_content_candidate(persisted) == serialize_structured_content_candidate(candidate):
                return persisted
            raise StructuredContentCandidateConflict(f"candidate_id already exists: {sval(candidate.candidate_id)}") from exc
        except CandidatePersistenceError:
            raise
        except SQLAlchemyError as exc:
            raise CandidatePersistenceError("failed to persist candidate graph") from exc
        return self.get_candidate(session, candidate.candidate_id)

    def get_candidate(self, session, candidate_id: ContentCandidateId | str) -> StructuredContentCandidate:
        cid=sval(candidate_id)
        try:
            candidate = reconstruct(session, cid)
            candidate = reconstruct_rendition_registry(session, candidate)
        except KeyError:
            raise StructuredContentCandidateNotFound(f"candidate not found: {cid}")
        result=validate_content_candidate(candidate)
        if not result.is_valid:
            raise PersistedCandidateCorrupt([f"{i.code}:{i.safe_summary}" for i in result.issues])
        return candidate

    def candidate_exists(self, session, candidate_id: ContentCandidateId | str) -> bool:
        return self._row(session, sval(candidate_id)) is not None

    def candidate_belongs_to_document(self, session, candidate_id: ContentCandidateId | str, document_ref: DocumentRef | str) -> bool:
        row=self._row(session, sval(candidate_id))
        return bool(row and row.document_id == sval(document_ref))

    def list_candidates_for_document(self, session, document_ref: DocumentRef | str) -> tuple[StructuredContentCandidateSummary, ...]:
        rows=session.execute(select(CandidateRow).where(CandidateRow.document_id==sval(document_ref)).order_by(CandidateRow.created_at, CandidateRow.candidate_id)).scalars().all()
        return tuple(StructuredContentCandidateSummary(r.candidate_id,r.document_id,r.lineage_key,r.schema_id,r.schema_version,r.recovery_state,r.total_page_count,r.complete_page_count,r.degraded_page_count,r.no_usable_page_count,r.unavailable_page_count,r.created_at,r.source_file_ref,r.processing_run_ref,r.raw_result_ref,r.structured_processing_result_ref) for r in rows)

    def _validate_processing_run(self, session, candidate: StructuredContentCandidate) -> None:
        run_ref = sval(candidate.processing_run_ref)
        if run_ref is None:
            return
        run = session.execute(select(ProcessingRun).where(ProcessingRun.processing_run_id == run_ref)).scalar_one_or_none()
        if run is None:
            raise CandidateProcessingRunMismatch(f"processing run not found: {run_ref}")
        if run.document_id != sval(candidate.document_ref):
            raise CandidateProcessingRunMismatch("processing run belongs to a different document")
        evidence_sources = {sval(e.source_file_ref) for e in candidate.evidence if sval(e.source_file_ref) is not None}
        if run.source_file_id is not None and evidence_sources and run.source_file_id not in evidence_sources:
            raise CandidateProcessingRunMismatch("candidate source evidence does not match processing run source file")

    def _row(self, session, cid: str):
        return session.execute(select(CandidateRow).where(CandidateRow.candidate_id==cid)).scalar_one_or_none()

_repository=StructuredContentCandidateRepository()
create_candidate=_repository.create_candidate
get_candidate=_repository.get_candidate
candidate_exists=_repository.candidate_exists
candidate_belongs_to_document=_repository.candidate_belongs_to_document
list_candidates_for_document=_repository.list_candidates_for_document
