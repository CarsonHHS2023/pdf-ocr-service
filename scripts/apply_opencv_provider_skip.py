from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"{label} anchor not found")
    return text.replace(old, new, 1)


def main() -> None:
    path = Path("app/processing/pdf_ingestion.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "import logging\nimport sys\n",
        "import logging\nimport os\nimport sys\n",
        "os import",
    )
    anchor = '''        _diagnostic(\n            "PDF_PROVIDER_CONFIGURATION",'''
    replacement = '''        if os.environ.get(\n            "PDF_OPENCV_EXPERIMENT_SKIP_PROVIDER",\n            "1",\n        ).strip().lower() in {"1", "true", "yes", "on"}:\n            geometry_cleanup_allowed = True\n            _diagnostic(\n                "PDF_PROVIDER_SKIPPED",\n                document_id=document_id,\n                processing_attempt_id=ids.processing_attempt_id,\n                provider_job_id=ids.provider_job_id,\n                reason="opencv_visual_experiment",\n            )\n            _set_document_terminal_state(\n                document_id,\n                status="completed",\n                error_message=None,\n            )\n            _diagnostic(\n                "PDF_INGESTION_EXPERIMENT_COMPLETED",\n                document_id=document_id,\n                processing_attempt_id=ids.processing_attempt_id,\n                preprocessing_version=geometry_input.preprocessing.version,\n                changed_page_count=geometry_input.preprocessing.changed_page_count,\n            )\n            return\n\n        _diagnostic(\n            "PDF_PROVIDER_CONFIGURATION",'''
    text = replace_once(text, anchor, replacement, "provider configuration")
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
