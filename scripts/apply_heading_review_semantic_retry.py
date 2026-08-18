"""Retry one semantically incomplete mandatory heading-review batch once."""
from __future__ import annotations

from pathlib import Path


def _replace_once(path: Path, old: str, new: str, *, label: str) -> None:
    source = path.read_text(encoding="utf-8")
    if new in source:
        return
    if source.count(old) != 1:
        raise RuntimeError(f"Could not find unique {label} in {path}")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


def _patch_heading_review_semantic_retry() -> None:
    path = Path("app/processing/batched_structure_refinement.py")
    constant_anchor = '''_PAGE_ROLE_PROMPT_TOKEN = "v4_page_roles"\n'''
    constant_replacement = '''_PAGE_ROLE_PROMPT_TOKEN = "v4_page_roles"\n_HEADING_REVIEW_SEMANTIC_MAX_ATTEMPTS = 2\n'''
    _replace_once(
        path,
        constant_anchor,
        constant_replacement,
        label="heading semantic retry constant anchor",
    )

    old = '''    async def _propose_one_async(\n        self,\n        spr: StructuredProcessingResultV2,\n        image_batch: Mapping[str, str],\n        *,\n        required_page_role_source_unit_ids: Sequence[str] = (),\n    ) -> StructureRefinementPatch:\n        refiner = self.refiner_factory(dict(image_batch))\n        propose_async = getattr(refiner, "propose_async", None)\n        if callable(propose_async):\n            patch = await propose_async(spr)\n        else:\n            propose = getattr(refiner, "propose", None)\n            if not callable(propose):\n                raise TypeError("batch refiner must expose propose_async(spr) or propose(spr)")\n            patch = await asyncio.to_thread(propose, spr)\n        if not isinstance(patch, StructureRefinementPatch):\n            raise TypeError("batch refiner must return StructureRefinementPatch")\n        _validate_batch_patch(\n            spr,\n            patch,\n            required_page_role_source_unit_ids=required_page_role_source_unit_ids,\n        )\n        return patch\n'''
    new = '''    async def _propose_one_async(\n        self,\n        spr: StructuredProcessingResultV2,\n        image_batch: Mapping[str, str],\n        *,\n        required_page_role_source_unit_ids: Sequence[str] = (),\n    ) -> StructureRefinementPatch:\n        for semantic_attempt in range(1, _HEADING_REVIEW_SEMANTIC_MAX_ATTEMPTS + 1):\n            refiner = self.refiner_factory(dict(image_batch))\n            propose_async = getattr(refiner, "propose_async", None)\n            if callable(propose_async):\n                patch = await propose_async(spr)\n            else:\n                propose = getattr(refiner, "propose", None)\n                if not callable(propose):\n                    raise TypeError(\n                        "batch refiner must expose propose_async(spr) or propose(spr)"\n                    )\n                patch = await asyncio.to_thread(propose, spr)\n            if not isinstance(patch, StructureRefinementPatch):\n                raise TypeError("batch refiner must return StructureRefinementPatch")\n            try:\n                _validate_batch_patch(\n                    spr,\n                    patch,\n                    required_page_role_source_unit_ids=(\n                        required_page_role_source_unit_ids\n                    ),\n                )\n            except RequiredHeadingReviewError as exc:\n                will_retry = (\n                    exc.stage == "heading_review_coverage"\n                    and semantic_attempt < _HEADING_REVIEW_SEMANTIC_MAX_ATTEMPTS\n                )\n                if not will_retry:\n                    raise\n                self.event_sink(\n                    "PDF_STRUCTURE_REFINEMENT_SEMANTIC_RETRY_SCHEDULED",\n                    {\n                        "semantic_attempt": semantic_attempt,\n                        "next_semantic_attempt": semantic_attempt + 1,\n                        "max_semantic_attempts": (\n                            _HEADING_REVIEW_SEMANTIC_MAX_ATTEMPTS\n                        ),\n                        "error_stage": exc.stage,\n                        "expected_heading_count": (\n                            exc.expected_heading_count\n                        ),\n                        "reviewed_heading_count": (\n                            exc.reviewed_heading_count\n                        ),\n                    },\n                )\n                continue\n            return patch\n        raise AssertionError(\n            "heading review semantic retry loop exhausted without returning or raising"\n        )\n'''
    _replace_once(
        path,
        old,
        new,
        label="batched heading review proposal method",
    )


def main() -> None:
    _patch_heading_review_semantic_retry()


if __name__ == "__main__":
    main()
