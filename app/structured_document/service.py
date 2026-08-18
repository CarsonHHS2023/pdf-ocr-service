from __future__ import annotations

from app.structured_content.identity import DocumentRef
from app.structured_content.persistence_mapping import sval
from app.structured_content.repository import StructuredContentCandidateRepository
from app.structured_content.selection_repository import StructuredContentSelectionRepository
from app.structured_document.assembler import assemble_structured_document
from app.structured_document.projection.projector import project_structured_document
from app.structured_document.projection.types import (
    DEFAULT_PROJECTION_POLICY,
    ProjectionPolicy,
    ReaderContentStreamV2Projection,
)
from app.structured_document.types import (
    DEFAULT_STRUCTURED_DOCUMENT_ASSEMBLY_POLICY,
    StructuredDocumentAssemblyPolicy,
)


class StructuredDocumentServiceError(Exception):
    """Base bounded error for Structured Document orchestration."""


class NoSelectedStructuredContent(StructuredDocumentServiceError):
    """Raised when a document has no explicit Structured Content selection."""


class SelectedCandidateDocumentMismatch(StructuredDocumentServiceError):
    """Raised when selected candidate reconstruction does not match the document."""


def build_selected_document_projection(
    *,
    session,
    document_ref: DocumentRef | str,
    candidate_repository: StructuredContentCandidateRepository | None = None,
    selection_repository: StructuredContentSelectionRepository | None = None,
    assembly_policy: StructuredDocumentAssemblyPolicy = DEFAULT_STRUCTURED_DOCUMENT_ASSEMBLY_POLICY,
    projection_policy: ProjectionPolicy = DEFAULT_PROJECTION_POLICY,
) -> ReaderContentStreamV2Projection:
    """Assemble and project the explicitly selected Structured Content candidate.

    This service boundary is read/orchestration only: selection lookup is
    authoritative, the selected candidate is reconstructed from the repository,
    and the Structured Document plus Reader v2 projection remain derived in
    memory.
    """

    document_id = sval(document_ref)
    candidates = candidate_repository or StructuredContentCandidateRepository()
    selections = selection_repository or StructuredContentSelectionRepository(candidates)

    selection = selections.get_selection(session, document_id)
    if selection is None:
        raise NoSelectedStructuredContent(f"no selected structured content candidate for document {document_id}")

    candidate = candidates.get_candidate(session, selection.candidate_id)
    if sval(candidate.document_ref) != document_id:
        raise SelectedCandidateDocumentMismatch(
            f"selected candidate {selection.candidate_id} does not belong to document {document_id}"
        )

    structured_document = assemble_structured_document(candidate, policy=assembly_policy)
    return project_structured_document(structured_document, candidate=candidate, policy=projection_policy)
