"""Image serving routes."""

from __future__ import annotations

import io
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.image_service import get_image_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/images", tags=["images"])


@router.get("/{image_id}")
async def get_image(image_id: str, db: Session = Depends(get_db)):
    """
    Get image by image_id and return as PNG.

    Args:
        image_id: Image ID (e.g., "img_uuid_001")

    Returns:
        PNG image binary data
    """
    try:
        image_service = get_image_service()
        book_image = image_service.get_image(db, image_id)

        if not book_image:
            logger.warning(f"Image not found: {image_id}")
            raise HTTPException(status_code=404, detail="Image not found")

        logger.info(f"Retrieved image: {image_id}, size: {book_image.image_size} bytes")

        # Return image as streaming response with proper content type
        return StreamingResponse(
            iter([book_image.image_data]),
            media_type=f"image/{book_image.image_format}",
            headers={"Content-Disposition": f"inline; filename={image_id}.{book_image.image_format}"},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get image: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get image: {e}")


@router.get("/page_crop/{book_id}/{page_num}")
async def get_page_crop(
    book_id: str,
    page_num: int,
    x1: int = Query(..., description="Left edge of bounding box (pixels)"),
    y1: int = Query(..., description="Top edge of bounding box (pixels)"),
    x2: int = Query(..., description="Right edge of bounding box (pixels)"),
    y2: int = Query(..., description="Bottom edge of bounding box (pixels)"),
    db: Session = Depends(get_db),
):
    """Crop a region from a stored PDF page image and return it as PNG.

    The frontend uses this endpoint when it encounters a ``$%$%$%{image_id}$%$%$%``
    marker in the book content and needs to retrieve the corresponding visual
    block from the original page.  The ``image_id`` stored in ``book_images``
    already contains the pre-cropped PNG; this endpoint additionally supports
    on-demand cropping directly from the full page stored in ``pdf_pages``.

    Args:
        book_id:  Book ID.
        page_num: 1-based page number.
        x1, y1, x2, y2: Bounding box coordinates in the rendered page's
                        pixel space (same coordinate system used when the
                        PDF was rendered at ``_RENDER_DPI`` DPI).

    Returns:
        PNG image of the requested region.
    """
    try:
        import numpy as np
        import cv2  # type: ignore[import]

        from app.models import PdfPage

        page = (
            db.query(PdfPage)
            .filter(PdfPage.book_id == book_id, PdfPage.page_num == page_num)
            .first()
        )
        if page is None or not page.page_image_data:
            raise HTTPException(
                status_code=404,
                detail=f"Page {page_num} not found for book {book_id}",
            )

        nparr = np.frombuffer(page.page_image_data, dtype=np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise HTTPException(status_code=500, detail="Failed to decode page image")

        h, w = img.shape[:2]
        cx1 = max(0, min(x1, w))
        cy1 = max(0, min(y1, h))
        cx2 = max(0, min(x2, w))
        cy2 = max(0, min(y2, h))

        if cx1 >= cx2 or cy1 >= cy2:
            raise HTTPException(status_code=400, detail="Invalid bounding box")

        crop = img[cy1:cy2, cx1:cx2]
        ok, enc = cv2.imencode(".png", crop)
        if not ok:
            raise HTTPException(status_code=500, detail="Failed to encode crop")

        png_bytes = enc.tobytes()
        logger.info(
            "Page crop: book=%s page=%d bbox=[%d,%d,%d,%d] size=%d bytes",
            book_id, page_num, x1, y1, x2, y2, len(png_bytes),
        )
        return StreamingResponse(
            io.BytesIO(png_bytes),
            media_type="image/png",
            headers={"Content-Disposition": f"inline; filename=crop_p{page_num}.png"},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get page crop: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get page crop: {e}")


@router.delete("/{image_id}")
async def delete_image(image_id: str, db: Session = Depends(get_db)) -> dict:
    """
    Delete image from database.

    Args:
        image_id: Image ID

    Returns:
        Success message
    """
    try:
        image_service = get_image_service()
        success = image_service.delete_image(db, image_id)

        if not success:
            raise HTTPException(status_code=404, detail="Image not found")

        logger.info(f"Deleted image: {image_id}")
        return {"message": f"Image {image_id} deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete image: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete image: {e}")

