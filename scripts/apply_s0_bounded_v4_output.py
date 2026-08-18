"""Install the S0 bounded ordinary-V4 output compatibility layer."""
from __future__ import annotations

from pathlib import Path


PDF_INGESTION_PATH = Path("app/processing/pdf_ingestion.py")
_IMPORT_ANCHOR = (
    "from app.processing.pdf_s0_bounded_memory_compat import "
    "install_s0_bounded_memory_compat\n"
)
_IMPORT_WITH_BOUNDED_V4 = (
    _IMPORT_ANCHOR
    + "from app.processing.pdf_s0_bounded_v4_output_compat import "
    "install_s0_bounded_v4_output_compat\n"
)
_CALL_ANCHOR = "install_s0_bounded_memory_compat()\n\n"
_CALL_WITH_BOUNDED_V4 = (
    "install_s0_bounded_memory_compat()\n"
    "install_s0_bounded_v4_output_compat()\n\n"
)


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    if source.count(old) != 1:
        raise RuntimeError(f"Could not find unique {label} anchor")
    return source.replace(old, new, 1)


def patch_s0_bounded_v4_output_installation(
    path: Path = PDF_INGESTION_PATH,
) -> None:
    """Install after final page ownership and before provider transport sharding."""
    source = path.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        _IMPORT_ANCHOR,
        _IMPORT_WITH_BOUNDED_V4,
        "bounded V4 output import",
    )
    source = _replace_once(
        source,
        _CALL_ANCHOR,
        _CALL_WITH_BOUNDED_V4,
        "bounded V4 output install",
    )
    path.write_text(source, encoding="utf-8")


def main() -> None:
    patch_s0_bounded_v4_output_installation()


if __name__ == "__main__":
    main()
