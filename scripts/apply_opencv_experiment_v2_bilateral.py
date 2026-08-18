from __future__ import annotations

from pathlib import Path


def main() -> None:
    path = Path("app/processing/pdf_opencv_experiment.py")
    text = path.read_text(encoding="utf-8")
    old = '''    # Suppress the paper/halftone texture without converting the page to a\n    # binary image. A low h value protects fine Chinese strokes and table lines.\n    cleaned = cv2.fastNlMeansDenoising(\n        normalized,\n        None,\n        h=4,\n        templateWindowSize=7,\n        searchWindowSize=21,\n    )'''
    new = '''    # Suppress paper/halftone texture without converting the page to binary.\n    # A small bilateral window protects fine Chinese strokes and table rules,\n    # and remains practical for 300 DPI pages.\n    cleaned = cv2.bilateralFilter(\n        normalized,\n        d=5,\n        sigmaColor=12,\n        sigmaSpace=5,\n    )'''
    if old not in text:
        raise SystemExit("OpenCV v2 denoising anchor not found")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


if __name__ == "__main__":
    main()
