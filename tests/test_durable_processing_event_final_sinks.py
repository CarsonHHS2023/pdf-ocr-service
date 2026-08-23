from __future__ import annotations

import ast
from pathlib import Path

from scripts import apply_durable_processing_events as durable_overlay


def _event_set_from_diagnostic(source: str) -> set[str]:
    parsed = ast.parse(source)
    diagnostic = next(
        node
        for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name == "_diagnostic"
    )
    for node in ast.walk(diagnostic):
        if not isinstance(node, ast.Compare):
            continue
        if not isinstance(node.left, ast.Name) or node.left.id != "event":
            continue
        if len(node.ops) != 1 or not isinstance(node.ops[0], ast.In):
            continue
        if len(node.comparators) != 1 or not isinstance(node.comparators[0], ast.Set):
            continue
        return {
            element.value
            for element in node.comparators[0].elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        }
    raise AssertionError("durable classification event set was not found")


def test_final_classification_sink_persists_only_config_and_summary(tmp_path: Path) -> None:
    path = tmp_path / "pdf_page_classification_observability_compat.py"
    path.write_text(
        '''from __future__ import annotations

import logging
import sys

from app.processing import pdf_page_presentation_preprocess_compat as preprocess

_logger = logging.getLogger(__name__)


def _diagnostic(event: str, **fields: object) -> None:
    """Emit one safe bounded event to both logger and runtime stderr."""
    payload = " ".join(f"{name}={value}" for name, value in fields.items())
    message = f"{event} {payload}".rstrip()
    _logger.info(message)
    print(message, file=sys.stderr, flush=True)
''',
        encoding="utf-8",
    )

    durable_overlay._patch_classification_observability_timeline(path)
    first = path.read_text(encoding="utf-8")

    assert (
        "from app.processing.processing_events import record_processing_event\n"
        in first
    )
    assert _event_set_from_diagnostic(first) == {
        "PDF_PAGE_CLASSIFICATION_CONFIG",
        "PDF_PAGE_CLASSIFICATION_SUMMARY",
    }
    assert first.count("record_processing_event(") == 1
    compile(first, str(path), "exec")

    durable_overlay._patch_classification_observability_timeline(path)
    assert path.read_text(encoding="utf-8") == first


def test_raw_source_without_result_stage_failures_is_noop(tmp_path: Path) -> None:
    path = tmp_path / "pdf_page_presentation_bridge.py"
    original = '''def _diagnostic(event: str, **fields: object) -> None:
    return None


def process(provider_input):
    _diagnostic("PDF_PROVIDER_PAGE_MAP_CREATED", page_count=1)
'''
    path.write_text(original, encoding="utf-8")

    durable_overlay._patch_provider_result_stage_failure_correlation(path)
    assert path.read_text(encoding="utf-8") == original

    durable_overlay._patch_provider_result_stage_failure_correlation(path)
    assert path.read_text(encoding="utf-8") == original


def test_all_provider_result_stage_failures_gain_processing_correlation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "pdf_page_presentation_bridge.py"
    path.write_text(
        '''def _diagnostic(event: str, **fields: object) -> None:
    return None


def process(provider_input):
    _diagnostic(
        "PDF_PROVIDER_RESULT_STAGE_FAILED",
        stage="fetch",
        error_type="RuntimeError",
    )
    _diagnostic(
        "PDF_PROVIDER_RESULT_STAGE_FAILED",
        stage="page_remap",
        error_type="RuntimeError",
    )
    _diagnostic(
        "PDF_PROVIDER_RESULT_STAGE_FAILED",
        stage="canonicalize",
        error_type="RuntimeError",
    )
''',
        encoding="utf-8",
    )

    durable_overlay._patch_provider_result_stage_failure_correlation(path)
    first = path.read_text(encoding="utf-8")
    parsed = ast.parse(first)
    calls = [
        node
        for node in ast.walk(parsed)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_diagnostic"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "PDF_PROVIDER_RESULT_STAGE_FAILED"
    ]

    assert len(calls) == 3
    for call in calls:
        correlation = next(
            keyword.value
            for keyword in call.keywords
            if keyword.arg == "processing_attempt_id"
        )
        assert ast.unparse(correlation) == "provider_input.processing_attempt_id"

    durable_overlay._patch_provider_result_stage_failure_correlation(path)
    assert path.read_text(encoding="utf-8") == first
