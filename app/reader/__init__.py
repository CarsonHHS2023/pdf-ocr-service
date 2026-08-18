"""Public M5 Reader application contract surface."""

from .contracts import (
    READER_APPLICATION_CONTRACT_VERSION,
    ReaderContentChunk,
    ReaderContentState,
    ReaderContinuation,
    ReaderDocumentMetadata,
    ReaderDocumentView,
    ReaderLocation,
    ReaderNavigationEntry,
    ReaderNavigationKind,
    ReaderNodeView,
    ReaderPageView,
    ReaderProcessingState,
    ReaderWarning,
    ReaderWarningCode,
)
from .errors import ReaderContractError, ReaderContractErrorCode, UnsupportedReaderContractVersion
from .serialization import serialize_reader_contract, to_reader_contract_dict
from .service import (
    NoSelectedReaderContent,
    ReaderServiceError,
    SelectedReaderCandidateDocumentMismatch,
    build_selected_reader_document,
)
from .validation import (
    validate_navigation_entry,
    validate_reader_content_chunk,
    validate_reader_document,
    validate_reader_location,
    validate_reader_node,
    validate_reader_page,
)

__all__ = [name for name in globals() if not name.startswith("_")]
