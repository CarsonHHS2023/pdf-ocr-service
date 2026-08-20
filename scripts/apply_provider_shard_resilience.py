"""Apply bounded Provider polling resilience and sharded failure observability."""
from __future__ import annotations

from pathlib import Path
import subprocess


PATCH_PATH = Path(__file__).with_name("provider-shard-resilience.patch")
_TARGETS = {
    Path("app/processing/orchestration.py"): (
        "_MAX_CONSECUTIVE_RETRYABLE_PROVIDER_POLL_ERRORS = 3",
        "PDF_PROVIDER_POLL_RETRY ",
    ),
    Path("app/processing/pdf_provider_sharding_compat.py"): (
        "provider_pages_completed",
        "print(message, file=sys.stderr, flush=True)",
    ),
    Path("app/processing/provider_input_source_access.py"): (
        "route=atlas_source_transport_fallback",
        "print(message, file=sys.stderr, flush=True)",
    ),
}


def _target_is_patched(path: Path, markers: tuple[str, ...]) -> bool:
    if not path.is_file():
        return False
    source = path.read_text(encoding="utf-8")
    return all(marker in source for marker in markers)


def patch_provider_shard_resilience() -> None:
    """Patch only post-submission polling and redacted sharding diagnostics.

    The patch deliberately does not alter the 1800-second production deadline,
    source/shard TTLs, sharding target/max bytes, Modal batch policy, provider
    submission semantics, cancellation, or shard concurrency.
    """
    if all(_target_is_patched(path, markers) for path, markers in _TARGETS.items()):
        return
    if not PATCH_PATH.is_file():
        raise RuntimeError(f"Provider shard resilience patch is missing: {PATCH_PATH}")

    check = subprocess.run(
        ["git", "apply", "--check", str(PATCH_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )
    if check.returncode != 0:
        detail = (check.stderr or check.stdout or "git apply --check failed").strip()
        raise RuntimeError(f"Provider shard resilience patch no longer applies cleanly: {detail}")

    subprocess.run(["git", "apply", str(PATCH_PATH)], check=True)
    missing = [
        str(path)
        for path, markers in _TARGETS.items()
        if not _target_is_patched(path, markers)
    ]
    if missing:
        raise RuntimeError(
            "Provider shard resilience patch completed without required markers: "
            + ", ".join(missing)
        )


def main() -> None:
    patch_provider_shard_resilience()


if __name__ == "__main__":
    main()
