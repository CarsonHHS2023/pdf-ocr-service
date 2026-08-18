from __future__ import annotations

from .selection_repository import StructuredContentSelectionRepository


class StructuredContentSelectionService:
    """Narrow facade for explicit Structured Content selection orchestration."""

    def __init__(self, session, repository: StructuredContentSelectionRepository | None = None):
        self.session = session
        self.repository = repository or StructuredContentSelectionRepository()

    def get_selection(self, document_ref):
        return self.repository.get_selection(self.session, document_ref)

    def get_selected_candidate(self, document_ref):
        return self.repository.get_selected_candidate(self.session, document_ref)

    def select_candidate(self, document_ref, candidate_id, expected_version: int, selected_by: str | None = None, reason: str | None = None):
        return self.repository.set_selection(self.session, document_ref=document_ref, candidate_id=candidate_id, expected_version=expected_version, selected_by=selected_by, reason=reason)

    def rollback_to_candidate(self, document_ref, candidate_id, expected_version: int, selected_by: str | None = None, reason: str | None = None):
        return self.repository.rollback_selection(self.session, document_ref=document_ref, candidate_id=candidate_id, expected_version=expected_version, selected_by=selected_by, reason=reason)
