from __future__ import annotations

from enum import Enum


class ReaderContractErrorCode(str, Enum):
    UNSUPPORTED_VERSION = "unsupported_version"
    INVALID_LOCATION = "invalid_location"
    INVALID_NODE = "invalid_node"
    INVALID_PAGE = "invalid_page"
    INVALID_DOCUMENT = "invalid_document"
    INVALID_NAVIGATION = "invalid_navigation"
    INVALID_CHUNK = "invalid_chunk"


class ReaderContractError(ValueError):
    """Bounded validation error without upstream payload or diagnostics."""

    def __init__(self, code: ReaderContractErrorCode, reason: str):
        self.code = code
        self.reason = reason
        super().__init__(f"{code.value}: {reason}")


class UnsupportedReaderContractVersion(ReaderContractError):
    def __init__(self) -> None:
        super().__init__(ReaderContractErrorCode.UNSUPPORTED_VERSION, "unsupported contract version")
