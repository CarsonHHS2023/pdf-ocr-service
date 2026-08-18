"""Provider-independent normalized observation bundle contracts."""
from __future__ import annotations

from dataclasses import dataclass

from app.processing.structured_result_v2.model import ProcessingEvidence, ProcessingObservation
from app.source_units import SourceUnit


@dataclass(frozen=True, slots=True)
class NormalizedObservationBundle:
    document_ref: str
    source_ref: str
    processing_run_ref: str
    raw_result_ref: str | None
    source_units: tuple[SourceUnit, ...]
    observations: tuple[ProcessingObservation, ...]
    evidence: tuple[ProcessingEvidence, ...]


# PDF currently uses the generic contract directly. The alias preserves the
# Phase 6A name while moving ownership out of the Paddle provider namespace.
NormalizedPdfObservationBundle = NormalizedObservationBundle
