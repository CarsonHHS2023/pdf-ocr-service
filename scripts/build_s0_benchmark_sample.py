#!/usr/bin/env python3
"""Build a bounded, reproducible PDF sample for S0 benchmarking.

The output PDF copies selected source pages without rendering them. A JSON
manifest records the source SHA-256, sampling seed, selected original pages, and
sample-to-original page mapping so multiple S0 implementations can benchmark the
same source pages.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Iterable

import fitz  # type: ignore[import]

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.processing.s0_benchmark_sampling import (  # noqa: E402
    DEFAULT_EDGE_PAGE_COUNT,
    DEFAULT_SAMPLE_SIZE,
    DEFAULT_SEED,
    build_benchmark_manifest,
    build_benchmark_sample_plan,
)


def _parse_special_pages(raw_values: Iterable[str]) -> tuple[int, ...]:
    pages: list[int] = []
    for raw_value in raw_values:
        for token in raw_value.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                page = int(token)
            except ValueError as exc:
                raise ValueError(f"invalid special page number: {token!r}") from exc
            pages.append(page)
    return tuple(pages)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_output_path(source: Path, sample_size: int) -> Path:
    return source.with_name(f"{source.stem}.s0-benchmark-{sample_size}.pdf")


def _default_manifest_path(sample_pdf: Path) -> Path:
    return sample_pdf.with_suffix(".json")


def _write_sample_pdf(
    *,
    source_path: Path,
    output_path: Path,
    selected_pages: tuple[int, ...],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    source = fitz.open(source_path)
    sampled = fitz.open()
    try:
        for original_page in selected_pages:
            sampled.insert_pdf(
                source,
                from_page=original_page - 1,
                to_page=original_page - 1,
            )
        sampled.save(output_path, garbage=4, deflate=True)
    finally:
        sampled.close()
        source.close()


def build_sample(
    *,
    source_path: Path,
    output_path: Path | None = None,
    manifest_path: Path | None = None,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    seed: str = DEFAULT_SEED,
    edge_page_count: int = DEFAULT_EDGE_PAGE_COUNT,
    special_pages: Iterable[int] | None = None,
) -> tuple[Path, Path, dict[str, object]]:
    source_path = source_path.resolve()
    if not source_path.exists() or not source_path.is_file():
        raise FileNotFoundError(f"source PDF not found: {source_path}")

    source = fitz.open(source_path)
    try:
        page_count = source.page_count
    finally:
        source.close()
    if page_count < 1:
        raise ValueError("source PDF contains no pages")

    plan = build_benchmark_sample_plan(
        page_count,
        sample_size=sample_size,
        seed=seed,
        edge_page_count=edge_page_count,
        special_pages=special_pages,
    )

    output_path = (output_path or _default_output_path(source_path, plan.sample_size)).resolve()
    manifest_path = (manifest_path or _default_manifest_path(output_path)).resolve()
    if output_path == source_path:
        raise ValueError("benchmark output path must not replace the source PDF")
    if manifest_path == source_path or manifest_path == output_path:
        raise ValueError("manifest path must be distinct from source and sample PDF")

    source_sha256 = _sha256_file(source_path)
    _write_sample_pdf(
        source_path=source_path,
        output_path=output_path,
        selected_pages=plan.selected_pages,
    )

    manifest = build_benchmark_manifest(
        plan,
        source_sha256=source_sha256,
        source_filename=source_path.name,
        sample_filename=output_path.name,
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path, manifest_path, manifest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create a reproducible stratified PDF sample for bounded S0 "
            "preprocessing benchmarks."
        )
    )
    parser.add_argument("source_pdf", type=Path)
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    parser.add_argument("--seed", default=DEFAULT_SEED)
    parser.add_argument(
        "--edge-pages",
        type=int,
        default=DEFAULT_EDGE_PAGE_COUNT,
        help="mandatory page count from both the beginning and end of the PDF",
    )
    parser.add_argument(
        "--special-pages",
        action="append",
        default=[],
        metavar="PAGES",
        help="1-based mandatory pages; comma-separated or repeat the option",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--manifest", type=Path)
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        special_pages = _parse_special_pages(args.special_pages)
        output_path, manifest_path, manifest = build_sample(
            source_path=args.source_pdf,
            output_path=args.output,
            manifest_path=args.manifest,
            sample_size=args.sample_size,
            seed=args.seed,
            edge_page_count=args.edge_pages,
            special_pages=special_pages,
        )
    except (FileNotFoundError, ValueError, RuntimeError, fitz.FileDataError) as exc:
        parser.error(str(exc))

    summary = {
        "source_page_count": manifest["source_page_count"],
        "sample_size": manifest["sample_size"],
        "seed": manifest["seed"],
        "selection_digest": manifest["selection_digest"],
        "sample_pdf": str(output_path),
        "manifest": str(manifest_path),
        "selected_original_pages": manifest["selected_original_pages"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
