"""Install the high-resolution pre-OCR confirmation layer in the test build."""
from __future__ import annotations

from pathlib import Path


_IMPORT_ANCHOR = (
    "from app.processing.pdf_page_analysis_fail_open_compat import "
    "install_analysis_render_fail_open_compat\n"
)
_IMPORT_WITH_CONFIRMATION = (
    _IMPORT_ANCHOR
    + "from app.processing.pdf_page_high_resolution_confirmation_compat import "
    "install_high_resolution_page_confirmation_compat\n"
)
_CALL_ANCHOR = "install_analysis_render_fail_open_compat()\n\n"
_CALL_WITH_CONFIRMATION = (
    "install_analysis_render_fail_open_compat()\n"
    "install_high_resolution_page_confirmation_compat()\n\n"
)


def _replace_once(path: Path, old: str, new: str, *, label: str) -> None:
    source = path.read_text(encoding="utf-8")
    if new in source:
        return
    if source.count(old) != 1:
        raise RuntimeError(f"Could not find unique {label} in {path}")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


def _patch_pdf_ingestion_installation() -> None:
    path = Path("app/processing/pdf_ingestion.py")
    _replace_once(
        path,
        _IMPORT_ANCHOR,
        _IMPORT_WITH_CONFIRMATION,
        label="high-resolution confirmation import anchor",
    )
    _replace_once(
        path,
        _CALL_ANCHOR,
        _CALL_WITH_CONFIRMATION,
        label="high-resolution confirmation install anchor",
    )


def main() -> None:
    _patch_pdf_ingestion_installation()


if __name__ == "__main__":
    main()
