"""Bound structure-refinement batch cost without shrinking review scope."""
from __future__ import annotations

from pathlib import Path

IMAGE_RUNTIME_PATH = Path("app/processing/pdf_structure_refinement_images.py")
REGRESSION_TEST_PATH = Path("tests/test_staging_deployment_contract.py")

_IMAGE_MODEL_IMPORT_ANCHOR = (
    "from app.processing.structured_result_v2.model import StructuredProcessingResultV2\n"
)
_IMAGE_MODEL_IMPORT_REPLACEMENT = (
    "from app.processing.structured_result_v2.model import (\n"
    "    ProcessingNodeKind,\n"
    "    StructuredProcessingResultV2,\n"
    ")\n"
)
_POLICY_FIELD_ANCHOR = '''class PdfPageImagePolicy:\n    max_pages: int = 16\n'''
_POLICY_FIELD_REPLACEMENT = '''class PdfPageImagePolicy:\n    max_pages: int = 16\n    max_headings: int = 12\n    max_nodes: int = 160\n'''
_POLICY_VALIDATION_ANCHOR = '''        if not isinstance(self.max_pages, int) or isinstance(self.max_pages, bool) or self.max_pages < 1:\n            raise ValueError("max_pages must be a positive integer")\n'''
_POLICY_VALIDATION_REPLACEMENT = '''        if not isinstance(self.max_pages, int) or isinstance(self.max_pages, bool) or self.max_pages < 1:\n            raise ValueError("max_pages must be a positive integer")\n        if not isinstance(self.max_headings, int) or isinstance(self.max_headings, bool) or self.max_headings < 1:\n            raise ValueError("max_headings must be a positive integer")\n        if not isinstance(self.max_nodes, int) or isinstance(self.max_nodes, bool) or self.max_nodes < 1:\n            raise ValueError("max_nodes must be a positive integer")\n'''
_POLICY_ENV_ANCHOR = '''        max_pages=_env_int("PDF_STRUCTURE_REFINEMENT_MAX_PAGES_PER_BATCH", 16),\n        max_dimension_pixels=_env_int("PDF_STRUCTURE_REFINEMENT_MAX_IMAGE_DIMENSION_PIXELS", 1400),\n'''
_POLICY_ENV_REPLACEMENT = '''        max_pages=_env_int("PDF_STRUCTURE_REFINEMENT_MAX_PAGES_PER_BATCH", 16),\n        max_headings=_env_int("PDF_STRUCTURE_REFINEMENT_MAX_HEADINGS_PER_BATCH", 12),\n        max_nodes=_env_int("PDF_STRUCTURE_REFINEMENT_MAX_NODES_PER_BATCH", 160),\n        max_dimension_pixels=_env_int("PDF_STRUCTURE_REFINEMENT_MAX_IMAGE_DIMENSION_PIXELS", 1400),\n'''
_PLANNER_METHOD_ANCHOR = '''    def __call__(self, spr: StructuredProcessingResultV2) -> Sequence[Mapping[str, str]]:\n        selected = _selected_source_unit_ids(spr)\n        batches: list[Mapping[str, str]] = []\n        for start in range(0, len(selected), self._policy.max_pages):\n            ids = selected[start : start + self._policy.max_pages]\n            resolver = PdfPageImageResolver(\n                self._pdf_bytes,\n                policy=self._policy,\n                source_unit_ids=ids,\n            )\n            batches.append(resolver(spr))\n        return tuple(batches)\n'''
_PLANNER_METHOD_REPLACEMENT = '''    def __call__(self, spr: StructuredProcessingResultV2) -> Sequence[Mapping[str, str]]:\n        selected = _selected_source_unit_ids(spr)\n        selected_set = frozenset(selected)\n        node_ids_by_unit = {source_unit_id: set() for source_unit_id in selected}\n        heading_ids_by_unit = {source_unit_id: set() for source_unit_id in selected}\n        for node in spr.nodes:\n            scoped_units = selected_set.intersection(node.source_unit_ids)\n            if not scoped_units:\n                continue\n            for source_unit_id in scoped_units:\n                node_ids_by_unit[source_unit_id].add(node.node_id)\n                if node.kind in {ProcessingNodeKind.TITLE, ProcessingNodeKind.HEADING}:\n                    heading_ids_by_unit[source_unit_id].add(node.node_id)\n\n        batches: list[Mapping[str, str]] = []\n        batch_ids: list[str] = []\n        batch_node_ids: set[str] = set()\n        batch_heading_ids: set[str] = set()\n\n        def flush() -> None:\n            nonlocal batch_ids, batch_node_ids, batch_heading_ids\n            if not batch_ids:\n                return\n            resolver = PdfPageImageResolver(\n                self._pdf_bytes,\n                policy=self._policy,\n                source_unit_ids=tuple(batch_ids),\n            )\n            batches.append(resolver(spr))\n            batch_ids = []\n            batch_node_ids = set()\n            batch_heading_ids = set()\n\n        for source_unit_id in selected:\n            next_node_ids = batch_node_ids.union(node_ids_by_unit[source_unit_id])\n            next_heading_ids = batch_heading_ids.union(\n                heading_ids_by_unit[source_unit_id]\n            )\n            would_exceed_budget = bool(batch_ids) and (\n                len(batch_ids) + 1 > self._policy.max_pages\n                or len(next_heading_ids) > self._policy.max_headings\n                or len(next_node_ids) > self._policy.max_nodes\n            )\n            if would_exceed_budget:\n                flush()\n                next_node_ids = set(node_ids_by_unit[source_unit_id])\n                next_heading_ids = set(heading_ids_by_unit[source_unit_id])\n\n            batch_ids.append(source_unit_id)\n            batch_node_ids = set(next_node_ids)\n            batch_heading_ids = set(next_heading_ids)\n\n        flush()\n        return tuple(batches)\n'''
_TIMEOUT_HELPER_ANCHOR = '''def openai_pdf_structure_refiner_from_env(\n'''
_TIMEOUT_HELPER = '''def _batch_execution_timeout_seconds(probe) -> float:\n    # Bound one full batch independently from one provider HTTP attempt. The\n    # outer budget covers the initial semantic request plus at most one targeted\n    # missing-heading repair, including each request's bounded provider retries.\n    retry_delay_budget = sum(\n        min(\n            probe.max_backoff_seconds,\n            probe.initial_backoff_seconds * (2 ** retry_index),\n        )\n        for retry_index in range(max(0, probe.max_attempts - 1))\n    )\n    one_semantic_request_budget = (\n        probe.timeout_seconds * probe.max_attempts + retry_delay_budget\n    )\n    return max(420.0, 2 * one_semantic_request_budget + 30.0)\n\n\n'''
_BATCH_TIMEOUT_ANCHOR = '''        batch_timeout_seconds=probe.timeout_seconds,\n'''
_BATCH_TIMEOUT_REPLACEMENT = '''        batch_timeout_seconds=_batch_execution_timeout_seconds(probe),\n'''
_BATCH_BUDGET_MARKER = "def _batch_execution_timeout_seconds(probe) -> float:"

_REGRESSION_MARKER = (
    "def test_structure_refinement_batch_budgeting_preserves_full_heading_scope("
)
_REGRESSION_BLOCK = r'''


def test_structure_refinement_batch_budgeting_preserves_full_heading_scope(
    monkeypatch,
) -> None:
    import fitz

    from app.processing.batched_structure_refinement import (
        _heading_candidate_ids,
        _scoped_spr,
    )
    from app.processing.pdf_structure_refinement_images import (
        PdfPageImageBatchPlanner,
        PdfPageImagePolicy,
        _selected_source_unit_ids,
        openai_pdf_structure_refiner_from_env,
        pdf_page_image_policy_from_env,
    )
    from app.processing.structured_result_v2.model import (
        ProcessingNode,
        ProcessingNodeKind,
        StructuredProcessingResultV2,
    )
    from app.source_units import SourceUnit, SourceUnitDimensions, SourceUnitKind

    page_count = 6
    document = fitz.open()
    try:
        for index in range(page_count):
            page = document.new_page(width=600, height=900)
            page.insert_text((72, 96), f"Page {index + 1}")
        pdf_bytes = document.tobytes()
    finally:
        document.close()

    units = tuple(
        SourceUnit(
            f"page-{index + 1}",
            SourceUnitKind.PHYSICAL_PAGE,
            index,
            "source",
            dimensions=SourceUnitDimensions(600, 900),
        )
        for index in range(page_count)
    )
    nodes = []
    for index, unit in enumerate(units):
        nodes.extend(
            (
                ProcessingNode(
                    f"heading-{index + 1}-a",
                    ProcessingNodeKind.HEADING,
                    index * 3,
                    (unit.source_unit_id,),
                    text=f"Heading {index + 1}A",
                    heading_level=2,
                ),
                ProcessingNode(
                    f"heading-{index + 1}-b",
                    ProcessingNodeKind.HEADING,
                    index * 3 + 1,
                    (unit.source_unit_id,),
                    text=f"Heading {index + 1}B",
                    heading_level=3,
                ),
                ProcessingNode(
                    f"paragraph-{index + 1}",
                    ProcessingNodeKind.PARAGRAPH,
                    index * 3 + 2,
                    (unit.source_unit_id,),
                    text=f"Paragraph {index + 1}",
                ),
            )
        )
    spr = StructuredProcessingResultV2(
        document_ref="doc",
        processing_run_ref="run",
        source_units=units,
        observations=(),
        nodes=tuple(nodes),
    )

    heading_limited = PdfPageImageBatchPlanner(
        pdf_bytes,
        policy=PdfPageImagePolicy(
            max_pages=16,
            max_headings=3,
            max_nodes=100,
        ),
    )(spr)
    flattened_pages = [
        source_unit_id for batch in heading_limited for source_unit_id in batch
    ]
    assert flattened_pages == _selected_source_unit_ids(spr)
    assert [len(batch) for batch in heading_limited] == [1] * page_count

    reviewed_heading_ids = set()
    for batch in heading_limited:
        scoped = _scoped_spr(spr, tuple(batch))
        reviewed_heading_ids.update(_heading_candidate_ids(scoped))
        assert len(_heading_candidate_ids(scoped)) <= 3
    assert reviewed_heading_ids == set(_heading_candidate_ids(spr))

    node_limited = PdfPageImageBatchPlanner(
        pdf_bytes,
        policy=PdfPageImagePolicy(
            max_pages=16,
            max_headings=100,
            max_nodes=4,
        ),
    )(spr)
    assert [source_unit_id for batch in node_limited for source_unit_id in batch] == (
        _selected_source_unit_ids(spr)
    )
    assert [len(batch) for batch in node_limited] == [1] * page_count

    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_MAX_HEADINGS_PER_BATCH", "12")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_MAX_NODES_PER_BATCH", "160")
    loaded_policy = pdf_page_image_policy_from_env()
    assert loaded_policy.max_headings == 12
    assert loaded_policy.max_nodes == 160

    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY", "secret")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_OPENAI_MODEL", "model")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_INITIAL_BACKOFF_SECONDS", "0.5")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_MAX_BACKOFF_SECONDS", "8")
    built = openai_pdf_structure_refiner_from_env(
        pdf_bytes,
        policy=PdfPageImagePolicy(max_pages=16, max_headings=12, max_nodes=160),
        global_semaphore=object(),
    )
    assert built is not None
    assert built.probe.timeout_seconds == 60.0
    assert built.batch_timeout_seconds == 420.0
    assert built.batch_timeout_seconds > built.probe.timeout_seconds
'''


def _replace_once(source: str, old: str, new: str, *, label: str) -> str:
    if new in source:
        return source
    if source.count(old) != 1:
        raise RuntimeError(f"Could not find unique {label} anchor")
    return source.replace(old, new, 1)


def _patch_batch_budgeting_and_timeout() -> None:
    source = IMAGE_RUNTIME_PATH.read_text(encoding="utf-8")
    if _BATCH_BUDGET_MARKER in source:
        return
    source = _replace_once(
        source,
        _IMAGE_MODEL_IMPORT_ANCHOR,
        _IMAGE_MODEL_IMPORT_REPLACEMENT,
        label="structure refinement model import",
    )
    source = _replace_once(
        source,
        _POLICY_FIELD_ANCHOR,
        _POLICY_FIELD_REPLACEMENT,
        label="batch cost policy fields",
    )
    source = _replace_once(
        source,
        _POLICY_VALIDATION_ANCHOR,
        _POLICY_VALIDATION_REPLACEMENT,
        label="batch cost policy validation",
    )
    source = _replace_once(
        source,
        _POLICY_ENV_ANCHOR,
        _POLICY_ENV_REPLACEMENT,
        label="batch cost policy environment",
    )
    source = _replace_once(
        source,
        _PLANNER_METHOD_ANCHOR,
        _PLANNER_METHOD_REPLACEMENT,
        label="cost-aware batch planner",
    )
    if source.count(_TIMEOUT_HELPER_ANCHOR) != 1:
        raise RuntimeError("Could not find unique batch timeout helper anchor")
    source = source.replace(
        _TIMEOUT_HELPER_ANCHOR,
        _TIMEOUT_HELPER + _TIMEOUT_HELPER_ANCHOR,
        1,
    )
    source = _replace_once(
        source,
        _BATCH_TIMEOUT_ANCHOR,
        _BATCH_TIMEOUT_REPLACEMENT,
        label="batch execution timeout wiring",
    )
    IMAGE_RUNTIME_PATH.write_text(source, encoding="utf-8")


def _append_regression() -> None:
    source = REGRESSION_TEST_PATH.read_text(encoding="utf-8")
    if _REGRESSION_MARKER in source:
        return
    REGRESSION_TEST_PATH.write_text(
        source.rstrip() + "\n\n" + _REGRESSION_BLOCK.rstrip() + "\n",
        encoding="utf-8",
    )


def main() -> None:
    _patch_batch_budgeting_and_timeout()
    _append_regression()


if __name__ == "__main__":
    main()
