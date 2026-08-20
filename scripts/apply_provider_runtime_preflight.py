"""Install fail-fast PDF provider runtime validation in staging ingestion.

The narrow ``patch_provider_runtime_preflight`` helper remains independently
usable.  The CLI entrypoint is the ordered Staging provider-runtime installer:
after preflight is present it also installs the existing presigned provider-input
lifecycle so the artifact tested by Staging CI matches the focused provider CI.
"""
from __future__ import annotations

from pathlib import Path


PDF_INGESTION_PATH = Path("app/processing/pdf_ingestion.py")

_IMPORT_ANCHOR = "from app.storage.models import StorageReference\n"
_IMPORT_WITH_PREFLIGHT = (
    "from app.processing.pdf_provider_runtime_preflight import (\n"
    "    PdfProviderRuntimeConfigurationError,\n"
    "    validate_provider_runtime_configuration,\n"
    ")\n"
    + _IMPORT_ANCHOR
)

_STORAGE_ANCHOR = "    storage = get_storage_provider()\n"
_STORAGE_WITH_PREFLIGHT = '''    try:
        validate_provider_runtime_configuration(settings)
    except PdfProviderRuntimeConfigurationError as exc:
        status = exc.status
        _diagnostic(
            "PDF_PROVIDER_CONFIGURATION_INVALID",
            document_id=document_id,
            processing_attempt_id=ids.processing_attempt_id,
            base_url_configured=status.base_url_configured,
            bearer_token_configured=status.bearer_token_configured,
            public_origin_configured=status.public_origin_configured,
        )
        _set_document_terminal_state(
            document_id,
            status="failed",
            error_message=exc.safe_message,
        )
        sync_pdf_processing_run_terminal(
            processing_run_id=ids.processing_attempt_id,
            document_id=document_id,
        )
        return

    storage = get_storage_provider()
'''


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    if source.count(old) != 1:
        raise RuntimeError(f"Could not find unique {label} anchor")
    return source.replace(old, new, 1)


def patch_provider_runtime_preflight(
    path: Path = PDF_INGESTION_PATH,
) -> None:
    """Validate deployment configuration after run setup but before preprocessing."""
    source = path.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        _IMPORT_ANCHOR,
        _IMPORT_WITH_PREFLIGHT,
        "provider preflight import",
    )
    if "sync_pdf_processing_run_terminal" not in source:
        raise RuntimeError(
            "Provider runtime preflight must be applied after the S0 heartbeat overlay"
        )
    source = _replace_once(
        source,
        _STORAGE_ANCHOR,
        _STORAGE_WITH_PREFLIGHT,
        "provider preflight call",
    )
    path.write_text(source, encoding="utf-8")


def _presigned_lifecycle_installer():
    """Resolve the sibling installer for package import or direct CLI execution."""
    if __package__:
        from scripts.apply_provider_input_presigned_read import (
            patch_provider_input_presigned_read,
        )
    else:
        from apply_provider_input_presigned_read import (
            patch_provider_input_presigned_read,
        )
    return patch_provider_input_presigned_read


def main() -> None:
    patch_provider_runtime_preflight()

    # Staging CI invokes this script only after the heartbeat and sharding
    # overlays.  At that point install the complete provider-delivery lifecycle
    # into the same worktree that will be tested, archived, and deployed.
    _presigned_lifecycle_installer()()


if __name__ == "__main__":
    main()
