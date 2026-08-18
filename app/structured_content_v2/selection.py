from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.models import Document
from app.models_v2 import StructuredContentCandidateV2Record as CandidateRow
from app.models_v2_selection import StructuredContentSelectionV2Record as SelectionRow
from app.structured_content_v2.model import StructuredContentCandidateV2
from app.structured_content_v2.repository import (
    StructuredContentCandidateV2Repository,
    StructuredContentV2CandidateDocumentNotFound,
    StructuredContentV2CandidateNotFound,
    StructuredContentV2PersistenceError,
)


class StructuredContentV2SelectionError(RuntimeError):
    pass


class StructuredContentV2SelectionNotFound(StructuredContentV2SelectionError):
    pass


class StructuredContentV2SelectionVersionConflict(StructuredContentV2SelectionError):
    pass


class StructuredContentV2SelectionCandidateMismatch(StructuredContentV2SelectionError):
    pass


class StructuredContentV2SelectionCandidateInvalid(StructuredContentV2SelectionError):
    pass


@dataclass(frozen=True, slots=True)
class StructuredContentV2Selection:
    document_ref: str
    candidate_id: str
    selection_version: int
    selected_at: datetime
    selection_actor_ref: str | None = None
    reason: str | None = None


class StructuredContentV2SelectionRepository:
    def __init__(self, candidates: StructuredContentCandidateV2Repository | None = None) -> None:
        self._candidates = candidates or StructuredContentCandidateV2Repository()

    def get_selection(self, session, document_ref: str) -> StructuredContentV2Selection:
        row = session.get(SelectionRow, document_ref)
        if row is None:
            raise StructuredContentV2SelectionNotFound(f"no Structured Content v2 selection for document: {document_ref}")
        candidate = session.get(CandidateRow, row.candidate_record_id)
        if candidate is None or candidate.document_id != document_ref:
            raise StructuredContentV2SelectionCandidateMismatch("persisted v2 selection references an invalid candidate")
        return StructuredContentV2Selection(
            document_ref=document_ref,
            candidate_id=candidate.candidate_id,
            selection_version=row.selection_version,
            selected_at=row.selected_at,
            selection_actor_ref=row.selection_actor_ref,
            reason=row.reason,
        )

    def set_selection(
        self,
        session,
        *,
        document_ref: str,
        candidate_id: str,
        expected_version: int,
        selection_actor_ref: str | None = None,
        reason: str | None = None,
    ) -> StructuredContentV2Selection:
        if not isinstance(expected_version, int) or isinstance(expected_version, bool) or expected_version < 0:
            raise ValueError("expected_version must be a nonnegative integer")
        if session.get(Document, document_ref) is None:
            raise StructuredContentV2CandidateDocumentNotFound(f"document not found: {document_ref}")
        candidate = session.execute(
            select(CandidateRow).where(CandidateRow.candidate_id == candidate_id)
        ).scalar_one_or_none()
        if candidate is None:
            raise StructuredContentV2CandidateNotFound(f"candidate not found: {candidate_id}")
        if candidate.document_id != document_ref:
            raise StructuredContentV2SelectionCandidateMismatch("candidate belongs to a different document")

        # Selection makes a candidate authoritative. Validate the full persisted graph
        # before mutating selection state so a corrupt/incomplete candidate cannot be
        # selected merely because its header row exists.
        try:
            self._candidates.get_candidate(session, candidate_id)
        except StructuredContentV2PersistenceError as exc:
            raise StructuredContentV2SelectionCandidateInvalid(
                f"candidate cannot be selected because its persisted graph is invalid: {candidate_id}"
            ) from exc

        row = session.get(SelectionRow, document_ref)
        now = datetime.utcnow()
        if row is None:
            if expected_version != 0:
                raise StructuredContentV2SelectionVersionConflict(
                    f"expected selection version {expected_version}, actual version 0"
                )
            try:
                with session.begin_nested():
                    session.add(
                        SelectionRow(
                            document_id=document_ref,
                            candidate_record_id=candidate.id,
                            selection_version=1,
                            selected_at=now,
                            selection_actor_ref=selection_actor_ref,
                            reason=reason,
                        )
                    )
                    session.flush()
            except IntegrityError as exc:
                raise StructuredContentV2SelectionVersionConflict(
                    "selection was created concurrently; retry with the current version"
                ) from exc
        else:
            result = session.execute(
                update(SelectionRow)
                .where(
                    SelectionRow.document_id == document_ref,
                    SelectionRow.selection_version == expected_version,
                )
                .values(
                    candidate_record_id=candidate.id,
                    selection_version=expected_version + 1,
                    selected_at=now,
                    selection_actor_ref=selection_actor_ref,
                    reason=reason,
                )
            )
            if result.rowcount != 1:
                actual = session.execute(
                    select(SelectionRow.selection_version).where(SelectionRow.document_id == document_ref)
                ).scalar_one_or_none()
                raise StructuredContentV2SelectionVersionConflict(
                    f"expected selection version {expected_version}, actual version {actual if actual is not None else 0}"
                )
            session.expire(row)

        session.flush()
        return self.get_selection(session, document_ref)

    def get_selected_candidate(self, session, document_ref: str) -> StructuredContentCandidateV2:
        selection = self.get_selection(session, document_ref)
        return self._candidates.get_candidate(session, selection.candidate_id)


selection_repository_v2 = StructuredContentV2SelectionRepository()
