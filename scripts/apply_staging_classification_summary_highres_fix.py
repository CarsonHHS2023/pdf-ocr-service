"""Count high-resolution-confirmed presentation pages in bounded diagnostics.

Staging-only follow-up after the 11-page Baseline regression smoke. The runtime
routing is already correct; this overlay changes only the classification summary
diagnostic so it recognizes both the legacy and high-resolution presentation
success reasons.
"""
from __future__ import annotations

from pathlib import Path


CLASSIFICATION_OBSERVABILITY_PATH = Path(
    "app/processing/pdf_page_classification_observability_compat.py"
)

_OLD_PRESENTATION_SUMMARY_RULE = '''        elif skip_ocr and decision_reason == "presentation_page_confirmed":\n            presentation_page_count += 1\n'''
_NEW_PRESENTATION_SUMMARY_RULE = '''        elif skip_ocr and decision_reason in {\n            "presentation_page_confirmed",\n            "presentation_page_high_resolution_confirmed",\n        }:\n            presentation_page_count += 1\n'''


def main() -> None:
    source = CLASSIFICATION_OBSERVABILITY_PATH.read_text(encoding="utf-8")
    if _NEW_PRESENTATION_SUMMARY_RULE in source:
        print("staging classification summary high-resolution fix already installed: no changes")
        return

    count = source.count(_OLD_PRESENTATION_SUMMARY_RULE)
    if count != 1:
        raise RuntimeError(
            "classification presentation summary rule: expected exactly one source match, "
            f"found {count}"
        )

    source = source.replace(
        _OLD_PRESENTATION_SUMMARY_RULE,
        _NEW_PRESENTATION_SUMMARY_RULE,
        1,
    )
    CLASSIFICATION_OBSERVABILITY_PATH.write_text(source, encoding="utf-8")
    print("installed staging classification summary high-resolution fix")


if __name__ == "__main__":
    main()
