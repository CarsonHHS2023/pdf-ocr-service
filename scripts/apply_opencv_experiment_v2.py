from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label} anchor not found")
    return text.replace(old, new, 1)


def main() -> None:
    path = Path("app/processing/pdf_opencv_experiment.py")
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        'with a background-cleaned binary raster. No OCR is performed here.',
        'with a background-normalized grayscale raster. No OCR is performed here.',
        "module description",
    )
    text = replace_once(
        text,
        'GEOMETRY_PREPROCESSING_VERSION = "opencv_pages_3_4_experiment_v1"',
        'GEOMETRY_PREPROCESSING_VERSION = "opencv_pages_3_4_experiment_v2"',
        "version",
    )
    text = replace_once(
        text,
        '''                steps = (\n                    "opencv_background_normalize",\n                    "opencv_adaptive_binarize",\n                )''',
        '''                steps = (\n                    "opencv_background_estimate",\n                    "opencv_background_divide",\n                    "opencv_grayscale_denoise",\n                    "opencv_background_whiten",\n                )''',
        "page 4 steps",
    )
    text = replace_once(
        text,
        '''    angle, confidence = _estimate_horizontal_angle(corrected)\n    if 0.08 <= abs(angle) <= 5.0:\n        corrected = _rotate_same_canvas(corrected, angle)\n    else:\n        angle = 0.0''',
        '''    angle, confidence = _estimate_text_angle(corrected)\n    if confidence >= 0.35 and 0.08 <= abs(angle) <= 5.0:\n        corrected = _rotate_same_canvas(corrected, angle)\n    else:\n        angle = 0.0''',
        "page 3 deskew",
    )

    gray_scan_old = '''def _process_gray_scan_page(image: np.ndarray) -> tuple[np.ndarray, dict[str, float | bool]]:\n    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)\n    height, width = gray.shape\n    block_size = _odd_clamped(round(min(height, width) / 8), 75, 401)\n    binary = cv2.adaptiveThreshold(\n        gray,\n        255,\n        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,\n        cv2.THRESH_BINARY,\n        block_size,\n        18,\n    )\n    output = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)\n    return output, {\n        "perspective_applied": False,\n        "perspective_confidence": 0.0,\n        "perspective_distortion": 0.0,\n        "deskew_angle_degrees": 0.0,\n        "deskew_confidence": 0.0,\n    }'''
    gray_scan_new = '''def _process_gray_scan_page(image: np.ndarray) -> tuple[np.ndarray, dict[str, float | bool]]:\n    """Remove uneven gray illumination while preserving grayscale text edges."""\n    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)\n\n    # Estimate only broad illumination changes. At 300 DPI this sigma is large\n    # enough to ignore Chinese strokes, table rules, and ordinary halftone dots.\n    sigma = max(24.0, min(gray.shape) / 20.0)\n    background = cv2.GaussianBlur(\n        gray,\n        (0, 0),\n        sigmaX=sigma,\n        sigmaY=sigma,\n        borderType=cv2.BORDER_REPLICATE,\n    )\n    normalized = cv2.divide(gray, np.maximum(background, 1), scale=255)\n\n    # Suppress the paper/halftone texture without converting the page to a\n    # binary image. A low h value protects fine Chinese strokes and table lines.\n    cleaned = cv2.fastNlMeansDenoising(\n        normalized,\n        None,\n        h=4,\n        templateWindowSize=7,\n        searchWindowSize=21,\n    )\n    softly_blurred = cv2.GaussianBlur(cleaned, (0, 0), sigmaX=0.8)\n    cleaned = cv2.addWeighted(cleaned, 1.15, softly_blurred, -0.15, 0)\n\n    # Push only near-white background pixels to white. Midtones remain available\n    # for anti-aliased text and thin table rules.\n    cleaned[cleaned >= 240] = 255\n    output = cv2.cvtColor(cleaned, cv2.COLOR_GRAY2BGR)\n    return output, {\n        "perspective_applied": False,\n        "perspective_confidence": 0.0,\n        "perspective_distortion": 0.0,\n        "deskew_angle_degrees": 0.0,\n        "deskew_confidence": 0.0,\n        "background_sigma": float(sigma),\n        "white_pixel_ratio": float(np.mean(cleaned == 255)),\n        "dark_pixel_ratio": float(np.mean(cleaned <= 48)),\n    }'''
    text = replace_once(text, gray_scan_old, gray_scan_new, "page 4 processor")

    angle_old_start = text.index("def _estimate_horizontal_angle(")
    angle_old_end = text.index("\n\ndef _weighted_median", angle_old_start)
    angle_new = '''def _estimate_text_angle(image: np.ndarray) -> tuple[float, float]:\n    """Estimate text-line skew while excluding page borders and long chart rules."""\n    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)\n    height, width = gray.shape\n    x0, x1 = int(round(width * 0.10)), int(round(width * 0.90))\n    y0, y1 = int(round(height * 0.06)), int(round(height * 0.92))\n    roi = gray[y0:y1, x0:x1]\n    if roi.size == 0:\n        return 0.0, 0.0\n\n    binary = cv2.threshold(\n        roi,\n        0,\n        255,\n        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,\n    )[1]\n\n    # Remove long horizontal/vertical diagram borders before joining characters\n    # into candidate text baselines.\n    horizontal_rules = cv2.morphologyEx(\n        binary,\n        cv2.MORPH_OPEN,\n        cv2.getStructuringElement(\n            cv2.MORPH_RECT,\n            (max(30, roi.shape[1] // 5), 1),\n        ),\n    )\n    vertical_rules = cv2.morphologyEx(\n        binary,\n        cv2.MORPH_OPEN,\n        cv2.getStructuringElement(\n            cv2.MORPH_RECT,\n            (1, max(30, roi.shape[0] // 8)),\n        ),\n    )\n    text_only = cv2.subtract(\n        binary,\n        cv2.bitwise_or(horizontal_rules, vertical_rules),\n    )\n    connected = cv2.morphologyEx(\n        text_only,\n        cv2.MORPH_CLOSE,\n        cv2.getStructuringElement(\n            cv2.MORPH_RECT,\n            (max(12, roi.shape[1] // 18), 1),\n        ),\n    )\n    lines = cv2.HoughLinesP(\n        connected,\n        1,\n        np.pi / 1440.0,\n        threshold=max(24, roi.shape[1] // 12),\n        minLineLength=max(40, roi.shape[1] // 8),\n        maxLineGap=max(10, roi.shape[1] // 40),\n    )\n    if lines is None:\n        return 0.0, 0.0\n\n    angles: list[float] = []\n    weights: list[float] = []\n    for x_start, y_start, x_end, y_end in lines[:, 0, :]:\n        angle = math.degrees(\n            math.atan2(float(y_end - y_start), float(x_end - x_start))\n        )\n        while angle <= -90.0:\n            angle += 180.0\n        while angle > 90.0:\n            angle -= 180.0\n        length = math.hypot(float(x_end - x_start), float(y_end - y_start))\n        if abs(angle) <= 5.0:\n            angles.append(angle)\n            weights.append(length)\n    if not angles:\n        return 0.0, 0.0\n\n    angle = _weighted_median(angles, weights)\n    total_weight = max(1.0, sum(weights))\n    inlier_weight = sum(\n        weight\n        for candidate, weight in zip(angles, weights, strict=True)\n        if abs(candidate - angle) <= 0.75\n    )\n    return angle, min(1.0, inlier_weight / total_weight)'''
    text = text[:angle_old_start] + angle_new + text[angle_old_end:]

    print_old = '''                f"deskew_confidence={diagnostic['deskew_confidence']:.4f} "\n                f"input_size={input_width}x{input_height} "'''
    print_new = '''                f"deskew_confidence={diagnostic['deskew_confidence']:.4f} "\n                f"background_sigma={float(diagnostic.get('background_sigma', 0.0)):.2f} "\n                f"white_pixel_ratio={float(diagnostic.get('white_pixel_ratio', 0.0)):.4f} "\n                f"dark_pixel_ratio={float(diagnostic.get('dark_pixel_ratio', 0.0)):.4f} "\n                f"input_size={input_width}x{input_height} "'''
    text = replace_once(text, print_old, print_new, "page diagnostics")

    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
