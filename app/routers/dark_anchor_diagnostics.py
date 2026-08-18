"""Test-only downloads for dark-foreground-anchor histogram diagnostics.

The histogram artifacts are independent diagnostic storage objects, never Reader
renditions. This router is intentionally separate from the normal Reader v2
router so startup/import ordering cannot change Reader fallback behavior.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.database import get_db


router = APIRouter(prefix="/api/reader/v2", tags=["reader-v2-diagnostics"])


def _build_delivery(
    *,
    db: Session,
    document_ref: str,
    candidate_id: str,
    asset_id: str,
    kind: str,
):
    # Delay both imports until request time. The PDF test overlays are installed
    # while app.main imports the OCR router, so eager Reader/diagnostic imports
    # here would recreate a circular-startup dependency.
    from app.processing import pdf_crop_dark_foreground_anchor_diagnostics_compat as diagnostics
    from app.routers import reader_v2

    try:
        return diagnostics._build_delivery(
            session=db,
            document_ref=document_ref,
            candidate_id=candidate_id,
            asset_id=asset_id,
            kind=kind,
        )
    except Exception as exc:
        reader_v2._map_asset_build_error(exc)


def _deliver(delivery, *, attachment_filename: str) -> Response:
    from app.routers import reader_v2

    return reader_v2._deliver_asset_bytes(
        delivery,
        attachment_filename=attachment_filename,
    )


@router.get(
    "/documents/{document_ref}/assets/{asset_id}/diagnostics/dark-anchor-histogram/plot"
)
def download_dark_anchor_histogram_plot(
    document_ref: str,
    asset_id: str,
    candidate_id: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
) -> Response:
    """Download the annotated histogram used by dark-anchor analysis."""
    delivery = _build_delivery(
        db=db,
        document_ref=document_ref,
        candidate_id=candidate_id,
        asset_id=asset_id,
        kind="plot",
    )
    return _deliver(delivery, attachment_filename="dark-anchor-histogram.png")


@router.get(
    "/documents/{document_ref}/assets/{asset_id}/diagnostics/dark-anchor-histogram/data"
)
def download_dark_anchor_histogram_data(
    document_ref: str,
    asset_id: str,
    candidate_id: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
) -> Response:
    """Download all raw/smoothed bins and exact algorithm-selected positions."""
    delivery = _build_delivery(
        db=db,
        document_ref=document_ref,
        candidate_id=candidate_id,
        asset_id=asset_id,
        kind="data",
    )
    return _deliver(delivery, attachment_filename="dark-anchor-histogram.json")


__all__ = ["router"]
