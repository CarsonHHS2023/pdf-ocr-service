"""Bounded PDF page-image batching for multimodal structure refinement."""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass, replace
from typing import Mapping, Sequence

from app.processing.llm_structure_refinement_request import build_structure_refinement_request
from app.processing.openai_batched_structure_refinement import OpenAIBatchedStructureRefiner
from app.processing.openai_provider_error_diagnostics import (
    diagnostic_openai_client_factory,
    diagnostic_openai_http_post,
)
from app.processing.openai_structure_refinement_provider import (
    OpenAIResponsesStructureRefiner,
    openai_structure_refiner_from_env,
)
from app.processing.refinement_provider_diagnostics import emit_refinement_provider_event
from app.processing.structure_refinement_concurrency import (
    process_structure_refinement_limiter_from_env,
)
from app.processing.structured_result_v2.model import StructuredProcessingResultV2

_SELECTION_PRIORITY = {
    "first_page": 0,
    "last_page": 1,
    "toc_page": 2,
    "summary_page": 3,
    "heading_candidate_page": 4,
    "unknown_node_page": 5,
    "degraded_node_page": 6,
    "low_ocr_confidence_page": 7,
}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


@dataclass(frozen=True, slots=True)
class PdfPageImagePolicy:
    max_pages: int = 16
    max_dimension_pixels: int = 1400
    jpeg_quality: int = 72
    max_image_bytes: int = 1_500_000

    def __post_init__(self) -> None:
        if not isinstance(self.max_pages, int) or isinstance(self.max_pages, bool) or self.max_pages < 1:
            raise ValueError("max_pages must be a positive integer")
        if not isinstance(self.max_dimension_pixels, int) or isinstance(self.max_dimension_pixels, bool) or self.max_dimension_pixels < 256:
            raise ValueError("max_dimension_pixels must be an integer of at least 256")
        if not isinstance(self.jpeg_quality, int) or isinstance(self.jpeg_quality, bool) or not 20 <= self.jpeg_quality <= 95:
            raise ValueError("jpeg_quality must be between 20 and 95")
        if not isinstance(self.max_image_bytes, int) or isinstance(self.max_image_bytes, bool) or self.max_image_bytes < 32_000:
            raise ValueError("max_image_bytes must be at least 32000")


def pdf_page_image_policy_from_env() -> PdfPageImagePolicy:
    """Load bounded page-image settings without exposing provider credentials."""

    return PdfPageImagePolicy(
        max_pages=_env_int("PDF_STRUCTURE_REFINEMENT_MAX_PAGES_PER_BATCH", 16),
        max_dimension_pixels=_env_int("PDF_STRUCTURE_REFINEMENT_MAX_IMAGE_DIMENSION_PIXELS", 1400),
        jpeg_quality=_env_int("PDF_STRUCTURE_REFINEMENT_JPEG_QUALITY", 72),
        max_image_bytes=_env_int("PDF_STRUCTURE_REFINEMENT_MAX_IMAGE_BYTES", 1_500_000),
    )


class PdfPageImageResolver:
    """Render one bounded page set from an already verified retained PDF."""

    def __init__(
        self,
        pdf_bytes: bytes,
        *,
        policy: PdfPageImagePolicy | None = None,
        source_unit_ids: Sequence[str] | None = None,
    ) -> None:
        if not isinstance(pdf_bytes, bytes) or not pdf_bytes:
            raise ValueError("pdf_bytes must be non-empty bytes")
        self._pdf_bytes = pdf_bytes
        self._policy = policy or pdf_page_image_policy_from_env()
        self._source_unit_ids = tuple(source_unit_ids) if source_unit_ids is not None else None
        self._cache: dict[tuple[str, ...], dict[str, str]] = {}

    def __call__(self, spr: StructuredProcessingResultV2) -> Mapping[str, str]:
        source_unit_ids = list(self._source_unit_ids or _selected_source_unit_ids(spr))
        if self._source_unit_ids is None:
            source_unit_ids = source_unit_ids[: self._policy.max_pages]
        cache_key = tuple(source_unit_ids)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return dict(cached)
        source_order = {unit.source_unit_id: unit.source_order for unit in spr.source_units}
        rendered: dict[str, str] = {}
        import fitz  # type: ignore[import]

        document = fitz.open(stream=self._pdf_bytes, filetype="pdf")
        try:
            for source_unit_id in source_unit_ids:
                page_index = source_order.get(source_unit_id)
                if page_index is None or page_index < 0 or page_index >= document.page_count:
                    continue
                jpeg = _render_page_jpeg(document[page_index], self._policy)
                rendered[source_unit_id] = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
        finally:
            document.close()
        self._cache[cache_key] = rendered
        return dict(rendered)


class PdfPageImageBatchPlanner:
    """Render every selected page exactly once across bounded batches."""

    def __init__(self, pdf_bytes: bytes, *, policy: PdfPageImagePolicy | None = None) -> None:
        self._pdf_bytes = pdf_bytes
        self._policy = policy or pdf_page_image_policy_from_env()

    def __call__(self, spr: StructuredProcessingResultV2) -> Sequence[Mapping[str, str]]:
        selected = _selected_source_unit_ids(spr)
        batches: list[Mapping[str, str]] = []
        for start in range(0, len(selected), self._policy.max_pages):
            ids = selected[start : start + self._policy.max_pages]
            resolver = PdfPageImageResolver(
                self._pdf_bytes,
                policy=self._policy,
                source_unit_ids=ids,
            )
            batches.append(resolver(spr))
        return tuple(batches)


def _selected_source_unit_ids(spr: StructuredProcessingResultV2) -> list[str]:
    request = build_structure_refinement_request(spr)
    raw_reasons = request.get("page_selection_reasons") or {}
    reasons = raw_reasons if isinstance(raw_reasons, dict) else {}
    source_order = {unit.source_unit_id: unit.source_order for unit in spr.source_units}

    def priority(source_unit_id: str) -> tuple[int, int, str]:
        page_reasons = reasons.get(source_unit_id) or []
        best = min((_SELECTION_PRIORITY.get(str(reason), 99) for reason in page_reasons), default=99)
        return best, source_order.get(source_unit_id, 2**31), source_unit_id

    return sorted((str(item) for item in reasons), key=priority)


def _render_page_jpeg(page, policy: PdfPageImagePolicy) -> bytes:
    rect = page.rect
    longest = max(float(rect.width), float(rect.height))
    if longest <= 0:
        raise ValueError("PDF page must have positive dimensions")
    scale = min(1.0, policy.max_dimension_pixels / longest)
    import fitz  # type: ignore[import]

    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    quality = policy.jpeg_quality
    while quality >= 30:
        jpeg = pixmap.tobytes("jpeg", jpg_quality=quality)
        if len(jpeg) <= policy.max_image_bytes:
            return jpeg
        quality -= 10
    raise ValueError("rendered refinement page image exceeds the configured byte limit")


def openai_pdf_structure_refinement_is_configured() -> bool:
    """Return whether the optional provider is explicitly and completely configured."""

    api_key = os.getenv("PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY", "").strip()
    model_id = os.getenv("PDF_STRUCTURE_REFINEMENT_OPENAI_MODEL", "").strip()
    if not api_key and not model_id:
        return False
    if not api_key or not model_id:
        raise ValueError("both PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY and _MODEL are required")
    return True


def openai_pdf_structure_refiner_from_env(
    pdf_bytes: bytes,
    *,
    policy: PdfPageImagePolicy | None = None,
    global_semaphore: object | None = None,
) -> OpenAIBatchedStructureRefiner | OpenAIResponsesStructureRefiner | None:
    """Build a batched OpenAI refiner; missing provider configuration stays disabled."""

    if not openai_pdf_structure_refinement_is_configured():
        return None
    planner = PdfPageImageBatchPlanner(
        pdf_bytes,
        policy=policy or pdf_page_image_policy_from_env(),
    )
    probe = openai_structure_refiner_from_env(
        page_image_resolver=lambda _spr: {},
        async_http_post=diagnostic_openai_http_post,
    )
    assert probe is not None
    probe = replace(probe, event_sink=emit_refinement_provider_event)

    max_concurrent_batches = int(
        os.getenv("PDF_STRUCTURE_REFINEMENT_MAX_CONCURRENT_BATCHES", "2")
    )
    limiter = global_semaphore or process_structure_refinement_limiter_from_env()
    return OpenAIBatchedStructureRefiner(
        probe=probe,
        batch_planner=planner,
        max_concurrent_batches=max_concurrent_batches,
        batch_timeout_seconds=probe.timeout_seconds,
        global_semaphore=limiter,
        client_factory=diagnostic_openai_client_factory,
    )


__all__ = [
    "PdfPageImageBatchPlanner",
    "PdfPageImagePolicy",
    "PdfPageImageResolver",
    "openai_pdf_structure_refinement_is_configured",
    "openai_pdf_structure_refiner_from_env",
    "pdf_page_image_policy_from_env",
]
