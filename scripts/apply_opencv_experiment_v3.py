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
        'GEOMETRY_PREPROCESSING_VERSION = "opencv_pages_3_4_experiment_v2"',
        'GEOMETRY_PREPROCESSING_VERSION = "opencv_pages_3_4_experiment_v3"',
        "version",
    )

    text = replace_once(
        text,
        '''                steps = (\n                    "opencv_perspective",\n                    "opencv_deskew",\n                    "opencv_illumination_normalize",\n                )''',
        '''                steps = (\n                    "opencv_perspective",\n                    "opencv_deskew",\n                    "opencv_illumination_normalize",\n                    "opencv_showthrough_soft_suppress",\n                )''',
        "page 3 steps",
    )

    text = replace_once(
        text,
        '''                steps = (\n                    "opencv_background_estimate",\n                    "opencv_background_divide",\n                    "opencv_grayscale_denoise",\n                    "opencv_background_whiten",\n                )''',
        '''                steps = (\n                    "opencv_background_estimate",\n                    "opencv_background_divide",\n                    "opencv_texture_median",\n                    "opencv_grayscale_denoise",\n                    "opencv_background_whiten",\n                )''',
        "page 4 steps",
    )

    text = replace_once(
        text,
        '''    normalized = cv2.addWeighted(gray, 0.35, normalized, 0.65, 0)\n    normalized[normalized >= 250] = 255\n    output = cv2.cvtColor(normalized, cv2.COLOR_GRAY2BGR)''',
        '''    normalized = cv2.addWeighted(gray, 0.35, normalized, 0.65, 0)\n\n    # Suppress only faint show-through in the highlight range. Dark foreground\n    # strokes, chart lines, and anti-aliased edges below the threshold remain\n    # effectively unchanged.\n    tone = normalized.astype(np.float32)\n    lift = np.clip((tone - 200.0) / 55.0, 0.0, 1.0)\n    tone += (255.0 - tone) * np.power(lift, 1.7) * 0.45\n    normalized = np.clip(tone, 0.0, 255.0).astype(np.uint8)\n    normalized[normalized >= 250] = 255\n    output = cv2.cvtColor(normalized, cv2.COLOR_GRAY2BGR)''',
        "page 3 show-through suppression",
    )

    text = replace_once(
        text,
        '''    cleaned = cv2.bilateralFilter(\n        normalized,\n        d=5,\n        sigmaColor=12,\n        sigmaSpace=5,\n    )''',
        '''    texture_reduced = cv2.medianBlur(normalized, 3)\n    cleaned = cv2.bilateralFilter(\n        texture_reduced,\n        d=5,\n        sigmaColor=12,\n        sigmaSpace=5,\n    )''',
        "page 4 texture suppression",
    )

    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
