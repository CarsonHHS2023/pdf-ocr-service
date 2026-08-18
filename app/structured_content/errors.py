from __future__ import annotations

class StructuredContentRepositoryError(Exception):
    """Base bounded error for structured content repository operations."""

class InvalidStructuredContentCandidate(StructuredContentRepositoryError):
    def __init__(self, issues: list[str]):
        self.issues = tuple(issues[:20])
        super().__init__("invalid structured content candidate: " + "; ".join(self.issues))

class StructuredContentCandidateAlreadyExists(StructuredContentRepositoryError): pass
class StructuredContentCandidateConflict(StructuredContentRepositoryError): pass
class StructuredContentCandidateNotFound(StructuredContentRepositoryError): pass
class CandidateDocumentNotFound(StructuredContentRepositoryError): pass
class CandidateDocumentMismatch(StructuredContentRepositoryError): pass
class CandidatePersistenceError(StructuredContentRepositoryError): pass
class PersistedCandidateCorrupt(StructuredContentRepositoryError):
    def __init__(self, issues: list[str] | str):
        if isinstance(issues, str): issues = [issues]
        self.issues = tuple(issues[:20])
        super().__init__("persisted structured content candidate corrupt: " + "; ".join(self.issues))

class CandidateSelectionDocumentNotFound(StructuredContentRepositoryError): pass
class CandidateSelectionCandidateNotFound(StructuredContentRepositoryError): pass
class CandidateSelectionDocumentMismatch(StructuredContentRepositoryError): pass
class CandidateSelectionCorrupt(StructuredContentRepositoryError): pass
class CandidateNotSelectable(StructuredContentRepositoryError): pass
class CandidateSelectionPersistenceError(StructuredContentRepositoryError): pass
class CandidateSelectionConflict(StructuredContentRepositoryError):
    def __init__(self, *, document_ref: str, expected_version: int, actual_version: int | None):
        self.document_ref = document_ref
        self.expected_version = expected_version
        self.actual_version = actual_version
        actual = "no selection" if actual_version is None else str(actual_version)
        super().__init__(f"selection version conflict for document {document_ref}: expected {expected_version}, actual {actual}")

class CandidateProcessingRunMismatch(StructuredContentRepositoryError): pass
