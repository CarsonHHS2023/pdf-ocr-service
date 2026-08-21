"""Expose the logical Provider poll count in the top-level terminal diagnostic."""
from __future__ import annotations

from pathlib import Path


INGESTION_PATH = Path("app/processing/pdf_ingestion.py")
TEST_REVIEW_PATH = Path("tests/test_provider_20mib_review_fixes.py")
TEST_DEPLOYMENT_PATH = Path("tests/test_staging_deployment_contract.py")


def _replace_once(source: str, old: str, new: str, *, label: str) -> str:
    count = source.count(old)
    if count == 0:
        if new in source:
            return source
        raise RuntimeError(f"{label}: source marker is missing")
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one source match, found {count}")
    return source.replace(old, new, 1)


def _patch_provider_terminal_poll_diagnostic() -> None:
    source = INGESTION_PATH.read_text(encoding="utf-8")
    old = '''            error_category=outcome.error.category.value if outcome.error is not None else None,\n            raw_result_retained=outcome.raw_result is not None,\n            canonicalization_ready=outcome.canonicalization is not None,\n'''
    new = '''            error_category=outcome.error.category.value if outcome.error is not None else None,\n            poll_count=outcome.poll_count,\n            raw_result_retained=outcome.raw_result is not None,\n            canonicalization_ready=outcome.canonicalization is not None,\n'''
    source = _replace_once(
        source,
        old,
        new,
        label="top-level provider terminal poll diagnostic",
    )
    INGESTION_PATH.write_text(source, encoding="utf-8")


def _append_focused_contract() -> None:
    source = TEST_REVIEW_PATH.read_text(encoding="utf-8")
    marker = "def test_provider_terminal_diagnostic_exposes_logical_poll_count()"
    if marker in source:
        return
    block = '''


def test_provider_terminal_diagnostic_exposes_logical_poll_count() -> None:
    import inspect
+
+    from app.processing import pdf_ingestion
+
+    processing = inspect.getsource(pdf_ingestion.process_pdf_document_background)
+    terminal_start = processing.index('"PDF_PROVIDER_TERMINAL"')
+    terminal_block = processing[terminal_start:terminal_start + 1600]
+    assert "poll_count=outcome.poll_count" in terminal_block
+'''.replace("\n+", "\n")
    TEST_REVIEW_PATH.write_text(source.rstrip() + block.rstrip() + "\n", encoding="utf-8")


def _append_deploy_contract() -> None:
    source = TEST_DEPLOYMENT_PATH.read_text(encoding="utf-8")
    marker = "def test_pr16_provider_terminal_exposes_aggregate_poll_count()"
    if marker in source:
        return
    block = '''


def test_pr16_provider_terminal_exposes_aggregate_poll_count() -> None:
    ingestion = (REPO_ROOT / "app" / "processing" / "pdf_ingestion.py").read_text(
        encoding="utf-8"
    )
    terminal_start = ingestion.index('"PDF_PROVIDER_TERMINAL"')
    terminal_block = ingestion[terminal_start:terminal_start + 1600]
    assert "poll_count=outcome.poll_count" in terminal_block
'''
    TEST_DEPLOYMENT_PATH.write_text(
        source.rstrip() + block.rstrip() + "\n",
        encoding="utf-8",
    )


def main() -> None:
    _patch_provider_terminal_poll_diagnostic()
    _append_focused_contract()
    _append_deploy_contract()
    print(
        "provider terminal poll diagnostic ready: "
        "PDF_PROVIDER_TERMINAL.poll_count=logical_outcome_poll_count"
    )


if __name__ == "__main__":
    main()
