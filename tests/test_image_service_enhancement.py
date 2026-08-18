from __future__ import annotations

from app import image_service as image_service_module
from app.image_service import ImageService


class FakeSession:
    def __init__(self) -> None:
        self.added = []
        self.committed = False
        self.rolled_back = False

    def add(self, value) -> None:
        self.added.append(value)

    def commit(self) -> None:
        self.committed = True

    def refresh(self, value) -> None:
        return None

    def rollback(self) -> None:
        self.rolled_back = True


def test_save_image_persists_enhanced_png(monkeypatch) -> None:
    db = FakeSession()
    monkeypatch.setattr(
        image_service_module,
        "visual_asset_enhancement_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        image_service_module,
        "enhance_visual_asset_bytes",
        lambda image_data, block_type=None: (
            b"enhanced-png",
            {
                "output_format": "png",
                "fallback_used": False,
                "applied_steps": ["deskew"],
                "block_type": block_type,
            },
        ),
    )

    image_id = ImageService.save_image(
        db=db,
        book_id="book-1",
        image_data=b"source-jpeg",
        image_format="jpg",
        page_num=7,
        bbox="1,2,30,40",
        block_type="table",
    )

    assert image_id.startswith("img_")
    assert db.committed is True
    assert db.rolled_back is False
    stored = db.added[0]
    assert stored.image_data == b"enhanced-png"
    assert stored.image_format == "png"
    assert stored.image_size == len(b"enhanced-png")
    assert stored.block_type == "table"


def test_save_image_can_bypass_enhancement(monkeypatch) -> None:
    db = FakeSession()

    def should_not_run(*args, **kwargs):
        raise AssertionError("enhancer should not be called")

    monkeypatch.setattr(
        image_service_module,
        "enhance_visual_asset_bytes",
        should_not_run,
    )
    ImageService.save_image(
        db=db,
        book_id="book-1",
        image_data=b"original",
        image_format="jpg",
        block_type="photo",
        enhance=False,
    )

    stored = db.added[0]
    assert stored.image_data == b"original"
    assert stored.image_format == "jpg"


def test_save_image_preserves_original_bytes_when_enhancement_falls_back(
    monkeypatch,
) -> None:
    db = FakeSession()
    monkeypatch.setattr(
        image_service_module,
        "visual_asset_enhancement_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        image_service_module,
        "enhance_visual_asset_bytes",
        lambda image_data, block_type=None: (
            b"reencoded-but-rejected",
            {
                "output_format": "png",
                "fallback_used": True,
                "reason": "quality_gate_rejected",
            },
        ),
    )

    ImageService.save_image(
        db=db,
        book_id="book-1",
        image_data=b"original-jpeg",
        image_format="jpg",
        block_type="photo",
    )

    stored = db.added[0]
    assert stored.image_data == b"original-jpeg"
    assert stored.image_format == "jpg"
