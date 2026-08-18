from __future__ import annotations

import cv2
import fitz
import numpy as np

from app.processing.pdf_opencv_quality_pipeline import (
    GEOMETRY_PREPROCESSING_VERSION,
    _color_features,
    _gate_background_candidate,
    _normalize_background,
    preprocess_pdf_geometry_opencv,
)


def _encoded_png(image: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def _raster_page(document: fitz.Document, image: np.ndarray) -> None:
    page = document.new_page(width=300, height=420)
    page.insert_image(page.rect, stream=_encoded_png(image))


def main() -> None:
    height, width = 840, 600
    document = fitz.open()

    color = np.full((height, width, 3), 245, dtype=np.uint8)
    cv2.rectangle(color, (30, 30), (570, 300), (20, 20, 220), -1)
    cv2.rectangle(color, (30, 320), (570, 800), (20, 210, 240), -1)
    cv2.putText(
        color,
        "COLOR COVER",
        (80, 180),
        cv2.FONT_HERSHEY_SIMPLEX,
        2,
        (255, 255, 255),
        5,
    )
    _raster_page(document, color)

    page = document.new_page(width=300, height=420)
    for row in range(16):
        page.insert_text(
            (35, 45 + row * 20),
            "Born digital paragraph text for structure detection.",
            fontsize=10,
        )

    photo = np.full((height, width, 3), 235, dtype=np.uint8)
    gradient = np.linspace(0, 20, width, dtype=np.uint8)
    photo = np.clip(photo - gradient[None, :, None], 0, 255).astype(np.uint8)
    for row in range(12):
        cv2.putText(
            photo,
            "SCANNED TEXT LINE",
            (75, 120 + row * 42),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (35, 35, 35),
            2,
        )
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), 1.4, 1.0)
    photo = cv2.warpAffine(
        photo,
        matrix,
        (width, height),
        borderValue=(255, 255, 255),
    )
    _raster_page(document, photo)

    # Use an uneven gray scan background so the quality gate has a real,
    # measurable cleanup opportunity. A perfectly uniform gray fixture should
    # be rejected as "no material improvement", which is correct behavior.
    gray_gradient = np.linspace(170.0, 230.0, width, dtype=np.float32)
    gray_plane = np.tile(gray_gradient, (height, 1)).astype(np.uint8)
    gray = cv2.merge((gray_plane, gray_plane, gray_plane))
    for row in range(14):
        cv2.putText(
            gray,
            "GRAY SCAN TEXT",
            (80, 100 + row * 42),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (35, 35, 35),
            2,
        )
    cv2.line(gray, (70, 700), (530, 700), (30, 30, 30), 2)
    _raster_page(document, gray)

    chart = np.full((height, width, 3), 248, dtype=np.uint8)
    cv2.rectangle(chart, (80, 250), (520, 650), (185, 185, 185), -1)
    for x in range(100, 510, 55):
        cv2.line(chart, (x, 270), (x, 630), (90, 90, 90), 1)
    for y in range(280, 630, 50):
        cv2.line(chart, (95, y), (505, y), (90, 90, 90), 1)
    cv2.putText(
        chart,
        "STOCK CHART",
        (165, 215),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (30, 30, 30),
        2,
    )
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), 0.9, 1.0)
    chart = cv2.warpAffine(
        chart,
        matrix,
        (width, height),
        borderValue=(255, 255, 255),
    )
    _raster_page(document, chart)

    source = document.tobytes()
    document.close()

    result = preprocess_pdf_geometry_opencv(source, expected_page_count=5)
    assert result.version == GEOMETRY_PREPROCESSING_VERSION
    assert result.version.endswith("experiment_v4")
    assert result.page_count == 5
    assert result.pdf_bytes.startswith(b"%PDF-")

    # All source pages must enter the same top-level classification pipeline.
    # Pages 1 and 2 are not pre-excluded by page number: the classifier itself
    # must select safe no-op behavior for the color-critical and born-digital
    # fixtures, while pages 3-5 continue through the normal quality gates.
    assert tuple(page.page_index for page in result.pages) == tuple(range(5))
    assert result.pages[0].route.startswith("color_critical")
    assert result.pages[0].route in {
        "color_critical_no_op",
        "color_critical_geometry",
    }
    assert not any(
        step.startswith("opencv_background")
        for step in result.pages[0].applied_steps
    )
    assert result.pages[1].route == "born_digital_no_op"
    assert result.pages[1].safe_reason == "born_digital_preserved"
    assert result.pages[1].applied_steps == ()
    assert all(page.route != "born_digital_no_op" for page in result.pages[2:])

    assert result.changed_page_count >= 1
    assert all(
        "opencv_adaptive_binarize" not in page.applied_steps
        for page in result.pages
    )

    output = fitz.open(stream=result.pdf_bytes, filetype="pdf")
    assert output.page_count == 5
    output.close()

    candidate = _normalize_background(gray)
    accepted, reason, gate = _gate_background_candidate(gray, candidate)
    assert accepted, (reason, gate)
    assert gate["edge_retention"] >= 0.70
    assert _color_features(color).color_critical is True
    assert _color_features(gray).color_critical is False


if __name__ == "__main__":
    main()
