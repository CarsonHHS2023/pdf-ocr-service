from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.models import Document, StructuredContentCandidate as CandidateRow, StructuredContentSelection as SelectionRow
from .errors import (
    CandidateNotSelectable,
    CandidateSelectionCandidateNotFound,
    CandidateSelectionConflict,
    CandidateSelectionCorrupt,
    CandidateSelectionDocumentMismatch,
    CandidateSelectionDocumentNotFound,
    CandidateSelectionPersistenceError,
    PersistedCandidateCorrupt,
    StructuredContentCandidateNotFound,
)
from .identity import ContentCandidateId, DocumentRef
from .persistence_mapping import sval
from .repository import StructuredContentCandidateRepository
from .selection_types import StructuredContentSelectionState
from .validation import validate_content_candidate


class StructuredContentSelectionRepository:
    """Repository for explicit zero-or-one Structured Content selections.

    The caller owns the outer transaction. Methods flush but never commit.
    """

    def __init__(self, candidate_repository: StructuredContentCandidateRepository | None = None):
        self._candidates = candidate_repository or StructuredContentCandidateRepository()

    def get_selection(self, session, document_ref: DocumentRef | str) -> StructuredContentSelectionState | None:
        document_id = sval(document_ref)
        row = session.execute(select(SelectionRow).where(SelectionRow.document_id == document_id)).scalar_one_or_none()
        if row is None:
            return None
        candidate = session.get(CandidateRow, row.candidate_id)
        if candidate is None or candidate.document_id != document_id:
            raise CandidateSelectionCorrupt(f"selection for document {document_id} references an invalid candidate")
        return _state(row, candidate)

    def get_selected_candidate(self, session, document_ref: DocumentRef | str):
        state = self.get_selection(session, document_ref)
        if state is None:
            return None
        try:
            candidate = self._candidates.get_candidate(session, state.candidate_id)
        except StructuredContentCandidateNotFound as exc:
            raise CandidateSelectionCorrupt(f"selection for document {state.document_ref} references missing candidate") from exc
        except PersistedCandidateCorrupt as exc:
            raise CandidateSelectionCorrupt(f"selection for document {state.document_ref} references corrupt candidate") from exc
        if sval(candidate.document_ref) != state.document_ref:
            raise CandidateSelectionCorrupt(f"selection for document {state.document_ref} references another document")
        return candidate

    def set_selection(
        self,
        session,
        *,
        document_ref: DocumentRef | str,
        candidate_id: ContentCandidateId | str,
        expected_version: int,
        selected_by: str | None = None,
        reason: str | None = None,
    ) -> StructuredContentSelectionState:
        document_id = sval(document_ref)
        public_candidate_id = sval(candidate_id)
        if expected_version is None or expected_version < 0:
            raise CandidateSelectionConflict(document_ref=document_id, expected_version=-1 if expected_version is None else expected_version, actual_version=self._actual_version(session, document_id))
        if session.get(Document, document_id) is None:
            raise CandidateSelectionDocumentNotFound(f"document not found: {document_id}")
        candidate_row = session.execute(select(CandidateRow).where(CandidateRow.candidate_id == public_candidate_id)).scalar_one_or_none()
        if candidate_row is None:
            raise CandidateSelectionCandidateNotFound(f"candidate not found: {public_candidate_id}")
        if candidate_row.document_id != document_id:
            raise CandidateSelectionDocumentMismatch(f"candidate {public_candidate_id} does not belong to document {document_id}")
        self._ensure_selectable(session, public_candidate_id, document_id)
        current = self.get_selection(session, document_id)
        if current is None:
            if expected_version != 0:
                raise CandidateSelectionConflict(document_ref=document_id, expected_version=expected_version, actual_version=None)
            return self._insert_first(session, document_id, candidate_row, selected_by, reason)
        if current.selection_version != expected_version:
            raise CandidateSelectionConflict(document_ref=document_id, expected_version=expected_version, actual_version=current.selection_version)
        if current.candidate_id == public_candidate_id:
            return current
        return self._replace_existing(session, document_id, candidate_row, expected_version, selected_by, reason)

    def rollback_selection(self, session, **kwargs) -> StructuredContentSelectionState:
        return self.set_selection(session, **kwargs)

    def _ensure_selectable(self, session, candidate_id: str, document_id: str) -> None:
        try:
            candidate = self._candidates.get_candidate(session, candidate_id)
        except StructuredContentCandidateNotFound as exc:
            raise CandidateSelectionCandidateNotFound(f"candidate not found: {candidate_id}") from exc
        except PersistedCandidateCorrupt as exc:
            raise CandidateNotSelectable(f"candidate not selectable: {candidate_id}") from exc
        if sval(candidate.document_ref) != document_id:
            raise CandidateSelectionDocumentMismatch(f"candidate {candidate_id} does not belong to document {document_id}")
        result = validate_content_candidate(candidate)
        if not result.is_valid:
            raise CandidateNotSelectable(f"candidate not selectable: {candidate_id}")

    def _insert_first(self, session, document_id: str, candidate_row: CandidateRow, selected_by: str | None, reason: str | None) -> StructuredContentSelectionState:
        row = SelectionRow(document_id=document_id, candidate_id=candidate_row.id, selection_version=1, selected_at=datetime.utcnow(), selection_actor_ref=selected_by, reason=reason)
        try:
            with session.begin_nested():
                session.add(row)
                session.flush()
        except IntegrityError as exc:
            raise CandidateSelectionConflict(document_ref=document_id, expected_version=0, actual_version=self._actual_version(session, document_id)) from exc
        except SQLAlchemyError as exc:
            raise CandidateSelectionPersistenceError("failed to persist structured content selection") from exc
        return self.get_selection(session, document_id)  # type: ignore[return-value]

    def _replace_existing(self, session, document_id: str, candidate_row: CandidateRow, expected_version: int, selected_by: str | None, reason: str | None) -> StructuredContentSelectionState:
        stmt = update(SelectionRow).where(SelectionRow.document_id == document_id, SelectionRow.selection_version == expected_version).values(candidate_id=candidate_row.id, selection_version=expected_version + 1, selected_at=datetime.utcnow(), selection_actor_ref=selected_by, reason=reason)
        try:
            result = session.execute(stmt)
            if result.rowcount != 1:
                raise CandidateSelectionConflict(document_ref=document_id, expected_version=expected_version, actual_version=self._actual_version(session, document_id))
            session.flush()
        except CandidateSelectionConflict:
            raise
        except IntegrityError as exc:
            raise CandidateSelectionPersistenceError("failed to persist structured content selection") from exc
        except SQLAlchemyError as exc:
            raise CandidateSelectionPersistenceError("failed to persist structured content selection") from exc
        return self.get_selection(session, document_id)  # type: ignore[return-value]

    def _actual_version(self, session, document_id: str) -> int | None:
        return session.execute(select(SelectionRow.selection_version).where(SelectionRow.document_id == document_id)).scalar_one_or_none()


def _state(row: SelectionRow, candidate: CandidateRow) -> StructuredContentSelectionState:
    return StructuredContentSelectionState(candidate.document_id, candidate.candidate_id, row.selection_version, row.selected_at, row.selection_actor_ref, row.reason)


_repository = StructuredContentSelectionRepository()
get_selection = _repository.get_selection
get_selected_candidate = _repository.get_selected_candidate
set_selection = _repository.set_selection
rollback_selection = _repository.rollback_selection
