"""Compose the S0.3.3 exact-Staging Provider endpoint resolver."""
from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Mapping

PDF_INGESTION_PATH = Path("app/processing/pdf_ingestion.py")
PROCESSING_OPERATOR_PATH = Path("app/routers/processing_operator.py")
STAGING_REVISION_PATH = Path("staging-revision.txt")
_AUTHORITATIVE_STAGING_WORKFLOW = "Staging Backend Integration CI"
_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")

_IMPORT_ANCHOR = "from app.config import settings\n"
_IMPORT_BLOCK = '''from app.config import settings\nfrom app.s0_provider_staging_routing import resolve_s0_provider_base_url\n'''

_PDF_CONFIG_ANCHOR = '''        _diagnostic(\n            "PDF_PROVIDER_CONFIGURATION",\n            document_id=document_id,\n            processing_attempt_id=ids.processing_attempt_id,\n            base_url_configured=bool(settings.paddle_vl_api_base_url),\n            bearer_token_configured=bool(settings.paddle_vl_api_bearer_token),\n            public_origin_configured=bool(settings.public_source_transport_origin),\n        )\n        client = PaddleVLClient(\n            PaddleVLClientConfig(\n                base_url=settings.paddle_vl_api_base_url or "",\n'''
_PDF_CONFIG_BLOCK = '''        provider_base_url = resolve_s0_provider_base_url(\n            settings.paddle_vl_api_base_url\n        )\n        _diagnostic(\n            "PDF_PROVIDER_CONFIGURATION",\n            document_id=document_id,\n            processing_attempt_id=ids.processing_attempt_id,\n            base_url_configured=bool(provider_base_url),\n            bearer_token_configured=bool(settings.paddle_vl_api_bearer_token),\n            public_origin_configured=bool(settings.public_source_transport_origin),\n        )\n        client = PaddleVLClient(\n            PaddleVLClientConfig(\n                base_url=provider_base_url,\n'''

_OPERATOR_CONFIG_ANCHOR = '''        config = PaddleVLClientConfig(\n            base_url=settings.paddle_vl_api_base_url or "",\n'''
_OPERATOR_CONFIG_BLOCK = '''        provider_base_url = resolve_s0_provider_base_url(\n            settings.paddle_vl_api_base_url\n        )\n        config = PaddleVLClientConfig(\n            base_url=provider_base_url,\n'''

_PDF_FINAL_MARKERS = (
    "from app.s0_provider_staging_routing import resolve_s0_provider_base_url",
    "provider_base_url = resolve_s0_provider_base_url(",
    "base_url=provider_base_url,",
)
_OPERATOR_FINAL_MARKERS = _PDF_FINAL_MARKERS


def ensure_authoritative_staging_revision_marker(
    *,
    revision_path: Path = STAGING_REVISION_PATH,
    env: Mapping[str, str] | None = None,
) -> bool:
    """Activate routed Staging semantics before contracts in the authoritative CI only."""
    values = os.environ if env is None else env
    if values.get("GITHUB_ACTIONS") != "true":
        return False
    if values.get("GITHUB_WORKFLOW") != _AUTHORITATIVE_STAGING_WORKFLOW:
        return False
    revision = str(values.get("GITHUB_SHA") or "").strip()
    if _REVISION_RE.fullmatch(revision) is None:
        raise RuntimeError("Authoritative Staging CI has an invalid GITHUB_SHA")
    if revision_path.exists():
        existing = revision_path.read_text(encoding="utf-8").strip()
        if existing != revision:
            raise RuntimeError("Existing Staging revision marker disagrees with GITHUB_SHA")
        return True
    revision_path.write_text(revision + "\n", encoding="utf-8")
    return True


def _patch_provider_client(
    path: Path,
    *,
    config_anchor: str,
    config_block: str,
    final_markers: tuple[str, ...],
    label: str,
) -> None:
    source = path.read_text(encoding="utf-8")
    if all(marker in source for marker in final_markers):
        return
    if any(marker in source for marker in final_markers):
        raise RuntimeError(f"S0 Provider staging routing overlay is only partially installed in {label}")
    if source.count(_IMPORT_ANCHOR) != 1:
        raise RuntimeError(f"Could not find unique Atlas settings import anchor in {label}")
    if source.count(config_anchor) != 1:
        raise RuntimeError(f"Could not find unique Provider client configuration anchor in {label}")
    source = source.replace(_IMPORT_ANCHOR, _IMPORT_BLOCK, 1)
    source = source.replace(config_anchor, config_block, 1)
    if not all(marker in source for marker in final_markers):
        raise RuntimeError(f"S0 Provider staging routing overlay did not reach final contract in {label}")
    path.write_text(source, encoding="utf-8")


def patch_pdf_ingestion(path: Path = PDF_INGESTION_PATH) -> None:
    _patch_provider_client(
        path,
        config_anchor=_PDF_CONFIG_ANCHOR,
        config_block=_PDF_CONFIG_BLOCK,
        final_markers=_PDF_FINAL_MARKERS,
        label="pdf_ingestion",
    )


def patch_processing_operator(path: Path = PROCESSING_OPERATOR_PATH) -> None:
    _patch_provider_client(
        path,
        config_anchor=_OPERATOR_CONFIG_ANCHOR,
        config_block=_OPERATOR_CONFIG_BLOCK,
        final_markers=_OPERATOR_FINAL_MARKERS,
        label="processing_operator",
    )


def main() -> None:
    # This installer runs inside the authoritative Staging workflow's overlay step.
    # Create the same exact revision marker that is packaged later so every runtime
    # contract exercises the routed configuration that will actually be deployed.
    ensure_authoritative_staging_revision_marker()
    patch_pdf_ingestion()
    patch_processing_operator()


if __name__ == "__main__":
    main()
