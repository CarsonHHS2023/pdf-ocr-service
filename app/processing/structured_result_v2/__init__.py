"""Source-unit-centric Structured Processing Result v2 contracts."""

from .model import (
    ProcessingEvidence,
    ProcessingNode,
    ProcessingNodeKind,
    ProcessingNodeRecoveryState,
    ProcessingObservation,
    StructuredProcessingResultV2,
    normalize_spr_v2,
)
from .validation import validate_spr_v2

__all__ = [
    "ProcessingEvidence",
    "ProcessingNode",
    "ProcessingNodeKind",
    "ProcessingNodeRecoveryState",
    "ProcessingObservation",
    "StructuredProcessingResultV2",
    "normalize_spr_v2",
    "validate_spr_v2",
]
