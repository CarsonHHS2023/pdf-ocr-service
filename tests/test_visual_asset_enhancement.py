from __future__ import annotations

import cv2
import numpy as np

from app.services.visual_asset_enhancement import (
    ENHANCEMENT_VERSION,
    enhance_visual_asset,
    enhance_visual_asset_bytes,
)


def _white_canvas(width: int = 420, height: int = 260) -> np.ndarray:
    return np.full((height, width, 3), 255, dtype=np.uint8)


def test_empty_bytes_fail_open() -> None:
    output, metadata = enhance_visual_asset_bytes(b"", block_type="table")
    assert output == b""
    assert metadata["fallback_used"] is True
    assert metadata["reason"] == "empty_input"


def test_small_image_returns_original() -> None:
    image = np.full((12, 12, 3), 127, dtype=np.uint8)
    result = enhance_visual_asset(image, block_type="image")
    assert np.array_equal(result.image, image)
    assert result.metadata["fallback_used"] is True
    assert result.metadata["reason"] == "image_too_small"


def test_table_deskew_is_applied_to_consistent_horizontal_lines() -> None:
    canvas = _white_canvas()
    for y in range(55, 220, 32):
        cv2.line(canvas, (35, y), (385, y), (20, 20, 20), 3)
    for x in range(35, 386, 70):
        cv2.line(canvas, (x, 45), (x, 225), (20, 20, 20), 2)

    matrix = cv2.getRotationMatrix2D((210, 130), 2.2, 1.0)
    skewed = cv2.warpAffine(
        canvas,
        matrix,
        (420, 260),
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )
    result = enhance_visual_asset(skewed, block_type="table")

    assert result.metadata["enhancement_version"] == ENHANCEMENT_VERSION
    assert result.metadata["fallback_used"] is False
    assert "deskew" in result.metadata["applied_steps"]
    assert abs(result.metadata["deskew_angle_degrees"]) > 1.0
    assert result.image.ndim == 3


def test_color_sensitive_asset_stays_color() -> None:
    image = _white_canvas(180, 120)
    cv2.circle(image, (90, 60), 35, (0, 0, 220), -1)
    result = enhance_visual_asset(image, block_type="seal")

    assert result.metadata["fallback_used"] is False
    assert "mild_color_denoise" in result.metadata["applied_steps"]
    assert result.image.shape[2] == 3
    center = result.image[35:85, 65:115]
    assert float(center[:, :, 2].mean()) > float(center[:, :, 0].mean()) + 80


def test_bytes_output_is_png_and_metadata_is_bounded() -> None:
    image = _white_canvas(220, 140)
    cv2.rectangle(image, (20, 20), (200, 120), (30, 30, 30), 2)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok

    output, metadata = enhance_visual_asset_bytes(
        encoded.tobytes(),
        block_type="figure",
    )
    decoded = cv2.imdecode(np.frombuffer(output, dtype=np.uint8), cv2.IMREAD_COLOR)

    assert decoded is not None
    assert output.startswith(b"\x89PNG")
    assert metadata["output_format"] == "png"
    assert metadata["enhancement_version"] == ENHANCEMENT_VERSION
