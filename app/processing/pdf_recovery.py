"""Canonical PDF structure-recovery entry point.

The public import path is retained for compatibility. PDF recovery first runs
through the provider-independent MinerU/Popo-style semantic engine, then adds
page-presentation furniture for semantic full-page Reader rendering.
"""
from __future__ import annotations

from app.processing.mineru_popo_pdf_recovery import (
    recover_pdf_observations_via_mineru_popo,
)
from app.processing.pdf_page_presentation_recovery import (
    recover_pdf_observations_for_page_presentation,
)


# Compatibility name used by PdfCanonicalizationService and existing callers.
recover_pdf_observations_to_spr_v2 = recover_pdf_observations_for_page_presentation


__all__ = [
    "recover_pdf_observations_for_page_presentation",
    "recover_pdf_observations_to_spr_v2",
    "recover_pdf_observations_via_mineru_popo",
]
