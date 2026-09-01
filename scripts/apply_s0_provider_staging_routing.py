"""Compose the S0.3.3 exact-Staging Provider endpoint resolver."""
from __future__ import annotations

from pathlib import Path

PDF_INGESTION_PATH = Path("app/processing/pdf_ingestion.py")

_IMPORT_ANCHOR = "from app.config import settings\n"
_IMPORT_BLOCK = '''from app.config import settings\nfrom app.s0_provider_staging_routing import resolve_s0_provider_base_url\n'''

_CONFIG_ANCHOR = '''        _diagnostic(\n            "PDF_PROVIDER_CONFIGURATION",\n            document_id=document_id,\n            processing_attempt_id=ids.processing_attempt_id,\n            base_url_configured=bool(settings.paddle_vl_api_base_url),\n            bearer_token_configured=bool(settings.paddle_vl_api_bearer_token),\n            public_origin_configured=bool(settings.public_source_transport_origin),\n        )\n        client = PaddleVLClient(\n            PaddleVLClientConfig(\n                base_url=settings.paddle_vl_api_base_url or "",\n'''
_CONFIG_BLOCK = '''        provider_base_url = resolve_s0_provider_base_url(\n            settings.paddle_vl_api_base_url\n        )\n        _diagnostic(\n            "PDF_PROVIDER_CONFIGURATION",\n            document_id=document_id,\n            processing_attempt_id=ids.processing_attempt_id,\n            base_url_configured=bool(provider_base_url),\n            bearer_token_configured=bool(settings.paddle_vl_api_bearer_token),\n            public_origin_configured=bool(settings.public_source_transport_origin),\n        )\n        client = PaddleVLClient(\n            PaddleVLClientConfig(\n                base_url=provider_base_url,\n'''

_FINAL_MARKERS = (
    "from app.s0_provider_staging_routing import resolve_s0_provider_base_url",
    "provider_base_url = resolve_s0_provider_base_url(",
    "base_url=provider_base_url,",
)


def patch_pdf_ingestion(path: Path = PDF_INGESTION_PATH) -> None:
    source = path.read_text(encoding="utf-8")
    if all(marker in source for marker in _FINAL_MARKERS):
        return
    if any(marker in source for marker in _FINAL_MARKERS):
        raise RuntimeError("S0 Provider staging routing overlay is only partially installed")
    if source.count(_IMPORT_ANCHOR) != 1:
        raise RuntimeError("Could not find unique Atlas settings import anchor")
    if source.count(_CONFIG_ANCHOR) != 1:
        raise RuntimeError("Could not find unique Provider client configuration anchor")
    source = source.replace(_IMPORT_ANCHOR, _IMPORT_BLOCK, 1)
    source = source.replace(_CONFIG_ANCHOR, _CONFIG_BLOCK, 1)
    if not all(marker in source for marker in _FINAL_MARKERS):
        raise RuntimeError("S0 Provider staging routing overlay did not reach final contract")
    path.write_text(source, encoding="utf-8")


def main() -> None:
    patch_pdf_ingestion()


if __name__ == "__main__":
    main()
