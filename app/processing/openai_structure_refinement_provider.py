"""OpenAI Responses API adapter for bounded multimodal PDF refinement."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping

import httpx

from app.processing.llm_structure_refinement import StructureRefinementPatch
from app.processing.llm_structure_refinement_provider import (
    DEFAULT_STRUCTURE_REFINEMENT_PROMPT_VERSION,
    StructureRefinementResponseError,
    parse_structure_refinement_response,
)
from app.processing.llm_structure_refinement_request import build_structure_refinement_request
from app.processing.structured_result_v2.model import (
    ProcessingNodeKind,
    ProcessingNodeRecoveryState,
    StructuredProcessingResultV2,
)

PageImageResolver = Callable[[StructuredProcessingResultV2], Mapping[str, str]]
HttpPost = Callable[[str, Mapping[str, str], Mapping[str, Any], float], Mapping[str, Any]]
AsyncHttpPost = Callable[
    [str, Mapping[str, str], Mapping[str, Any], float],
    Awaitable[Mapping[str, Any]],
]
AsyncSleep = Callable[[float], Awaitable[None]]
ProviderEventSink = Callable[[str, Mapping[str, object]], None]

_logger = logging.getLogger("uvicorn.error")
_RETRYABLE_STATUS_CODES = frozenset({408, 409, 429, 500, 502, 503, 504})
_TOC_RULE = "mineru_popo_toc_item"
_SAFE_DIAGNOSTIC_LIMIT = 180


def _log_provider_event(event: str, fields: Mapping[str, object]) -> None:
    payload = " ".join(f"{name}={value}" for name, value in sorted(fields.items()))
    _logger.info("%s %s", event, payload)


class StructureRefinementProviderError(RuntimeError):
    """Bounded provider failure safe for retry classification and logging."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


_PATCH_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["page_reviews", "operations"],
    "properties": {
        "page_reviews": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "source_unit_id",
                    "page_role",
                    "confidence",
                    "reason_codes",
                ],
                "properties": {
                    "source_unit_id": {"type": "string", "minLength": 1},
                    "page_role": {
                        "type": "string",
                        "enum": [
                            "cover",
                            "back_cover",
                            "title_page",
                            "copyright_page",
                            "body",
                            "unknown",
                        ],
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "reason_codes": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "minLength": 1},
                    },
                },
            },
        },
        "operations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "op",
                    "node_id",
                    "confidence",
                    "reason_codes",
                    "target_kind",
                    "heading_level",
                    "toc_level",
                    "parent_id",
                    "original_text",
                    "corrected_text",
                    "warning",
                ],
                "properties": {
                    "op": {
                        "type": "string",
                        "enum": [
                            "reclassify_node", "set_toc_level", "set_parent",
                            "suppress_as_artifact", "correct_text", "add_warning",
                        ],
                    },
                    "node_id": {"type": "string", "minLength": 1},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "reason_codes": {
                        "type": "array", "minItems": 1,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "target_kind": {
                        "type": ["string", "null"],
                        "enum": [
                            None, "title", "heading", "paragraph", "list", "list_item",
                            "caption", "formula", "header", "footer", "footnote",
                            "table", "figure", "quote", "code", "reference", "unknown",
                        ],
                    },
                    "heading_level": {"type": ["integer", "null"], "minimum": 1, "maximum": 6},
                    "toc_level": {"type": ["integer", "null"], "minimum": 1, "maximum": 12},
                    "parent_id": {"type": ["string", "null"]},
                    "original_text": {"type": ["string", "null"]},
                    "corrected_text": {"type": ["string", "null"]},
                    "warning": {"type": ["string", "null"]},
                },
            },
        },
    },
}

_SYSTEM_INSTRUCTION = """You are a PDF document-structure, page-role, and OCR-correction reviewer.
Perform exactly five tasks. Return only page_reviews for scoped boundary pages and bounded
operations against existing node_ids.

TASK 1 — FIRST AND LAST PAGE ROLE
For every source_unit_id listed in review_scope.page_role_review_positions, return exactly
one page_reviews item. Use the page image, page position, OCR nodes, layout, typography,
artwork, logos, barcodes, publisher marks, and amount of continuous body prose. Allowed
roles are cover, back_cover, title_page, copyright_page, body, and unknown.

A front cover may contain a title, subtitle, author, editor, translator, publisher, logo,
and large artwork. These elements may currently be classified as heading, paragraph,
figure, or unknown. Do not reject a cover merely because author or publisher text is a
paragraph. A back cover may contain marketing copy, blurbs, barcode, publisher marks, or
artwork. Do not classify a normal chapter-opening page or continuous body-text page as a
cover. Return unknown when visual evidence is insufficient.

TASK 2 — HEADING STRUCTURE
For every title/heading candidate, decide whether it is truly a semantic document heading.
If it is a heading, assign the correct heading_level from 1 through 6. If it is not,
reclassify it as paragraph, list_item, header, footer, figure, caption, unknown, or another
allowed existing kind. Never decide from font size alone. Use page position, neighboring
nodes, document-outline consistency, cross-page repetition, visual containers, and images.

TASK 3 — TABLE OF CONTENTS
For every TOC list_item, assign toc_level 1, 2, 3, or deeper as supported by visual
indentation and neighboring hierarchy. TOC entries must remain list_item nodes; never turn
them into headings. Exclude page headers, footers, page numbers, and decoration mistakenly
recovered as TOC items.

TASK 4 — OCR CORRECTION
Inspect low-confidence and visually suspicious text. Pay special attention to show-through
or bleed-through: text from the reverse side or next page visible through paper. It is often
very faint, low contrast, mirrored, offset, overlapping real text, outside normal lines, and
semantically unrelated to the current page. Also inspect extremely low visual visibility,
text absent from the page image, isolated characters, scan stains/noise, abnormal bbox size,
bbox/text mismatch, overlapping coordinates, chaotic node order, and semantic discontinuity.
Low OCR confidence is only a review trigger, not proof of error.

Use correct_text only when the page image clearly supports one unique correction. The
operation must include original_text exactly matching the current node text and a non-empty
corrected_text. Do not polish, paraphrase, infer missing prose, or rely on context when the
image is unreadable. When content is likely bleed-through or scan noise, use
suppress_as_artifact. When evidence is uncertain, use add_warning or return no operation.

TASK 5 — REQUIRED UNKNOWN/DEGRADED DISPOSITION
For every node_id listed in review_scope.unresolved_candidate_node_ids, return exactly one
primary disposition: reclassify_node or suppress_as_artifact. This requirement also applies
when the node currently has a non-unknown kind but recovery_state is degraded. If the
current kind is visually correct, return reclassify_node with that same kind so the review
is explicit and auditable. If visual evidence remains insufficient, return reclassify_node
with target_kind unknown and an uncertainty reason code; do not omit the node.

Nodes whose recovery_rule is llm_pre_refinement_toc_line were deterministically split from
one multiline degraded block. Do not merge or drop them. When the page image shows that a
line is a table-of-contents entry, reclassify it to list_item and also return set_toc_level
based on indentation and neighboring hierarchy. Use suppress_as_artifact only when the line
is not genuine visible page content, such as bleed-through, scan noise, decoration, or a
duplicate OCR artifact.

The general instruction to return no operation when uncertain applies only to optional
nodes outside review_scope.unresolved_candidate_node_ids. Every scoped unresolved node must
receive exactly one primary disposition.

Suggested reason codes include probable_show_through, possible_show_through,
very_low_visual_contrast, text_not_visible_in_page_image, mirrored_background_text,
overlapping_text_geometry, bbox_text_mismatch, abnormal_bbox_size,
reading_order_conflict, semantic_discontinuity, isolated_character_artifact,
scan_noise_or_stain, and no_unique_text_correction.

Preserve node ids and evidence. Return no node operation for optional nodes when uncertain.
Never rewrite the whole document and never create arbitrary nodes.
"""


async def _default_async_http_post(
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
    timeout_seconds: float,
) -> Mapping[str, Any]:
    timeout = httpx.Timeout(timeout_seconds)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=dict(headers), json=payload)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        raise StructureRefinementProviderError(
            f"structure refinement provider HTTP {status_code}",
            retryable=status_code in _RETRYABLE_STATUS_CODES,
            status_code=status_code,
            retry_after_seconds=_retry_after_seconds(exc.response.headers.get("Retry-After")),
        ) from exc
    except httpx.RequestError as exc:
        raise StructureRefinementProviderError(
            "structure refinement provider unavailable",
            retryable=True,
        ) from exc
    try:
        decoded = response.json()
    except ValueError as exc:
        raise StructureRefinementProviderError(
            "structure refinement provider returned invalid JSON",
            retryable=False,
            status_code=response.status_code,
        ) from exc
    if not isinstance(decoded, Mapping):
        raise StructureRefinementProviderError(
            "structure refinement provider response must be an object",
            retryable=False,
            status_code=response.status_code,
        )
    return decoded


def _retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value.strip())
    except (TypeError, ValueError):
        return None
    return max(0.0, parsed)


def _response_output_text(response: Mapping[str, Any]) -> str:
    direct = response.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    for item in response.get("output") or []:
        if not isinstance(item, Mapping) or item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if (
                isinstance(content, Mapping)
                and content.get("type") in {"output_text", "text"}
                and isinstance(content.get("text"), str)
            ):
                return str(content["text"])
    raise ValueError("OpenAI response did not contain output text")


def _bounded_diagnostic(value: object, limit: int = _SAFE_DIAGNOSTIC_LIMIT) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split())
    if not normalized:
        return None
    return normalized[:limit]


def _request_preflight_fields(
    spr: StructuredProcessingResultV2,
    serialized_request: str,
    *,
    selected_page_count: int,
    page_role_review_count: int,
) -> dict[str, object]:
    return {
        "json_preflight_passed": True,
        "serialized_request_bytes": len(serialized_request.encode("utf-8")),
        "source_unit_count": len(spr.source_units),
        "observation_count": len(spr.observations),
        "node_count": len(spr.nodes),
        "evidence_count": len(spr.evidence),
        "unknown_node_count": sum(
            node.kind is ProcessingNodeKind.UNKNOWN for node in spr.nodes
        ),
        "degraded_node_count": sum(
            node.recovery_state is ProcessingNodeRecoveryState.DEGRADED
            for node in spr.nodes
        ),
        "toc_item_count": sum(
            node.kind is ProcessingNodeKind.LIST_ITEM
            and isinstance(node.metadata, Mapping)
            and node.metadata.get("recovery_rule") == _TOC_RULE
            for node in spr.nodes
        ),
        "heading_candidate_count": sum(
            node.kind in {ProcessingNodeKind.TITLE, ProcessingNodeKind.HEADING}
            for node in spr.nodes
        ),
        "page_role_review_count": page_role_review_count,
        "selected_page_count": selected_page_count,
    }


def _response_diagnostic_fields(response: Mapping[str, Any]) -> dict[str, object]:
    output_items = response.get("output")
    output_types: list[str] = []
    if isinstance(output_items, list):
        output_types = sorted({
            str(item.get("type"))
            for item in output_items
            if isinstance(item, Mapping) and item.get("type") is not None
        })

    output_text: str | None = None
    try:
        output_text = _response_output_text(response)
    except ValueError:
        pass

    incomplete_details = response.get("incomplete_details")
    incomplete_reason = (
        incomplete_details.get("reason")
        if isinstance(incomplete_details, Mapping)
        else None
    )
    usage = response.get("usage")
    usage = usage if isinstance(usage, Mapping) else {}
    return {
        "response_id": _bounded_diagnostic(response.get("id"), 100),
        "response_model": _bounded_diagnostic(response.get("model"), 100),
        "response_status": _bounded_diagnostic(response.get("status"), 60),
        "output_item_types": ",".join(output_types),
        "output_text_present": output_text is not None,
        "output_text_length": len(output_text) if output_text is not None else 0,
        "incomplete_reason": _bounded_diagnostic(incomplete_reason, 100),
        "input_tokens": _non_negative_int(usage.get("input_tokens")),
        "output_tokens": _non_negative_int(usage.get("output_tokens")),
    }


def _non_negative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


def _parse_failure_fields(
    exc: Exception,
    *,
    stage: str,
) -> dict[str, object]:
    fields: dict[str, object] = {
        "error_stage": stage,
        "error_type": type(exc).__name__,
    }
    if isinstance(exc, json.JSONDecodeError):
        fields.update({
            "error_summary": _bounded_diagnostic(exc.msg),
            "error_line": exc.lineno,
            "error_column": exc.colno,
        })
    elif isinstance(exc, StructureRefinementResponseError):
        fields.update({
            "error_stage": exc.stage,
            "error_summary": _bounded_diagnostic(str(exc)),
            "operation_index": exc.operation_index,
            "operation_kind": exc.operation_kind,
            "null_fields": ",".join(exc.null_fields),
        })
    elif str(exc) == "OpenAI response did not contain output text":
        fields["error_summary"] = str(exc)
    return fields


@dataclass(frozen=True, slots=True)
class OpenAIResponsesStructureRefiner:
    api_key: str
    model_id: str
    page_image_resolver: PageImageResolver | None = None
    page_role_review_positions: Mapping[str, str] | None = None
    endpoint: str = "https://api.openai.com/v1/responses"
    timeout_seconds: float = 60.0
    prompt_version: str = DEFAULT_STRUCTURE_REFINEMENT_PROMPT_VERSION
    async_http_post: AsyncHttpPost = _default_async_http_post
    http_post: HttpPost | None = None
    max_attempts: int = 3
    initial_backoff_seconds: float = 0.5
    max_backoff_seconds: float = 8.0
    sleep: AsyncSleep = asyncio.sleep
    event_sink: ProviderEventSink = _log_provider_event

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValueError("api_key must be non-empty")
        if not self.model_id.strip():
            raise ValueError("model_id must be non-empty")
        if not self.endpoint.startswith("https://"):
            raise ValueError("endpoint must use HTTPS")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if isinstance(self.max_attempts, bool) or self.max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        if self.initial_backoff_seconds < 0:
            raise ValueError("initial_backoff_seconds must be non-negative")
        if self.max_backoff_seconds < self.initial_backoff_seconds:
            raise ValueError("max_backoff_seconds must be at least initial_backoff_seconds")
        if self.page_role_review_positions is not None:
            object.__setattr__(
                self,
                "page_role_review_positions",
                dict(self.page_role_review_positions),
            )

    async def propose_async(self, spr: StructuredProcessingResultV2) -> StructureRefinementPatch:
        request_payload = build_structure_refinement_request(
            spr,
            page_role_review_positions=self.page_role_review_positions,
        )
        try:
            serialized_request = json.dumps(
                request_payload,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            self.event_sink(
                "PDF_STRUCTURE_REFINEMENT_REQUEST_PREFLIGHT_FAILED",
                {
                    "error_stage": "request_json_preflight",
                    "error_type": type(exc).__name__,
                    "json_preflight_passed": False,
                    "source_unit_count": len(spr.source_units),
                    "observation_count": len(spr.observations),
                    "node_count": len(spr.nodes),
                    "evidence_count": len(spr.evidence),
                },
            )
            raise

        try:
            images = self.page_image_resolver(spr) if self.page_image_resolver else {}
        except Exception as exc:
            self.event_sink(
                "PDF_STRUCTURE_REFINEMENT_REQUEST_PREFLIGHT_FAILED",
                {
                    "error_stage": "page_image_resolution",
                    "error_type": type(exc).__name__,
                    "json_preflight_passed": True,
                    "serialized_request_bytes": len(serialized_request.encode("utf-8")),
                },
            )
            raise

        review_scope = request_payload.get("review_scope")
        review_scope = review_scope if isinstance(review_scope, Mapping) else {}
        page_role_ids = review_scope.get("page_role_review_source_unit_ids")
        page_role_count = len(page_role_ids) if isinstance(page_role_ids, list) else 0
        self.event_sink(
            "PDF_STRUCTURE_REFINEMENT_REQUEST_PREFLIGHT",
            _request_preflight_fields(
                spr,
                serialized_request,
                selected_page_count=len(images),
                page_role_review_count=page_role_count,
            ),
        )

        content: list[dict[str, object]] = [{
            "type": "input_text",
            "text": serialized_request,
        }]
        selection_reasons = request_payload.get("page_selection_reasons") or {}
        for source_unit_id in sorted(images):
            image_url = images[source_unit_id]
            if not isinstance(image_url, str) or not image_url.startswith("data:image/"):
                raise ValueError("page image resolver must return image data URLs")
            reasons = (
                selection_reasons.get(source_unit_id, [])
                if isinstance(selection_reasons, Mapping)
                else []
            )
            content.append({
                "type": "input_text",
                "text": (
                    f"Page image source_unit_id={source_unit_id}; "
                    f"selection_reasons={json.dumps(reasons)}"
                ),
            })
            content.append({"type": "input_image", "image_url": image_url, "detail": "high"})

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model_id,
            "instructions": _SYSTEM_INSTRUCTION,
            "input": [{"role": "user", "content": content}],
            "text": {"format": {
                "type": "json_schema", "name": "pdf_structure_refinement_patch",
                "strict": True, "schema": _PATCH_SCHEMA,
            }},
        }
        response = await self._post_with_retry(headers, payload)
        self.event_sink(
            "PDF_STRUCTURE_REFINEMENT_RESPONSE_RECEIVED",
            _response_diagnostic_fields(response),
        )

        try:
            output_text = _response_output_text(response)
        except ValueError as exc:
            self.event_sink(
                "PDF_STRUCTURE_REFINEMENT_RESPONSE_PARSE_FAILED",
                _parse_failure_fields(exc, stage="output_text_extraction"),
            )
            raise

        try:
            decoded = json.loads(output_text)
        except json.JSONDecodeError as exc:
            self.event_sink(
                "PDF_STRUCTURE_REFINEMENT_RESPONSE_PARSE_FAILED",
                _parse_failure_fields(exc, stage="json_decode"),
            )
            raise

        if not isinstance(decoded, Mapping):
            exc = StructureRefinementResponseError(
                "structured refinement output must be an object",
                stage="response_root_validation",
            )
            self.event_sink(
                "PDF_STRUCTURE_REFINEMENT_RESPONSE_PARSE_FAILED",
                _parse_failure_fields(exc, stage=exc.stage),
            )
            raise exc

        try:
            return parse_structure_refinement_response(
                decoded,
                model_id=self.model_id,
                prompt_version=self.prompt_version,
            )
        except StructureRefinementResponseError as exc:
            self.event_sink(
                "PDF_STRUCTURE_REFINEMENT_RESPONSE_PARSE_FAILED",
                _parse_failure_fields(exc, stage=exc.stage),
            )
            raise

    async def _post_with_retry(
        self,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        for attempt in range(1, self.max_attempts + 1):
            try:
                if self.http_post is None:
                    return await self.async_http_post(
                        self.endpoint, headers, payload, self.timeout_seconds
                    )
                return await asyncio.to_thread(
                    self.http_post,
                    self.endpoint,
                    headers,
                    payload,
                    self.timeout_seconds,
                )
            except StructureRefinementProviderError as exc:
                will_retry = exc.retryable and attempt < self.max_attempts
                self.event_sink(
                    "PDF_STRUCTURE_REFINEMENT_PROVIDER_FAILURE",
                    {
                        "attempt": attempt,
                        "max_attempts": self.max_attempts,
                        "retryable": exc.retryable,
                        "will_retry": will_retry,
                        "status_code": exc.status_code,
                        "error_type": type(exc).__name__,
                    },
                )
                if not will_retry:
                    raise
                delay = self._retry_delay(attempt, exc.retry_after_seconds)
                self.event_sink(
                    "PDF_STRUCTURE_REFINEMENT_PROVIDER_RETRY_SCHEDULED",
                    {
                        "attempt": attempt,
                        "next_attempt": attempt + 1,
                        "delay_ms": round(delay * 1000),
                        "status_code": exc.status_code,
                    },
                )
                await self.sleep(delay)
        raise AssertionError("provider retry loop exhausted without returning or raising")

    def _retry_delay(self, attempt: int, retry_after_seconds: float | None) -> float:
        exponential = min(
            self.max_backoff_seconds,
            self.initial_backoff_seconds * (2 ** (attempt - 1)),
        )
        if retry_after_seconds is None:
            return exponential
        return min(self.max_backoff_seconds, max(exponential, retry_after_seconds))

    def propose(self, spr: StructuredProcessingResultV2) -> StructureRefinementPatch:
        """Compatibility adapter for synchronous worker call sites."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.propose_async(spr))
        raise RuntimeError(
            "OpenAIResponsesStructureRefiner.propose() cannot run inside an active event loop; "
            "await propose_async() instead"
        )


def openai_structure_refiner_from_env(
    *,
    page_image_resolver: PageImageResolver | None = None,
    async_http_post: AsyncHttpPost = _default_async_http_post,
    http_post: HttpPost | None = None,
) -> OpenAIResponsesStructureRefiner | None:
    api_key = os.getenv("PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY", "").strip()
    model_id = os.getenv("PDF_STRUCTURE_REFINEMENT_OPENAI_MODEL", "").strip()
    if not api_key and not model_id:
        return None
    if not api_key or not model_id:
        raise ValueError("both PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY and _MODEL are required")
    endpoint = os.getenv(
        "PDF_STRUCTURE_REFINEMENT_OPENAI_ENDPOINT",
        "https://api.openai.com/v1/responses",
    ).strip()
    timeout_seconds = float(os.getenv("PDF_STRUCTURE_REFINEMENT_TIMEOUT_SECONDS", "60"))
    max_attempts = int(os.getenv("PDF_STRUCTURE_REFINEMENT_MAX_ATTEMPTS", "3"))
    initial_backoff_seconds = float(
        os.getenv("PDF_STRUCTURE_REFINEMENT_INITIAL_BACKOFF_SECONDS", "0.5")
    )
    max_backoff_seconds = float(
        os.getenv("PDF_STRUCTURE_REFINEMENT_MAX_BACKOFF_SECONDS", "8")
    )
    return OpenAIResponsesStructureRefiner(
        api_key=api_key,
        model_id=model_id,
        page_image_resolver=page_image_resolver,
        endpoint=endpoint,
        timeout_seconds=timeout_seconds,
        async_http_post=async_http_post,
        http_post=http_post,
        max_attempts=max_attempts,
        initial_backoff_seconds=initial_backoff_seconds,
        max_backoff_seconds=max_backoff_seconds,
    )


__all__ = [
    "AsyncHttpPost",
    "HttpPost",
    "OpenAIResponsesStructureRefiner",
    "PageImageResolver",
    "StructureRefinementProviderError",
    "openai_structure_refiner_from_env",
]
