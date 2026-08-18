from .assembler import assemble_structured_document
from .errors import (
    InvalidAssemblyPolicy,
    InvalidStructuredContentInput,
    StructuredDocumentAssemblyError,
    StructuredDocumentAssemblyNotImplemented,
    StructuredDocumentAssemblyInvariantViolation,
    StructuredDocumentValidationFailed,
    StructuredDocumentError,
    UnsupportedAssemblyPolicyVersion,
    UnsupportedStructuredDocumentVersion,
)
from .types import (
    DEFAULT_STRUCTURED_DOCUMENT_ASSEMBLY_POLICY,
    SUPPORTED_ASSEMBLY_POLICY_VERSION,
    SUPPORTED_STRUCTURED_DOCUMENT_SCHEMA_VERSION,
    StructuredDocument,
    StructuredDocumentAssemblyPolicy,
    StructuredDocumentNodeView,
    StructuredDocumentPageView,
)

from .service import (
    NoSelectedStructuredContent,
    SelectedCandidateDocumentMismatch,
    StructuredDocumentServiceError,
    build_selected_document_projection,
)

__all__ = [name for name in globals() if not name.startswith("_")]
