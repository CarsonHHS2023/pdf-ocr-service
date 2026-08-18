"""Align OpenAI batch page-role scope with the authoritative batch validator."""
from __future__ import annotations

from pathlib import Path


def _replace_once(path: Path, old: str, new: str, *, label: str) -> None:
    source = path.read_text(encoding="utf-8")
    if new in source:
        return
    if source.count(old) != 1:
        raise RuntimeError(f"Could not find unique {label} in {path}")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


def _patch_openai_page_role_scope() -> None:
    path = Path("app/processing/openai_batched_structure_refinement.py")
    import_anchor = (
        "import httpx\n\n"
        "from app.processing.batched_structure_refinement import BatchedStructureRefiner\n"
    )
    import_replacement = (
        "import httpx\n\n"
        "from app.processing import batched_structure_refinement as batched\n"
        "from app.processing.batched_structure_refinement import BatchedStructureRefiner\n"
    )
    _replace_once(
        path,
        import_anchor,
        import_replacement,
        label="authoritative batched refinement import",
    )

    _replace_once(
        path,
        "        boundary_positions = _document_boundary_positions(spr)\n",
        "        boundary_positions = batched._document_boundary_positions(spr)\n",
        label="OpenAI page-role boundary source",
    )


def main() -> None:
    _patch_openai_page_role_scope()


if __name__ == "__main__":
    main()
