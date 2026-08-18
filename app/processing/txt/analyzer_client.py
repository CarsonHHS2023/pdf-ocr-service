"""OpenAI Responses API client for bounded TXT structure analysis.

The network model classifies structure over exact retained-source lines but never
owns canonical text or identity. Requests use the same OpenAI Responses API +
strict JSON-schema family as PDF refinement. Dynamic source line IDs are encoded
as required JSON object keys in the schema, so the model cannot omit, duplicate,
or invent identities that the backend owns.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable

import httpx

from app.processing.txt.structure_recovery import (
    TxtHeadingLevelAssignment,
    TxtLineStructureAssignment,
    TxtOutlineAnalysisWindow,
    TxtOutlineWindowResult,
    TxtStructureAnalysisWindow,
    TxtStructureKind,
    TxtStructureRecoveryError,
    TxtStructureWindowResult,
)


class TxtStructureAnalyzerClientError(RuntimeError):
    """Bounded provider/contract failure safe for logging and user classification."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        stage: str = "provider_request",
        contract_reason: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.stage = stage
        self.contract_reason = contract_reason


@dataclass(frozen=True, slots=True)
class OpenAICompatibleTxtAnalyzerConfig:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: float = 30.0
    # Retained for configuration compatibility with the draft PR. The Responses
    # request intentionally does not send temperature for GPT-5.6-class models.
    temperature: float = 0.0
    max_attempts: int = 3
    retry_backoff_seconds: float = 0.5

    def __post_init__(self) -> None:
        for value, name in ((self.base_url, "base_url"), (self.api_key, "api_key"), (self.model, "model")):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not self.base_url.startswith(("https://", "http://")):
            raise ValueError("base_url must be HTTP(S)")
        if not isinstance(self.timeout_seconds, (int, float)) or isinstance(self.timeout_seconds, bool) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not isinstance(self.temperature, (int, float)) or isinstance(self.temperature, bool) or self.temperature < 0:
            raise ValueError("temperature must be nonnegative")
        if not isinstance(self.max_attempts, int) or isinstance(self.max_attempts, bool) or self.max_attempts <= 0:
            raise ValueError("max_attempts must be a positive integer")
        if (
            not isinstance(self.retry_backoff_seconds, (int, float))
            or isinstance(self.retry_backoff_seconds, bool)
            or self.retry_backoff_seconds < 0
        ):
            raise ValueError("retry_backoff_seconds must be nonnegative")


TransportFactory = Callable[..., httpx.Client]
SleepFunction = Callable[[float], None]


def _retryable_status(status_code: int) -> bool:
    return status_code in {408, 409, 429} or status_code >= 500


class OpenAICompatibleTxtStructureAnalyzer:
    def __init__(
        self,
        config: OpenAICompatibleTxtAnalyzerConfig,
        *,
        client_factory: TransportFactory = httpx.Client,
        sleep: SleepFunction = time.sleep,
    ) -> None:
        self.config = config
        self.client_factory = client_factory
        self.sleep = sleep

    def _backoff(self, attempt_number: int) -> None:
        delay = self.config.retry_backoff_seconds * (2 ** max(0, attempt_number - 1))
        if delay > 0:
            self.sleep(delay)

    def _request(self, payload: dict[str, Any]) -> Any:
        url = self.config.base_url.rstrip("/") + "/responses"
        for attempt in range(1, self.config.max_attempts + 1):
            try:
                with self.client_factory(timeout=self.config.timeout_seconds) as client:
                    response = client.post(
                        url,
                        headers={
                            "Authorization": f"Bearer {self.config.api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                    response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                status_code = int(exc.response.status_code)
                retryable = _retryable_status(status_code)
                if retryable and attempt < self.config.max_attempts:
                    self._backoff(attempt)
                    continue
                raise TxtStructureAnalyzerClientError(
                    f"TXT structure provider HTTP {status_code}",
                    status_code=status_code,
                    retryable=retryable,
                    stage="provider_http",
                ) from exc
            except httpx.RequestError as exc:
                if attempt < self.config.max_attempts:
                    self._backoff(attempt)
                    continue
                raise TxtStructureAnalyzerClientError(
                    "TXT structure provider unavailable",
                    retryable=True,
                    stage="provider_transport",
                ) from exc
            except Exception as exc:
                raise TxtStructureAnalyzerClientError(
                    "TXT structure analyzer request failed",
                    stage="provider_runtime",
                ) from exc

            try:
                return response.json()
            except Exception as exc:
                raise TxtStructureAnalyzerClientError(
                    "TXT structure analyzer response was malformed",
                    status_code=getattr(response, "status_code", None),
                    stage="provider_json",
                ) from exc
        raise TxtStructureAnalyzerClientError("TXT structure analyzer request failed")  # pragma: no cover

    def analyze(self, window: TxtStructureAnalysisWindow) -> TxtStructureWindowResult:
        if not isinstance(window, TxtStructureAnalysisWindow):
            raise TypeError("window must be a TxtStructureAnalysisWindow")
        return _parse_response(window, self._request(_request_payload(window, self.config)))

    def reconcile_outline(self, window: TxtOutlineAnalysisWindow) -> TxtOutlineWindowResult:
        if not isinstance(window, TxtOutlineAnalysisWindow):
            raise TypeError("window must be a TxtOutlineAnalysisWindow")
        return _parse_outline_response(
            window,
            self._request(_outline_request_payload(window, self.config)),
        )


def _structure_assignment_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "starts_new_node", "heading_level"],
        "properties": {
            "kind": {"type": "string", "enum": [kind.value for kind in TxtStructureKind]},
            "starts_new_node": {"type": "boolean"},
            "heading_level": {"type": ["integer", "null"], "minimum": 1, "maximum": 6},
        },
    }


def _structure_response_schema(window: TxtStructureAnalysisWindow) -> dict[str, Any]:
    line_ids = [line.line_id for line in window.lines if not line.is_empty]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["assignments"],
        "properties": {
            "assignments": {
                "type": "object",
                "additionalProperties": False,
                "required": line_ids,
                "properties": {
                    line_id: {"$ref": "#/$defs/structure_assignment"}
                    for line_id in line_ids
                },
            },
        },
        "$defs": {"structure_assignment": _structure_assignment_schema()},
    }


def _outline_assignment_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["heading_level"],
        "properties": {
            "heading_level": {"type": "integer", "minimum": 1, "maximum": 6},
        },
    }


def _outline_response_schema(window: TxtOutlineAnalysisWindow) -> dict[str, Any]:
    line_ids = [candidate.line_id for candidate in window.candidates]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["assignments"],
        "properties": {
            "assignments": {
                "type": "object",
                "additionalProperties": False,
                "required": line_ids,
                "properties": {
                    line_id: {"$ref": "#/$defs/outline_assignment"}
                    for line_id in line_ids
                },
            },
        },
        "$defs": {"outline_assignment": _outline_assignment_schema()},
    }


def _request_payload(window: TxtStructureAnalysisWindow, config: OpenAICompatibleTxtAnalyzerConfig) -> dict[str, Any]:
    allowed_kinds = [kind.value for kind in TxtStructureKind]
    source_lines = [
        {"line_id": line.line_id, "text": line.text, "is_empty": line.is_empty}
        for line in window.lines
    ]
    instructions = (
        "Classify document structure for each non-empty source line. "
        "Never rewrite, normalize, summarize, or return source text. "
        "The assignments object keys are fixed source line IDs supplied by the response schema; "
        "fill the value for every required key and do not invent identity. Each value contains "
        "kind, starts_new_node, and heading_level (integer 1..6 or null). "
        "Empty lines are context only and have no assignment key. "
        f"Allowed kind values: {', '.join(allowed_kinds)}. "
        "heading requires heading_level 1 through 6; title must use heading_level=1; "
        "all other kinds require heading_level=null. "
        "Use starts_new_node=false only when this physical source line clearly continues "
        "the same semantic node from the immediately preceding non-empty line."
    )
    user = json.dumps(
        {"window_id": window.window_id, "lines": source_lines},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return {
        "model": config.model,
        "instructions": instructions,
        "input": [{"role": "user", "content": [{"type": "input_text", "text": user}]}],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "txt_structure_assignments",
                "strict": True,
                "schema": _structure_response_schema(window),
            }
        },
    }


def _outline_request_payload(
    window: TxtOutlineAnalysisWindow,
    config: OpenAICompatibleTxtAnalyzerConfig,
) -> dict[str, Any]:
    candidates = [
        {
            "line_id": candidate.line_id,
            "kind": candidate.kind.value,
            "proposed_heading_level": candidate.proposed_heading_level,
            "text": candidate.text,
        }
        for candidate in window.candidates
    ]
    instructions = (
        "Reconcile the heading hierarchy for this ordered document outline. Every input "
        "candidate is already classified as title or heading. The assignments object keys are "
        "fixed candidate line IDs supplied by the response schema; fill every required key with "
        "only heading_level 1 through 6. A document title must remain level 1. Use numbering "
        "patterns, chapter/section consistency, neighboring outline entries, and the whole supplied "
        "outline window to correct locally inconsistent levels. Never return, rewrite, normalize, "
        "summarize, or correct source text. Do not create, delete, reclassify, merge, or parent nodes; "
        "the backend reconstructs parentage."
    )
    user = json.dumps(
        {"window_id": window.window_id, "outline_candidates": candidates},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return {
        "model": config.model,
        "instructions": instructions,
        "input": [{"role": "user", "content": [{"type": "input_text", "text": user}]}],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "txt_outline_heading_levels",
                "strict": True,
                "schema": _outline_response_schema(window),
            }
        },
    }


def _response_output_text(body: Any) -> str:
    if not isinstance(body, dict):
        raise TxtStructureAnalyzerClientError(
            "TXT structure analyzer response was malformed",
            stage="provider_output",
        )
    direct = body.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    output = body.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if (
                    isinstance(part, dict)
                    and part.get("type") in {"output_text", "text"}
                    and isinstance(part.get("text"), str)
                    and part["text"].strip()
                ):
                    return part["text"]
    raise TxtStructureAnalyzerClientError(
        "TXT structure analyzer response did not contain output text",
        stage="provider_output",
    )


def _single_response_json(body: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(_response_output_text(body))
    except TxtStructureAnalyzerClientError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TxtStructureAnalyzerClientError(
            "TXT structure analyzer response was malformed",
            stage="provider_output_json",
        ) from exc
    if not isinstance(parsed, dict) or set(parsed) != {"assignments"}:
        raise TxtStructureAnalyzerClientError(
            "TXT structure analyzer response was malformed",
            stage="provider_output_contract",
        )
    if not isinstance(parsed["assignments"], dict):
        raise TxtStructureAnalyzerClientError(
            "TXT structure analyzer response was malformed",
            stage="provider_output_contract",
        )
    return parsed


def _contract_failure(stage: str, reason: str, exc: BaseException | None = None) -> TxtStructureAnalyzerClientError:
    error = TxtStructureAnalyzerClientError(
        "TXT structure analyzer response was malformed",
        stage=stage,
        contract_reason=reason,
    )
    if exc is not None:
        error.__cause__ = exc
    return error


def _parse_response(window: TxtStructureAnalysisWindow, body: Any) -> TxtStructureWindowResult:
    try:
        parsed = _single_response_json(body)
        assignments_by_id = parsed["assignments"]
        expected_lines = [line for line in window.lines if not line.is_empty]
        expected_ids = [line.line_id for line in expected_lines]
        if set(assignments_by_id) != set(expected_ids) or len(assignments_by_id) != len(expected_ids):
            raise _contract_failure("local_structure_contract", "identity_set_mismatch")

        assignments: list[TxtLineStructureAssignment] = []
        allowed_fields = {"kind", "starts_new_node", "heading_level"}
        for line in expected_lines:
            raw = assignments_by_id[line.line_id]
            if not isinstance(raw, dict) or set(raw) != allowed_fields:
                raise _contract_failure("local_structure_contract", "assignment_shape")
            try:
                kind = TxtStructureKind(raw["kind"])
                assignment = TxtLineStructureAssignment(
                    line_id=line.line_id,
                    kind=kind,
                    starts_new_node=raw["starts_new_node"],
                    heading_level=raw["heading_level"],
                )
            except (KeyError, TypeError, ValueError, TxtStructureRecoveryError) as exc:
                raise _contract_failure("local_structure_contract", "assignment_semantics", exc) from exc
            assignments.append(assignment)
        return TxtStructureWindowResult(window.window_id, tuple(assignments))
    except TxtStructureAnalyzerClientError:
        raise
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, TxtStructureRecoveryError) as exc:
        raise _contract_failure("local_structure_contract", "unexpected_contract_failure", exc) from exc


def _parse_outline_response(window: TxtOutlineAnalysisWindow, body: Any) -> TxtOutlineWindowResult:
    try:
        parsed = _single_response_json(body)
        assignments_by_id = parsed["assignments"]
        expected_ids = [candidate.line_id for candidate in window.candidates]
        if set(assignments_by_id) != set(expected_ids) or len(assignments_by_id) != len(expected_ids):
            raise _contract_failure("outline_contract", "identity_set_mismatch")

        candidate_kind = {candidate.line_id: candidate.kind for candidate in window.candidates}
        assignments: list[TxtHeadingLevelAssignment] = []
        for line_id in expected_ids:
            raw = assignments_by_id[line_id]
            if not isinstance(raw, dict) or set(raw) != {"heading_level"}:
                raise _contract_failure("outline_contract", "assignment_shape")
            try:
                assignment = TxtHeadingLevelAssignment(
                    line_id=line_id,
                    heading_level=raw["heading_level"],
                )
            except (KeyError, TypeError, ValueError, TxtStructureRecoveryError) as exc:
                raise _contract_failure("outline_contract", "assignment_semantics", exc) from exc
            if candidate_kind[line_id] is TxtStructureKind.TITLE and assignment.heading_level != 1:
                raise _contract_failure("outline_contract", "title_level")
            assignments.append(assignment)
        return TxtOutlineWindowResult(window.window_id, tuple(assignments))
    except TxtStructureAnalyzerClientError:
        raise
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, TxtStructureRecoveryError) as exc:
        raise _contract_failure("outline_contract", "unexpected_contract_failure", exc) from exc


__all__ = [
    "OpenAICompatibleTxtAnalyzerConfig",
    "OpenAICompatibleTxtStructureAnalyzer",
    "TxtStructureAnalyzerClientError",
]
