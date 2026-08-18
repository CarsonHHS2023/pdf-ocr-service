"""Small, provider-independent runtime representation for SPR v1."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class StructuredPageStatus(str, Enum):
    """Atlas-owned semantic recovery status for a structured page."""

    USABLE = "usable"
    NO_USABLE_SEMANTIC_CONTENT = "no_usable_semantic_content"


PAGE_HAS_NO_USABLE_SEMANTIC_CONTENT = "PAGE_HAS_NO_USABLE_SEMANTIC_CONTENT"
PARTIAL_DOCUMENT_RECOVERY = "PARTIAL_DOCUMENT_RECOVERY"


def _normalize_page_status(page: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(page)
    status = normalized.get("status", StructuredPageStatus.USABLE)
    try:
        normalized["status"] = StructuredPageStatus(status)
    except (TypeError, ValueError):
        normalized["status"] = status
    normalized["diagnostics"] = (
        [PAGE_HAS_NO_USABLE_SEMANTIC_CONTENT]
        if normalized["status"] is StructuredPageStatus.NO_USABLE_SEMANTIC_CONTENT
        else []
    )
    return normalized


def _document_diagnostics(pages: list[Any]) -> list[str]:
    statuses = [page.get("status") for page in pages if isinstance(page, Mapping)]
    if (
        StructuredPageStatus.USABLE in statuses
        and StructuredPageStatus.NO_USABLE_SEMANTIC_CONTENT in statuses
    ):
        return [PARTIAL_DOCUMENT_RECOVERY]
    return []

@dataclass(frozen=True)
class StructuredProcessingResult:
    """Validated persistence-neutral SPR v1 document.

    The mapping is deliberately a JSON-shaped mapping so optional contract fields
    remain absent rather than being represented by provider-specific sentinels.
    """
    data: Mapping[str, Any]

    def __post_init__(self) -> None:
        data = dict(self.data)
        if isinstance(data.get("pages"), list):
            data["pages"] = [
                _normalize_page_status(page) if isinstance(page, Mapping) else page
                for page in data["pages"]
            ]
            data["diagnostics"] = _document_diagnostics(data["pages"])
        object.__setattr__(self, "data", data)
        from .validation import validate_structured_processing_result

        validate_structured_processing_result(self.data)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.data)
