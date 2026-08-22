"""Keep multi-page headings atomic across structure-refinement review batches."""
from __future__ import annotations

from pathlib import Path

IMAGE_RUNTIME_PATH = Path("app/processing/pdf_structure_refinement_images.py")
REGRESSION_TEST_PATH = Path("tests/test_staging_deployment_contract.py")

_PLANNER_ANCHOR = '''    def __call__(self, spr: StructuredProcessingResultV2) -> Sequence[Mapping[str, str]]:\n        selected = _selected_source_unit_ids(spr)\n        selected_set = frozenset(selected)\n        node_ids_by_unit = {source_unit_id: set() for source_unit_id in selected}\n        heading_ids_by_unit = {source_unit_id: set() for source_unit_id in selected}\n        for node in spr.nodes:\n            scoped_units = selected_set.intersection(node.source_unit_ids)\n            if not scoped_units:\n                continue\n            for source_unit_id in scoped_units:\n                node_ids_by_unit[source_unit_id].add(node.node_id)\n                if node.kind in {ProcessingNodeKind.TITLE, ProcessingNodeKind.HEADING}:\n                    heading_ids_by_unit[source_unit_id].add(node.node_id)\n\n        batches: list[Mapping[str, str]] = []\n        batch_ids: list[str] = []\n        batch_node_ids: set[str] = set()\n        batch_heading_ids: set[str] = set()\n\n        def flush() -> None:\n            nonlocal batch_ids, batch_node_ids, batch_heading_ids\n            if not batch_ids:\n                return\n            resolver = PdfPageImageResolver(\n                self._pdf_bytes,\n                policy=self._policy,\n                source_unit_ids=tuple(batch_ids),\n            )\n            batches.append(resolver(spr))\n            batch_ids = []\n            batch_node_ids = set()\n            batch_heading_ids = set()\n\n        for source_unit_id in selected:\n            next_node_ids = batch_node_ids.union(node_ids_by_unit[source_unit_id])\n            next_heading_ids = batch_heading_ids.union(\n                heading_ids_by_unit[source_unit_id]\n            )\n            would_exceed_budget = bool(batch_ids) and (\n                len(batch_ids) + 1 > self._policy.max_pages\n                or len(next_heading_ids) > self._policy.max_headings\n                or len(next_node_ids) > self._policy.max_nodes\n            )\n            if would_exceed_budget:\n                flush()\n                next_node_ids = set(node_ids_by_unit[source_unit_id])\n                next_heading_ids = set(heading_ids_by_unit[source_unit_id])\n\n            batch_ids.append(source_unit_id)\n            batch_node_ids = set(next_node_ids)\n            batch_heading_ids = set(next_heading_ids)\n\n        flush()\n        return tuple(batches)\n'''

_PLANNER_REPLACEMENT = '''    def __call__(self, spr: StructuredProcessingResultV2) -> Sequence[Mapping[str, str]]:\n        selected = _selected_source_unit_ids(spr)\n        selected_set = frozenset(selected)\n        node_ids_by_unit = {source_unit_id: set() for source_unit_id in selected}\n        heading_ids_by_unit = {source_unit_id: set() for source_unit_id in selected}\n\n        # A TITLE/HEADING can legally reference more than one source page. Those\n        # pages must stay in one first-pass review batch or the same mandatory\n        # heading would be reviewed more than once. Union only heading-linked\n        # pages; non-heading multi-page nodes do not widen mandatory review scope.\n        parent = {source_unit_id: source_unit_id for source_unit_id in selected}\n\n        def find(source_unit_id: str) -> str:\n            root = source_unit_id\n            while parent[root] != root:\n                root = parent[root]\n            while parent[source_unit_id] != source_unit_id:\n                next_id = parent[source_unit_id]\n                parent[source_unit_id] = root\n                source_unit_id = next_id\n            return root\n\n        def union(left: str, right: str) -> None:\n            left_root = find(left)\n            right_root = find(right)\n            if left_root != right_root:\n                parent[right_root] = left_root\n\n        for node in spr.nodes:\n            scoped_units = tuple(\n                source_unit_id\n                for source_unit_id in node.source_unit_ids\n                if source_unit_id in selected_set\n            )\n            if not scoped_units:\n                continue\n            for source_unit_id in scoped_units:\n                node_ids_by_unit[source_unit_id].add(node.node_id)\n                if node.kind in {ProcessingNodeKind.TITLE, ProcessingNodeKind.HEADING}:\n                    heading_ids_by_unit[source_unit_id].add(node.node_id)\n            if (\n                node.kind in {ProcessingNodeKind.TITLE, ProcessingNodeKind.HEADING}\n                and len(scoped_units) > 1\n            ):\n                first = scoped_units[0]\n                for source_unit_id in scoped_units[1:]:\n                    union(first, source_unit_id)\n\n        group_ids_by_root: dict[str, list[str]] = {}\n        for source_unit_id in selected:\n            group_ids_by_root.setdefault(find(source_unit_id), []).append(\n                source_unit_id\n            )\n\n        batches: list[Mapping[str, str]] = []\n        batch_ids: list[str] = []\n        batch_node_ids: set[str] = set()\n        batch_heading_ids: set[str] = set()\n        consumed_source_unit_ids: set[str] = set()\n\n        def flush() -> None:\n            nonlocal batch_ids, batch_node_ids, batch_heading_ids\n            if not batch_ids:\n                return\n            resolver = PdfPageImageResolver(\n                self._pdf_bytes,\n                policy=self._policy,\n                source_unit_ids=tuple(batch_ids),\n            )\n            batches.append(resolver(spr))\n            batch_ids = []\n            batch_node_ids = set()\n            batch_heading_ids = set()\n\n        for source_unit_id in selected:\n            if source_unit_id in consumed_source_unit_ids:\n                continue\n            group_ids = tuple(group_ids_by_root[find(source_unit_id)])\n            if len(group_ids) > self._policy.max_pages:\n                raise ValueError(\n                    "heading-connected page group exceeds max_pages and cannot "\n                    "be split without duplicating mandatory heading review"\n                )\n            group_node_ids = {\n                node_id\n                for group_source_unit_id in group_ids\n                for node_id in node_ids_by_unit[group_source_unit_id]\n            }\n            group_heading_ids = {\n                heading_id\n                for group_source_unit_id in group_ids\n                for heading_id in heading_ids_by_unit[group_source_unit_id]\n            }\n            next_node_ids = batch_node_ids.union(group_node_ids)\n            next_heading_ids = batch_heading_ids.union(group_heading_ids)\n            would_exceed_budget = bool(batch_ids) and (\n                len(batch_ids) + len(group_ids) > self._policy.max_pages\n                or len(next_heading_ids) > self._policy.max_headings\n                or len(next_node_ids) > self._policy.max_nodes\n            )\n            if would_exceed_budget:\n                flush()\n                next_node_ids = set(group_node_ids)\n                next_heading_ids = set(group_heading_ids)\n\n            batch_ids.extend(group_ids)\n            batch_node_ids = set(next_node_ids)\n            batch_heading_ids = set(next_heading_ids)\n            consumed_source_unit_ids.update(group_ids)\n\n        flush()\n        return tuple(batches)\n'''

_MARKER = "group_ids_by_root: dict[str, list[str]] = {}"
_REGRESSION_MARKER = (
    "def test_structure_refinement_multpage_heading_is_reviewed_exactly_once("
)
_REGRESSION_BLOCK = r'''


def test_structure_refinement_multpage_heading_is_reviewed_exactly_once() -> None:
    from collections import Counter

    import fitz

    from app.processing.batched_structure_refinement import (
        _heading_candidate_ids,
        _scoped_spr,
    )
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
        for index in range(3):
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
        for index in range(3)
    )
    spr = StructuredProcessingResultV2(
        document_ref="doc",
        processing_run_ref="run",
        source_units=units,
        observations=(),
        nodes=(
            ProcessingNode(
                "heading-spanning",
                ProcessingNodeKind.HEADING,
                0,
                ("page-1", "page-2"),
                text="Spanning heading",
                heading_level=1,
            ),
            ProcessingNode(
                "heading-last",
                ProcessingNodeKind.HEADING,
                1,
                ("page-3",),
                text="Last heading",
                heading_level=1,
            ),
        ),
    )

    planner = PdfPageImageBatchPlanner(
        pdf_bytes,
        policy=PdfPageImagePolicy(
            max_pages=2,
            max_headings=1,
            max_nodes=10,
        ),
    )
    batches = planner(spr)
    flattened = [source_unit_id for batch in batches for source_unit_id in batch]
    selected = _selected_source_unit_ids(spr)
    assert sorted(flattened) == sorted(selected)
    assert len(flattened) == len(set(flattened)) == len(selected)
    assert any(set(batch) == {"page-1", "page-2"} for batch in batches)

    reviewed = Counter()
    for batch in batches:
        scoped = _scoped_spr(spr, tuple(batch))
        validate_spr_v2(scoped)
        reviewed.update(_heading_candidate_ids(scoped))
    assert reviewed == Counter(
        {
            "heading-spanning": 1,
            "heading-last": 1,
        }
    )
'''


def _replace_once(source: str, old: str, new: str, *, label: str) -> str:
    if new in source:
        return source
    if source.count(old) != 1:
        raise RuntimeError(f"Could not find unique {label} anchor")
    return source.replace(old, new, 1)


def _patch_planner() -> None:
    source = IMAGE_RUNTIME_PATH.read_text(encoding="utf-8")
    if _MARKER in source:
        return
    source = _replace_once(
        source,
        _PLANNER_ANCHOR,
        _PLANNER_REPLACEMENT,
        label="cost-aware structure refinement batch planner",
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
    _patch_planner()
    _append_regression()


if __name__ == "__main__":
    main()
