"""Image service for handling book images."""

from __future__ import annotations

import io
import json
import logging
import uuid

from PIL import Image
from sqlalchemy.orm import Session

from app.models import BookImage
from app.services.visual_asset_enhancement import (
    enhance_visual_asset_bytes,
    visual_asset_enhancement_enabled,
)

logger = logging.getLogger(__name__)


class ImageService:
    """Service for managing book images."""

    @staticmethod
    def save_image(
        db: Session,
        book_id: str,
        image_data: bytes,
        image_format: str = "png",
        page_num: int | None = None,
        bbox: str | None = None,
        block_type: str | None = None,
        enhance: bool = True,
    ) -> str:
        """Save one image and return its stable image identifier.

        Visual blocks are enhanced only after OCR and cropping. Enhancement is
        fail-open and can be disabled globally with
        ``VISUAL_ASSET_ENHANCEMENT_ENABLED=0`` or per call with ``enhance=False``.
        """

        try:
            image_id = f"img_{uuid.uuid4().hex[:8]}"
            stored_data = image_data
            stored_format = (
                str(image_format or "png").strip().lower().lstrip(".") or "png"
            )
            enhancement_metadata: dict = {
                "rendition_kind": "original",
                "fallback_used": False,
                "applied_steps": [],
            }

            if enhance and visual_asset_enhancement_enabled():
                enhanced_data, enhancement_metadata = enhance_visual_asset_bytes(
                    image_data,
                    block_type=block_type,
                )
                if not enhancement_metadata.get("fallback_used", False):
                    stored_data = enhanced_data
                    stored_format = str(
                        enhancement_metadata.get("output_format") or stored_format
                    ).lower()

            image_size = len(stored_data)
            book_image = BookImage(
                book_id=book_id,
                image_id=image_id,
                image_format=stored_format,
                image_data=stored_data,
                image_size=image_size,
                page_num=page_num,
                bbox=bbox,
                block_type=block_type,
            )

            db.add(book_image)
            db.commit()
            db.refresh(book_image)

            logger.info(
                "Saved image: image_id=%s size=%d format=%s enhancement=%s",
                image_id,
                image_size,
                stored_format,
                json.dumps(
                    enhancement_metadata,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
            return image_id

        except Exception as exc:
            db.rollback()
            logger.error("Failed to save image: %s", exc)
            raise

    @staticmethod
    def get_image(db: Session, image_id: str) -> BookImage | None:
        """Get an image from the database by image identifier."""

        return db.query(BookImage).filter(BookImage.image_id == image_id).first()

    @staticmethod
    def delete_image(db: Session, image_id: str) -> bool:
        """Delete one image by identifier."""

        try:
            image = db.query(BookImage).filter(BookImage.image_id == image_id).first()
            if image:
                db.delete(image)
                db.commit()
                logger.info("Deleted image: %s", image_id)
                return True
            return False
        except Exception as exc:
            db.rollback()
            logger.error("Failed to delete image: %s", exc)
            raise

    @staticmethod
    def crop_image_to_region(
        image_data: bytes,
        bbox: list | None = None,
    ) -> bytes:
        """Crop encoded image bytes to an optional ``[x1, y1, x2, y2]`` region."""

        try:
            image = Image.open(io.BytesIO(image_data))

            if bbox:
                x1, y1, x2, y2 = bbox
                image = image.crop((x1, y1, x2, y2))

            output = io.BytesIO()
            image.save(output, format="PNG")
            output.seek(0)

            logger.info("Cropped image, new size: %d bytes", output.getbuffer().nbytes)
            return output.getvalue()

        except Exception as exc:
            logger.error("Failed to crop image: %s", exc)
            raise


_image_service: ImageService | None = None


def get_image_service() -> ImageService:
    global _image_service
    if _image_service is None:
        _image_service = ImageService()
    return _image_service
