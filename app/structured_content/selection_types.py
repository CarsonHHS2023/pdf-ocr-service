from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class StructuredContentSelectionState:
    """Immutable DTO for explicit Structured Content selection lifecycle state."""

    document_ref: str
    candidate_id: str
    selection_version: int
    selected_at: datetime
    selected_by: str | None = None
    reason: str | None = None
