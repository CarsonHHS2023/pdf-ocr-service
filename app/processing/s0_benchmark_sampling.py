"""Reproducible bounded sampling for S0 preprocessing benchmarks.

This module deliberately contains no OpenCV or provider behavior. It only chooses
which original PDF pages belong to a bounded benchmark sample so legacy v4 and
future S0 implementations can be compared on exactly the same pages.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import random
from typing import Iterable

DEFAULT_SAMPLE_SIZE = 100
DEFAULT_EDGE_PAGE_COUNT = 5
DEFAULT_SEED = "atlas-s0-v5-benchmark-v1"
SELECTION_ALGORITHM = "seeded-stratified-random-v1"


@dataclass(frozen=True)
class BenchmarkSamplePlan:
    """Immutable description of one source-page benchmark sample."""

    page_count: int
    requested_sample_size: int
    sample_size: int
    seed: str
    edge_page_count: int
    special_pages: tuple[int, ...]
    selected_pages: tuple[int, ...]
    selection_digest: str

    @property
    def page_mapping(self) -> tuple[tuple[int, int], ...]:
        """Return ``(sample_page, original_page)`` pairs using 1-based pages."""

        return tuple(
            (sample_page, original_page)
            for sample_page, original_page in enumerate(self.selected_pages, start=1)
        )


def _normalize_special_pages(
    page_count: int,
    special_pages: Iterable[int] | None,
) -> tuple[int, ...]:
    if special_pages is None:
        return ()

    normalized: list[int] = []
    for page in special_pages:
        if isinstance(page, bool) or not isinstance(page, int):
            raise ValueError("special pages must be integer page numbers")
        if page < 1 or page > page_count:
            raise ValueError(
                f"special page {page} is outside the source range 1..{page_count}"
            )
        normalized.append(page)
    return tuple(sorted(set(normalized)))


def _rng_for(*, page_count: int, sample_size: int, seed: str) -> random.Random:
    # Do not rely on process hash randomization or wall-clock state. Converting a
    # SHA-256 digest to an integer makes the sampling seed explicit and stable.
    material = (
        f"{SELECTION_ALGORITHM}|{seed}|{page_count}|{sample_size}"
    ).encode("utf-8")
    return random.Random(int.from_bytes(sha256(material).digest(), "big"))


def build_benchmark_sample_plan(
    page_count: int,
    *,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    seed: str = DEFAULT_SEED,
    edge_page_count: int = DEFAULT_EDGE_PAGE_COUNT,
    special_pages: Iterable[int] | None = None,
) -> BenchmarkSamplePlan:
    """Choose a deterministic stratified sample from a PDF page range.

    The first and last ``edge_page_count`` pages are mandatory. Caller-supplied
    special/problem pages are also mandatory. Remaining slots are filled by
    dividing all remaining source pages into equally sized ordered strata and
    choosing one page from each stratum with a stable seeded RNG.

    Selected pages are returned in original document order so the extracted
    benchmark PDF preserves the source reading order.
    """

    if isinstance(page_count, bool) or not isinstance(page_count, int) or page_count < 1:
        raise ValueError("page_count must be a positive integer")
    if isinstance(sample_size, bool) or not isinstance(sample_size, int) or sample_size < 1:
        raise ValueError("sample_size must be a positive integer")
    if (
        isinstance(edge_page_count, bool)
        or not isinstance(edge_page_count, int)
        or edge_page_count < 0
    ):
        raise ValueError("edge_page_count must be a non-negative integer")
    if not isinstance(seed, str) or not seed.strip():
        raise ValueError("seed must be a non-empty string")

    target_size = min(sample_size, page_count)
    normalized_special_pages = _normalize_special_pages(page_count, special_pages)

    mandatory: set[int] = set(normalized_special_pages)
    first_count = min(edge_page_count, page_count)
    mandatory.update(range(1, first_count + 1))
    mandatory.update(
        range(max(1, page_count - edge_page_count + 1), page_count + 1)
    )

    if len(mandatory) > target_size:
        raise ValueError(
            "mandatory edge/special pages exceed the requested sample size: "
            f"mandatory={len(mandatory)} sample_size={target_size}"
        )

    candidates = [
        page for page in range(1, page_count + 1) if page not in mandatory
    ]
    needed = target_size - len(mandatory)
    sampled: list[int] = []

    if needed:
        rng = _rng_for(page_count=page_count, sample_size=target_size, seed=seed)
        candidate_count = len(candidates)
        for stratum_index in range(needed):
            start = (stratum_index * candidate_count) // needed
            stop = ((stratum_index + 1) * candidate_count) // needed
            bucket = candidates[start:stop]
            # needed <= candidate_count by construction, so every stratum is
            # non-empty. Keep the guard explicit because a silent empty stratum
            # would make benchmark selection non-auditable.
            if not bucket:
                raise RuntimeError("benchmark sampling produced an empty stratum")
            sampled.append(rng.choice(bucket))

    selected_pages = tuple(sorted(mandatory.union(sampled)))
    if len(selected_pages) != target_size:
        raise RuntimeError(
            "benchmark sampling did not produce the requested number of pages"
        )

    digest_payload = (
        f"{SELECTION_ALGORITHM}|{page_count}|{target_size}|{seed}|"
        + ",".join(str(page) for page in selected_pages)
    )
    selection_digest = sha256(digest_payload.encode("utf-8")).hexdigest()

    return BenchmarkSamplePlan(
        page_count=page_count,
        requested_sample_size=sample_size,
        sample_size=target_size,
        seed=seed,
        edge_page_count=edge_page_count,
        special_pages=normalized_special_pages,
        selected_pages=selected_pages,
        selection_digest=selection_digest,
    )


def build_benchmark_manifest(
    plan: BenchmarkSamplePlan,
    *,
    source_sha256: str,
    source_filename: str | None = None,
    sample_filename: str | None = None,
) -> dict[str, object]:
    """Build the audit manifest persisted beside a sampled benchmark PDF."""

    normalized_sha = str(source_sha256).strip().lower()
    if len(normalized_sha) != 64 or any(
        character not in "0123456789abcdef" for character in normalized_sha
    ):
        raise ValueError("source_sha256 must be a SHA-256 hex digest")

    return {
        "schema_version": "atlas.s0.benchmark_sample.v1",
        "selection_algorithm": SELECTION_ALGORITHM,
        "source_sha256": normalized_sha,
        "source_filename": source_filename,
        "source_page_count": plan.page_count,
        "requested_sample_size": plan.requested_sample_size,
        "sample_size": plan.sample_size,
        "seed": plan.seed,
        "edge_page_count": plan.edge_page_count,
        "special_pages": list(plan.special_pages),
        "selected_original_pages": list(plan.selected_pages),
        "sample_filename": sample_filename,
        "selection_digest": plan.selection_digest,
        "page_mapping": [
            {
                "sample_page": sample_page,
                "original_page": original_page,
            }
            for sample_page, original_page in plan.page_mapping
        ],
    }
