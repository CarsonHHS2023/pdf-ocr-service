from __future__ import annotations

from pathlib import Path
import runpy


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label} anchor not found")
    return text.replace(old, new, 1)


def main() -> None:
    # First apply the existing clean-final diagnostics: install unpaper,
    # retain outputs, and add bounded stdout/stderr diagnostics.
    runpy.run_path(
        "scripts/apply_ocrmypdf_clean_final_diagnostic.py",
        run_name="__main__",
    )

    preprocessing_path = Path("app/processing/pdf_geometry_preprocessing.py")
    preprocessing = preprocessing_path.read_text(encoding="utf-8")

    preprocessing = replace_once(
        preprocessing,
        'GEOMETRY_PREPROCESSING_VERSION = "ocrmypdf_provider_preprocess_none_clean_final_diagnostic_v4"',
        'GEOMETRY_PREPROCESSING_VERSION = "ocrmypdf_provider_preprocess_pages_3_4_unpaper_diagnostic_v5"',
        "version",
    )

    preprocessing = replace_once(
        preprocessing,
        '        "--rotate-pages",\n',
        "",
        "rotate-pages removal",
    )

    preprocessing = replace_once(
        preprocessing,
        '        "--clean-final",\n        "--deskew",\n',
        '        "--pages",\n'
        '        "3,4",\n'
        '        "--oversample",\n'
        '        "300",\n'
        '        "--clean-final",\n'
        '        "--unpaper-args",\n'
        '        "--layout none --mask-scan-size 100 --no-border-align --no-mask-center --no-blackfilter",\n',
        "selected-page unpaper profile",
    )

    preprocessing_path.write_text(preprocessing, encoding="utf-8")


if __name__ == "__main__":
    main()
