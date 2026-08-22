"""Count high-resolution-confirmed presentation pages in bounded diagnostics.

Staging-only follow-up after the 11-page Baseline regression smoke. The runtime
routing is already correct; this overlay changes only the classification summary
diagnostic so it recognizes both the legacy and high-resolution presentation
success reasons. It also appends an authoritative deployment-contract regression
that exercises the composed runtime summary.
"""
from __future__ import annotations

from pathlib import Path


CLASSIFICATION_OBSERVABILITY_PATH = Path(
    "app/processing/pdf_page_classification_observability_compat.py"
)
DEPLOYMENT_TEST_PATH = Path("tests/test_staging_deployment_contract.py")

_OLD_PRESENTATION_SUMMARY_RULE = '''        elif skip_ocr and decision_reason == "presentation_page_confirmed":\n            presentation_page_count += 1\n'''
_NEW_PRESENTATION_SUMMARY_RULE = '''        elif skip_ocr and decision_reason in {\n            "presentation_page_confirmed",\n            "presentation_page_high_resolution_confirmed",\n        }:\n            presentation_page_count += 1\n'''
_DEPLOYMENT_TEST_MARKER = (
    "def test_classification_summary_counts_high_resolution_presentation_routes("
)
_DEPLOYMENT_TEST_BLOCK = r'''


def test_classification_summary_counts_high_resolution_presentation_routes(monkeypatch) -> None:
    from app.processing import pdf_page_classification_observability_compat as classification_obs
    from app.processing import pdf_page_presentation_bridge as bridge

    def decision(
        page_number: int,
        *,
        reason: str,
        skip_ocr: bool,
        native_text: bool = False,
        role: str = "body",
    ) -> dict[str, object]:
        return {
            "page_number": page_number,
            "source_unit_id": f"pdf-page:{page_number:06d}",
            "candidate": True,
            "classification": {
                "page_role": role,
                "confidence": 0.99,
                "provider": "openai",
                "model_id": "test-model",
                "cache_hit": False,
                "reason_codes": [],
            },
            "skip_ocr": skip_ocr,
            "native_text_accepted": native_text,
            "decision_reason": reason,
        }

    decisions = [
        decision(
            1,
            reason="presentation_page_high_resolution_confirmed",
            skip_ocr=True,
            role="cover",
        ),
        *[
            decision(page_number, reason="role_not_presentation", skip_ocr=False)
            for page_number in range(2, 7)
        ],
        decision(
            7,
            reason="local_dense_text_visual_conflict",
            skip_ocr=False,
            role="full_page_chart",
        ),
        decision(
            8,
            reason="presentation_page_high_resolution_confirmed",
            skip_ocr=True,
            role="chapter_divider",
        ),
        decision(
            9,
            reason="native_pdf_text_accepted",
            skip_ocr=True,
            native_text=True,
        ),
        decision(10, reason="role_not_presentation", skip_ocr=False),
        decision(
            11,
            reason="presentation_page_high_resolution_confirmed",
            skip_ocr=True,
            role="back_cover",
        ),
    ]

    diagnostics: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        bridge,
        "_diagnostic",
        lambda event, **fields: diagnostics.append((event, fields)),
    )
    classification_obs._emit_summary(decisions)
    summary = next(
        fields
        for event, fields in diagnostics
        if event == "PDF_PAGE_CLASSIFICATION_SUMMARY"
    )

    assert summary["presentation_page_count"] == 3
    assert summary["native_text_page_count"] == 1
    assert summary["provider_page_count"] == 7
    assert summary["excluded_from_provider_count"] == 4
'''


def _patch_runtime_summary() -> bool:
    source = CLASSIFICATION_OBSERVABILITY_PATH.read_text(encoding="utf-8")
    if _NEW_PRESENTATION_SUMMARY_RULE in source:
        return False

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
    return True


def _append_deployment_regression() -> bool:
    source = DEPLOYMENT_TEST_PATH.read_text(encoding="utf-8")
    if _DEPLOYMENT_TEST_MARKER in source:
        return False
    DEPLOYMENT_TEST_PATH.write_text(
        source.rstrip() + _DEPLOYMENT_TEST_BLOCK + "\n",
        encoding="utf-8",
    )
    return True


def main() -> None:
    runtime_changed = _patch_runtime_summary()
    test_changed = _append_deployment_regression()
    if runtime_changed or test_changed:
        print(
            "installed staging classification summary high-resolution fix "
            f"runtime_changed={runtime_changed} test_changed={test_changed}"
        )
    else:
        print("staging classification summary high-resolution fix already installed: no changes")


if __name__ == "__main__":
    main()
