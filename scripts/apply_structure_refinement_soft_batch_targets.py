"""Name heading/node batch budgets as soft targets, not hard atomic limits."""
from __future__ import annotations

from pathlib import Path

IMAGE_RUNTIME_PATH = Path("app/processing/pdf_structure_refinement_images.py")
REGRESSION_TEST_PATH = Path("tests/test_staging_deployment_contract.py")

_RUNTIME_REPLACEMENTS = (
    ("max_headings: int = 12", "target_headings: int = 12"),
    ("max_nodes: int = 160", "target_nodes: int = 160"),
    ("self.max_headings", "self.target_headings"),
    ("self.max_nodes", "self.target_nodes"),
    ("max_headings must be a positive integer", "target_headings must be a positive integer"),
    ("max_nodes must be a positive integer", "target_nodes must be a positive integer"),
    ("max_headings=_env_int(\"PDF_STRUCTURE_REFINEMENT_MAX_HEADINGS_PER_BATCH\", 12)", "target_headings=_env_int(\"PDF_STRUCTURE_REFINEMENT_TARGET_HEADINGS_PER_BATCH\", 12)"),
    ("max_nodes=_env_int(\"PDF_STRUCTURE_REFINEMENT_MAX_NODES_PER_BATCH\", 160)", "target_nodes=_env_int(\"PDF_STRUCTURE_REFINEMENT_TARGET_NODES_PER_BATCH\", 160)"),
    ("self._policy.max_headings", "self._policy.target_headings"),
    ("self._policy.max_nodes", "self._policy.target_nodes"),
)

_TEST_REPLACEMENTS = (
    ("max_headings=", "target_headings="),
    ("max_nodes=", "target_nodes="),
    ("PDF_STRUCTURE_REFINEMENT_MAX_HEADINGS_PER_BATCH", "PDF_STRUCTURE_REFINEMENT_TARGET_HEADINGS_PER_BATCH"),
    ("PDF_STRUCTURE_REFINEMENT_MAX_NODES_PER_BATCH", "PDF_STRUCTURE_REFINEMENT_TARGET_NODES_PER_BATCH"),
    ("loaded_policy.max_headings", "loaded_policy.target_headings"),
    ("loaded_policy.max_nodes", "loaded_policy.target_nodes"),
)

_RUNTIME_MARKER = "target_headings: int = 12"
_REGRESSION_MARKER = (
    "def test_structure_refinement_atomic_group_may_exceed_soft_heading_target("
)
_REGRESSION_BLOCK = r'''


def test_structure_refinement_atomic_group_may_exceed_soft_heading_target() -> None:
    import fitz

    from app.processing.batched_structure_refinement import (
        _heading_candidate_ids,
        _scoped_spr,
    )
    from app.processing.pdf_structure_refinement_images import (
        PdfPageImageBatchPlanner,
        PdfPageImagePolicy,
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
        page = document.new_page(width=600, height=900)
        page.insert_text((72, 96), "Dense heading page")
        pdf_bytes = document.tobytes()
    finally:
        document.close()

    unit = SourceUnit(
        "page-1",
        SourceUnitKind.PHYSICAL_PAGE,
        0,
        "source",
        dimensions=SourceUnitDimensions(600, 900),
    )
    headings = tuple(
        ProcessingNode(
            f"heading-{index}",
            ProcessingNodeKind.HEADING,
            index,
            ("page-1",),
            text=f"Heading {index}",
            heading_level=2,
        )
        for index in range(13)
    )
    spr = StructuredProcessingResultV2(
        document_ref="doc",
        processing_run_ref="run",
        source_units=(unit,),
        observations=(),
        nodes=headings,
    )

    policy = PdfPageImagePolicy(
        max_pages=16,
        target_headings=12,
        target_nodes=160,
    )
    batches = PdfPageImageBatchPlanner(pdf_bytes, policy=policy)(spr)
    assert len(batches) == 1
    assert tuple(batches[0]) == ("page-1",)

    scoped = _scoped_spr(spr, tuple(batches[0]))
    validate_spr_v2(scoped)
    assert len(_heading_candidate_ids(scoped)) == 13
    assert set(_heading_candidate_ids(scoped)) == {
        node.node_id for node in headings
    }
'''


def _replace_required(source: str, old: str, new: str, *, label: str) -> str:
    if old not in source:
        if new in source:
            return source
        raise RuntimeError(f"Could not find {label} anchor")
    return source.replace(old, new)


def _patch_runtime() -> None:
    source = IMAGE_RUNTIME_PATH.read_text(encoding="utf-8")
    if _RUNTIME_MARKER in source:
        return
    for old, new in _RUNTIME_REPLACEMENTS:
        source = _replace_required(source, old, new, label=old)
    IMAGE_RUNTIME_PATH.write_text(source, encoding="utf-8")


def _patch_tests() -> None:
    source = REGRESSION_TEST_PATH.read_text(encoding="utf-8")
    for old, new in _TEST_REPLACEMENTS:
        source = source.replace(old, new)
    if _REGRESSION_MARKER not in source:
        source = source.rstrip() + "\n\n" + _REGRESSION_BLOCK.rstrip() + "\n"
    REGRESSION_TEST_PATH.write_text(source, encoding="utf-8")


def main() -> None:
    _patch_runtime()
    _patch_tests()


if __name__ == "__main__":
    main()
