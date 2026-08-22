"""Assign every non-heading multi-page node to one deterministic review batch."""
from __future__ import annotations

from pathlib import Path

BATCH_RUNTIME_PATH = Path("app/processing/batched_structure_refinement.py")
REGRESSION_TEST_PATH = Path("tests/test_staging_deployment_contract.py")

_IMPORT_ANCHOR = '''from app.processing.structured_result_v2.model import (\n'''
_IMPORT_REPLACEMENT = '''from app.processing.llm_structure_refinement_request import build_structure_refinement_request\nfrom app.processing.structured_result_v2.model import (\n'''

_SELECTED_NODES_ANCHOR = '''    selected_units = frozenset(source_unit_ids)\n    selected_nodes = tuple(\n        node\n        for node in spr.nodes\n        if selected_units.intersection(node.source_unit_ids)\n    )\n    selected_node_ids = frozenset(node.node_id for node in selected_nodes)\n'''
_SELECTED_NODES_REPLACEMENT = '''    selected_units = frozenset(source_unit_ids)\n\n    # Cost-aware batching creates more page boundaries than the historical\n    # page-count-only planner. A non-heading node spanning two selected pages\n    # must therefore have one deterministic owner batch or it can be proposed\n    # twice and conflict during patch merge. Heading pages are kept atomic by\n    # the planner, so headings continue to use their full page intersection.\n    full_request = build_structure_refinement_request(spr)\n    raw_page_reasons = full_request.get("page_selection_reasons") or {}\n    selected_review_units = frozenset(\n        str(source_unit_id)\n        for source_unit_id in raw_page_reasons\n    )\n    source_order = {\n        unit.source_unit_id: unit.source_order\n        for unit in spr.source_units\n    }\n\n    def review_owner_source_unit_id(node) -> str | None:\n        candidates = tuple(\n            source_unit_id\n            for source_unit_id in node.source_unit_ids\n            if source_unit_id in selected_review_units\n        )\n        if not candidates:\n            return None\n        return min(\n            candidates,\n            key=lambda source_unit_id: (\n                source_order.get(source_unit_id, 2**31),\n                source_unit_id,\n            ),\n        )\n\n    selected_nodes = tuple(\n        node\n        for node in spr.nodes\n        if selected_units.intersection(node.source_unit_ids)\n        and (\n            node.kind in _HEADING_KINDS\n            or review_owner_source_unit_id(node) in selected_units\n        )\n    )\n    selected_node_ids = frozenset(node.node_id for node in selected_nodes)\n'''
_MARKER = "def review_owner_source_unit_id(node) -> str | None:"

_REGRESSION_MARKER = (
    "def test_structure_refinement_shared_nonheading_node_has_one_owner_batch("
)
_REGRESSION_BLOCK = r'''


def test_structure_refinement_shared_nonheading_node_has_one_owner_batch() -> None:
    from collections import Counter

    import fitz

    from app.processing.batched_structure_refinement import _scoped_spr
    from app.processing.pdf_structure_refinement_images import (
        PdfPageImageBatchPlanner,
        PdfPageImagePolicy,
        _selected_source_unit_ids,
    )
    from app.processing.structured_result_v2.model import (
        ProcessingNode,
        ProcessingNodeKind,
        StructuredProcessingResultV2,
    )
    from app.processing.structured_result_v2.validation import validate_spr_v2
    from app.source_units import SourceUnit, SourceUnitDimensions, SourceUnitKind

    document = fitz.open()
    try:
        for index in range(2):
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
        for index in range(2)
    )
    spr = StructuredProcessingResultV2(
        document_ref="doc",
        processing_run_ref="run",
        source_units=units,
        observations=(),
        nodes=(
            ProcessingNode(
                "heading-1",
                ProcessingNodeKind.HEADING,
                0,
                ("page-1",),
                text="Heading 1",
                heading_level=1,
            ),
            ProcessingNode(
                "shared-paragraph",
                ProcessingNodeKind.PARAGRAPH,
                1,
                ("page-1", "page-2"),
                text="Paragraph spanning two selected pages",
            ),
            ProcessingNode(
                "heading-2",
                ProcessingNodeKind.HEADING,
                2,
                ("page-2",),
                text="Heading 2",
                heading_level=1,
            ),
        ),
    )

    batches = PdfPageImageBatchPlanner(
        pdf_bytes,
        policy=PdfPageImagePolicy(
            max_pages=1,
            max_headings=12,
            max_nodes=160,
        ),
    )(spr)
    flattened = [source_unit_id for batch in batches for source_unit_id in batch]
    assert sorted(flattened) == sorted(_selected_source_unit_ids(spr))
    assert len(batches) == 2

    node_counts = Counter()
    for batch in batches:
        scoped = _scoped_spr(spr, tuple(batch))
        validate_spr_v2(scoped)
        node_counts.update(node.node_id for node in scoped.nodes)

    assert node_counts == Counter(
        {
            "heading-1": 1,
            "heading-2": 1,
            "shared-paragraph": 1,
        }
    )
'''


def _replace_once(source: str, old: str, new: str, *, label: str) -> str:
    if new in source:
        return source
    if source.count(old) != 1:
        raise RuntimeError(f"Could not find unique {label} anchor")
    return source.replace(old, new, 1)


def _patch_runtime() -> None:
    source = BATCH_RUNTIME_PATH.read_text(encoding="utf-8")
    if _MARKER in source:
        return
    source = _replace_once(
        source,
        _IMPORT_ANCHOR,
        _IMPORT_REPLACEMENT,
        label="structure refinement request import",
    )
    source = _replace_once(
        source,
        _SELECTED_NODES_ANCHOR,
        _SELECTED_NODES_REPLACEMENT,
        label="batch shared-node ownership",
    )
    BATCH_RUNTIME_PATH.write_text(source, encoding="utf-8")


def _append_regression() -> None:
    source = REGRESSION_TEST_PATH.read_text(encoding="utf-8")
    if _REGRESSION_MARKER in source:
        return
    REGRESSION_TEST_PATH.write_text(
        source.rstrip() + "\n\n" + _REGRESSION_BLOCK.rstrip() + "\n",
        encoding="utf-8",
    )


def main() -> None:
    _patch_runtime()
    _append_regression()


if __name__ == "__main__":
    main()
