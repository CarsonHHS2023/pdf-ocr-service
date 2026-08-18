"""Install the final S0 bounded-memory presentation compatibility layer."""
from __future__ import annotations

from pathlib import Path


PDF_INGESTION_PATH = Path("app/processing/pdf_ingestion.py")
_IMPORT_ANCHOR = (
    "from app.processing.pdf_native_orientation_preservation_compat import "
    "install_native_orientation_preservation_compat\n"
)
_IMPORT_WITH_BOUNDED = (
    _IMPORT_ANCHOR
    + "from app.processing.pdf_s0_bounded_memory_compat import "
    "install_s0_bounded_memory_compat\n"
)
_CALL_ANCHOR = "install_native_orientation_preservation_compat()\n\n"
_CALL_WITH_BOUNDED = (
    "install_native_orientation_preservation_compat()\n"
    "install_s0_bounded_memory_compat()\n\n"
)


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    if source.count(old) != 1:
        raise RuntimeError(f"Could not find unique {label} anchor")
    return source.replace(old, new, 1)


def patch_s0_bounded_memory_installation(
    path: Path = PDF_INGESTION_PATH,
) -> None:
    """Install after native/orientation routing so this is the final page owner."""
    source = path.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        _IMPORT_ANCHOR,
        _IMPORT_WITH_BOUNDED,
        "bounded-memory import",
    )
    source = _replace_once(
        source,
        _CALL_ANCHOR,
        _CALL_WITH_BOUNDED,
        "bounded-memory install",
    )
    path.write_text(source, encoding="utf-8")


def main() -> None:
    patch_s0_bounded_memory_installation()


if __name__ == "__main__":
    main()
