"""Staging-only Provider endpoint resolution for S0.3.3 acceptance.

The public Provider preview URL is used only by an exact Atlas Staging artifact,
proved by the workflow-generated ``staging-revision.txt`` marker. Production and
ordinary local/runtime artifacts keep the configured Provider base URL unchanged.
No credential is stored here.
"""
from __future__ import annotations

from pathlib import Path
import re

S0_PROVIDER_STAGING_BASE_URL = (
    "https://carsonhhs2023--paddle-vl-api-s0-staging-fastapi-app.modal.run"
)
STAGING_REVISION_PATH = Path("staging-revision.txt")
_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")


def exact_staging_artifact(
    revision_path: Path = STAGING_REVISION_PATH,
) -> bool:
    """Return true only for the exact tested Staging artifact marker contract."""
    try:
        revision = revision_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return False
    return _REVISION_RE.fullmatch(revision) is not None


def resolve_s0_provider_base_url(
    configured_base_url: str | None,
    *,
    revision_path: Path = STAGING_REVISION_PATH,
) -> str:
    """Resolve the Provider endpoint without changing non-Staging behavior."""
    if exact_staging_artifact(revision_path):
        return S0_PROVIDER_STAGING_BASE_URL
    return str(configured_base_url or "")


__all__ = [
    "S0_PROVIDER_STAGING_BASE_URL",
    "STAGING_REVISION_PATH",
    "exact_staging_artifact",
    "resolve_s0_provider_base_url",
]
