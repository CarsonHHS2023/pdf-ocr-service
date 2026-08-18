"""Install native PDF text recovery in the isolated test build."""
from __future__ import annotations

from pathlib import Path

try:
    from scripts.apply_provider_transport_sharding import (
        patch_provider_transport_sharding_installation,
    )
except ModuleNotFoundError:  # ``python scripts/...`` places scripts/ on sys.path.
    from apply_provider_transport_sharding import (  # type: ignore[no-redef]
        patch_provider_transport_sharding_installation,
    )


_IMPORT_ANCHOR = (
    "from app.processing.pdf_page_high_resolution_confirmation_compat import "
    "install_high_resolution_page_confirmation_compat\n"
)
_IMPORT_WITH_NATIVE = (
    _IMPORT_ANCHOR
    + "from app.processing.pdf_native_text_compat import "
    "install_native_pdf_text_compat\n"
    + "from app.processing.pdf_native_orientation_preservation_compat import "
    "install_native_orientation_preservation_compat\n"
)
_CALL_ANCHOR = "install_high_resolution_page_confirmation_compat()\n\n"
_CALL_WITH_NATIVE = (
    "install_high_resolution_page_confirmation_compat()\n"
    "install_native_pdf_text_compat()\n"
    "install_native_orientation_preservation_compat()\n\n"
)


def _replace_once(path: Path, old: str, new: str, *, label: str) -> None:
    source = path.read_text(encoding="utf-8")
    if new in source:
        return
    if source.count(old) != 1:
        raise RuntimeError(f"Could not find unique {label} in {path}")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


def _patch_installation() -> None:
    path = Path("app/processing/pdf_ingestion.py")
    _replace_once(
        path,
        _IMPORT_ANCHOR,
        _IMPORT_WITH_NATIVE,
        label="native text import anchor",
    )
    _replace_once(
        path,
        _CALL_ANCHOR,
        _CALL_WITH_NATIVE,
        label="native text install anchor",
    )


def _patch_preprocess_accounting() -> None:
    path = Path("app/processing/pdf_page_presentation_preprocess_compat.py")
    _replace_once(
        path,
        "        presentation_count = page_count - provider_page_count\n",
        "        local_result_count = page_count - provider_page_count\n"
        "        native_text_count = sum(\n"
        "            1 for item in decisions if item.get(\"native_text_accepted\")\n"
        "        )\n"
        "        presentation_count = local_result_count - native_text_count\n",
        label="local result accounting anchor",
    )
    _replace_once(
        path,
        "        elif presentation_count == 0:\n",
        "        elif local_result_count == 0:\n",
        label="provider subset accounting anchor",
    )
    _replace_once(
        path,
        "            \"presentation_page_count\": presentation_count,\n"
        "            \"pages\": page_entries,\n",
        "            \"presentation_page_count\": presentation_count,\n"
        "            \"native_text_page_count\": native_text_count,\n"
        "            \"local_result_page_count\": local_result_count,\n"
        "            \"native_text_version\": \"native_pdf_text_v1\",\n"
        "            \"pages\": page_entries,\n",
        label="native manifest accounting anchor",
    )
    _replace_once(
        path,
        "            presentation_page_count=presentation_count,\n"
        "        )\n",
        "            presentation_page_count=presentation_count,\n"
        "            native_text_page_count=native_text_count,\n"
        "            local_result_page_count=local_result_count,\n"
        "        )\n",
        label="native diagnostic accounting anchor",
    )
    _replace_once(
        path,
        "                \"presentation_original\",\n"
        "            }\n",
        "                \"presentation_original\",\n"
        "                \"native_pdf_text_no_op\",\n"
        "            }\n",
        label="native unchanged route anchor",
    )


def main() -> None:
    _patch_installation()
    _patch_preprocess_accounting()
    patch_provider_transport_sharding_installation()


if __name__ == "__main__":
    main()
