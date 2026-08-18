from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.models import Document, ProcessingRun
from app.models_v2 import StructuredContentCandidateV2Record as CandidateRow
from app.structured_content_v2.model import StructuredContentCandidateV2, normalize_candidate_v2
from app.structured_content_v2.persistence import insert_candidate_v2, reconstruct_candidate_v2
from app.structured_content_v2.validation import validate_candidate_v2


class StructuredContentV2RepositoryError(RuntimeError):
    pass


class StructuredContentV2CandidateNotFound(StructuredContentV2RepositoryError):
    pass


class StructuredContentV2CandidateConflict(StructuredContentV2RepositoryError):
    pass


class StructuredContentV2CandidateDocumentNotFound(StructuredContentV2RepositoryError):
    pass


class StructuredContentV2ProcessingRunMismatch(StructuredContentV2RepositoryError):
    pass


class StructuredContentV2PersistenceError(StructuredContentV2RepositoryError):
    pass


@dataclass(frozen=True, slots=True)
class StructuredContentCandidateV2Summary:
    candidate_id: str
    document_ref: str
    lineage_key: str
    recovery_state: str
    total_source_unit_count: int
    created_at: datetime
    processing_run_ref: str | None = None
    raw_result_ref: str | None = None
    structured_processing_result_ref: str | None = None


class StructuredContentCandidateV2Repository:
    """Immutable Structured Content v2 repository; caller owns the transaction."""

    def create_candidate(self, session, candidate: StructuredContentCandidateV2) -> StructuredContentCandidateV2:
        validate_candidate_v2(candidate)
        if session.get(Document, candidate.document_ref) is None:
            raise StructuredContentV2CandidateDocumentNotFound(f"document not found: {candidate.document_ref}")
        self._validate_processing_run(session, candidate)

        existing = self._row(session, candidate.candidate_id)
        if existing is not None:
            persisted = self.get_candidate(session, candidate.candidate_id)
            if normalize_candidate_v2(persisted) == normalize_candidate_v2(candidate):
                return persisted
            raise StructuredContentV2CandidateConflict(f"candidate_id already exists: {candidate.candidate_id}")

        try:
            with session.begin_nested():
                insert_candidate_v2(session, candidate)
        except IntegrityError as exc:
            try:
                persisted = self.get_candidate(session, candidate.candidate_id)
            except StructuredContentV2CandidateNotFound:
                raise StructuredContentV2PersistenceError("failed to persist Structured Content v2 candidate") from exc
            if normalize_candidate_v2(persisted) == normalize_candidate_v2(candidate):
                return persisted
            raise StructuredContentV2CandidateConflict(f"candidate_id already exists: {candidate.candidate_id}") from exc
        except SQLAlchemyError as exc:
            raise StructuredContentV2PersistenceError("failed to persist Structured Content v2 candidate") from exc

        return self.get_candidate(session, candidate.candidate_id)

    def get_candidate(self, session, candidate_id: str) -> StructuredContentCandidateV2:
        try:
            return reconstruct_candidate_v2(session, candidate_id)
        except KeyError as exc:
            raise StructuredContentV2CandidateNotFound(f"candidate not found: {candidate_id}") from exc
        except ValueError as exc:
            raise StructuredContentV2PersistenceError("persisted Structured Content v2 candidate is invalid") from exc

    def candidate_exists(self, session, candidate_id: str) -> bool:
        return self._row(session, candidate_id) is not None

    def candidate_belongs_to_document(self, session, candidate_id: str, document_ref: str) -> bool:
        row = self._row(session, candidate_id)
        return bool(row and row.document_id == document_ref)

    def list_candidates_for_document(self, session, document_ref: str) -> tuple[StructuredContentCandidateV2Summary, ...]:
        rows = session.execute(
            select(CandidateRow)
            .where(CandidateRow.document_id == document_ref)
            .order_by(CandidateRow.created_at, CandidateRow.candidate_id)
        ).scalars().all()
        return tuple(
            StructuredContentCandidateV2Summary(
                candidate_id=row.candidate_id,
                document_ref=row.document_id,
                lineage_key=row.lineage_key,
                recovery_state=row.recovery_state,
                total_source_unit_count=row.total_source_unit_count,
                created_at=row.created_at,
                processing_run_ref=row.processing_run_ref,
                raw_result_ref=row.raw_result_ref,
                structured_processing_result_ref=row.structured_processing_result_ref,
            )
            for row in rows
        )

    def _validate_processing_run(self, session, candidate: StructuredContentCandidateV2) -> None:
        if candidate.processing_run_ref is None:
            return
        run = next(
            (
                item
                for item in session.new
                if isinstance(item, ProcessingRun)
                and item.processing_run_id == candidate.processing_run_ref
            ),
            None,
        )
        if run is None:
            run = session.execute(
                select(ProcessingRun).where(ProcessingRun.processing_run_id == candidate.processing_run_ref)
            ).scalar_one_or_none()
        if run is None:
            raise StructuredContentV2ProcessingRunMismatch(
                f"processing run not found: {candidate.processing_run_ref}"
            )
        if run.document_id != candidate.document_ref:
            raise StructuredContentV2ProcessingRunMismatch("processing run belongs to a different document")

    @staticmethod
    def _row(session, candidate_id: str):
        return session.execute(
            select(CandidateRow).where(CandidateRow.candidate_id == candidate_id)
        ).scalar_one_or_none()


repository_v2 = StructuredContentCandidateV2Repository()
