from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import fitz  # type: ignore[import]
import pytest

from app.processing.s0_benchmark_sampling import (
    DEFAULT_SEED,
    build_benchmark_manifest,
    build_benchmark_sample_plan,
)


def test_528_page_default_sample_is_exactly_100_and_reproducible() -> None:
    first = build_benchmark_sample_plan(528)
    second = build_benchmark_sample_plan(528)

    assert first == second
    assert first.sample_size == 100
    assert len(first.selected_pages) == 100
    assert len(set(first.selected_pages)) == 100
    assert first.selected_pages == tuple(sorted(first.selected_pages))
    assert first.selected_pages[:5] == (1, 2, 3, 4, 5)
    assert first.selected_pages[-5:] == (524, 525, 526, 527, 528)
    assert first.selection_digest == (
        "c8012f2cb80227418065c669b59b15bacdeb0721754f5a2975ad6eff2f798443"
    )

    # The seeded stratification should cover the whole source rather than allow
    # a random cluster to leave a large unrepresented region.
    gaps = [
        right - left
        for left, right in zip(first.selected_pages, first.selected_pages[1:])
    ]
    assert max(gaps) <= 11


def test_different_seed_changes_interior_but_keeps_mandatory_edges() -> None:
    first = build_benchmark_sample_plan(528, seed=DEFAULT_SEED)
    second = build_benchmark_sample_plan(528, seed="atlas-s0-v5-benchmark-alt")

    assert first.selected_pages != second.selected_pages
    assert first.selected_pages[:5] == second.selected_pages[:5] == (1, 2, 3, 4, 5)
    assert first.selected_pages[-5:] == second.selected_pages[-5:] == (
        524,
        525,
        526,
        527,
        528,
    )


def test_special_problem_pages_are_mandatory_without_duplicates() -> None:
    plan = build_benchmark_sample_plan(
        528,
        special_pages=[3, 17, 302, 400, 302],
    )

    assert plan.special_pages == (3, 17, 302, 400)
    assert {3, 17, 302, 400}.issubset(plan.selected_pages)
    assert len(plan.selected_pages) == 100


def test_small_source_uses_every_page() -> None:
    plan = build_benchmark_sample_plan(8, sample_size=100)

    assert plan.sample_size == 8
    assert plan.selected_pages == tuple(range(1, 9))
    assert plan.page_mapping == tuple((page, page) for page in range(1, 9))


def test_mandatory_pages_cannot_silently_overflow_sample() -> None:
    with pytest.raises(ValueError, match="mandatory edge/special pages exceed"):
        build_benchmark_sample_plan(
            50,
            sample_size=10,
            edge_page_count=5,
            special_pages=[11],
        )


def test_manifest_records_source_identity_and_page_mapping() -> None:
    plan = build_benchmark_sample_plan(
        20,
        sample_size=12,
        edge_page_count=2,
        special_pages=[10],
        seed="manifest-test",
    )
    manifest = build_benchmark_manifest(
        plan,
        source_sha256="a" * 64,
        source_filename="book.pdf",
        sample_filename="book.sample.pdf",
    )

    assert manifest["schema_version"] == "atlas.s0.benchmark_sample.v1"
    assert manifest["source_sha256"] == "a" * 64
    assert manifest["sample_size"] == 12
    assert manifest["special_pages"] == [10]
    assert manifest["selected_original_pages"] == list(plan.selected_pages)
    assert manifest["page_mapping"][0] == {
        "sample_page": 1,
        "original_page": plan.selected_pages[0],
    }
    assert manifest["page_mapping"][-1] == {
        "sample_page": 12,
        "original_page": plan.selected_pages[-1],
    }


def _write_numbered_pdf(path: Path, page_count: int) -> None:
    document = fitz.open()
    try:
        for original_page in range(1, page_count + 1):
            page = document.new_page(width=300, height=400)
            page.insert_text((40, 60), f"ORIGINAL_PAGE={original_page}")
        document.save(path)
    finally:
        document.close()


def test_cli_builds_sample_pdf_and_auditable_manifest(tmp_path: Path) -> None:
    source_path = tmp_path / "source.pdf"
    output_path = tmp_path / "sample.pdf"
    manifest_path = tmp_path / "sample.json"
    _write_numbered_pdf(source_path, 32)

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_s0_benchmark_sample.py",
            str(source_path),
            "--sample-size",
            "12",
            "--edge-pages",
            "2",
            "--seed",
            "cli-test",
            "--special-pages",
            "8,17",
            "--output",
            str(output_path),
            "--manifest",
            str(manifest_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_page_count"] == 32
    assert manifest["sample_size"] == 12
    assert {1, 2, 8, 17, 31, 32}.issubset(manifest["selected_original_pages"])
    assert manifest["source_sha256"] == hashlib.sha256(source_path.read_bytes()).hexdigest()

    sampled = fitz.open(output_path)
    try:
        assert sampled.page_count == 12
        extracted_original_pages = []
        for page in sampled:
            text = page.get_text("text")
            marker = text.split("ORIGINAL_PAGE=", 1)[1].split()[0]
            extracted_original_pages.append(int(marker))
    finally:
        sampled.close()

    assert extracted_original_pages == manifest["selected_original_pages"]
