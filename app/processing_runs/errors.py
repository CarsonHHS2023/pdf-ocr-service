from __future__ import annotations

class ProcessingRunRepositoryError(Exception):
    """Base bounded error for ProcessingRun repository operations."""

class ProcessingRunInvalid(ProcessingRunRepositoryError): pass
class ProcessingRunAlreadyExists(ProcessingRunRepositoryError): pass
class ProcessingRunConflict(ProcessingRunRepositoryError): pass
class ProcessingRunNotFound(ProcessingRunRepositoryError): pass
class ProcessingRunDocumentNotFound(ProcessingRunRepositoryError): pass
class ProcessingRunSourceFileMismatch(ProcessingRunRepositoryError): pass
class ProcessingRunInvalidTransition(ProcessingRunRepositoryError): pass
class ProcessingRunPersistenceError(ProcessingRunRepositoryError): pass
class PersistedProcessingRunCorrupt(ProcessingRunRepositoryError): pass
class CandidateProcessingRunMismatch(ProcessingRunRepositoryError): pass
