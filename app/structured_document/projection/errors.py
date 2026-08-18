class StructuredDocumentProjectionError(Exception):
    """Base bounded error for Structured Document projection."""
class InvalidProjectionInput(StructuredDocumentProjectionError): pass
class UnsupportedProjectionType(StructuredDocumentProjectionError): pass
class UnsupportedProjectionVersion(StructuredDocumentProjectionError): pass
class ProjectionSourceMismatch(StructuredDocumentProjectionError): pass
class ProjectionInvariantViolation(StructuredDocumentProjectionError): pass
class ProjectionValidationFailed(ProjectionInvariantViolation): pass
