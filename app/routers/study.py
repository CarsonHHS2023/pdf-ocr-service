"""Study Assistant v1 HTTP API."""
from __future__ import annotations

import json
from typing import Any, Literal, NoReturn

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, validator

from app import study_assistant

router = APIRouter(prefix="/api/study/v1", tags=["study-assistant"])

MAX_ITEMS = 100
MAX_QUESTION = 4000
MAX_NOTE = 4000
MAX_EXCERPT = 2000
MAX_CONTEXT_CHARS = 60000


def _error(status_code: int, code: str, message: str) -> NoReturn:
    raise HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _validate_anchor(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("source_anchor must be an object")
    kind = value.get("kind")
    allowed: dict[str, set[str]] = {
        "spatial": {"kind", "source_unit_id", "normalized_bbox"},
        "text_span": {"kind", "source_unit_id", "start", "end"},
        "temporal": {"kind", "source_unit_id", "start_ms", "end_ms"},
        "dom": {"kind", "source_unit_id", "path", "text_start", "text_end"},
    }
    if kind not in allowed or not set(value).issubset(allowed[kind]):
        raise ValueError("unsupported source_anchor")
    if kind == "spatial":
        bbox = value.get("normalized_bbox")
        if not isinstance(bbox, list) or len(bbox) != 4 or any(not isinstance(v, (int, float)) for v in bbox):
            raise ValueError("invalid spatial anchor")
    elif kind == "text_span":
        if not isinstance(value.get("start"), int) or not isinstance(value.get("end"), int) or value["start"] < 0 or value["end"] < value["start"]:
            raise ValueError("invalid text span anchor")
    elif kind == "temporal":
        if not isinstance(value.get("start_ms"), int) or not isinstance(value.get("end_ms"), int) or value["start_ms"] < 0 or value["end_ms"] < value["start_ms"]:
            raise ValueError("invalid temporal anchor")
    elif kind == "dom":
        if not isinstance(value.get("path"), str) or not value["path"].strip():
            raise ValueError("invalid dom anchor")
    return value


class StudyContextItem(BaseModel):
    kind: Literal["bookmark", "note", "highlight"]
    item_id: str = Field(..., min_length=1, max_length=300)
    node_id: str = Field(..., min_length=1, max_length=300)
    source_unit_id: str | None = Field(default=None, max_length=300)
    source_anchor: dict[str, Any] | None = None
    note_text: str | None = Field(default=None, max_length=MAX_NOTE)
    excerpt: str | None = Field(default=None, max_length=MAX_EXCERPT)
    text_start: int | None = Field(default=None, ge=0)
    text_end: int | None = Field(default=None, ge=0)
    highlight_style: str | None = Field(default=None, max_length=32)

    _anchor = validator("source_anchor", allow_reuse=True)(_validate_anchor)

    class Config:
        extra = "forbid"


class StudyAskRequest(BaseModel):
    contract: Literal["reader-study-context"]
    version: Literal[1]
    document_ref: str = Field(..., min_length=1, max_length=300)
    candidate_id: str = Field(..., min_length=1, max_length=300)
    reader_contract_version: Literal["2"]
    candidate_schema_id: str = Field(..., min_length=1, max_length=300)
    candidate_schema_version: Literal[2]
    question: str = Field(..., min_length=1, max_length=MAX_QUESTION)
    items: list[StudyContextItem] = Field(default_factory=list, max_items=MAX_ITEMS)

    class Config:
        extra = "forbid"


class StudyAskResponse(BaseModel):
    contract: Literal["study-assistant-answer"] = "study-assistant-answer"
    version: Literal[1] = 1
    answer: str
    source_item_ids: list[str] = Field(default_factory=list)
    model: Literal["configured-provider"] = "configured-provider"


@router.post("/ask", response_model=StudyAskResponse)
def ask_study_assistant(request: StudyAskRequest) -> StudyAskResponse:
    item_ids = [item.item_id for item in request.items]
    if len(set(item_ids)) != len(item_ids):
        _error(status.HTTP_422_UNPROCESSABLE_ENTITY, "study_context_invalid", "StudyContext item IDs must be unique.")

    context_items = [item.dict(exclude_none=True) for item in request.items]
    total_chars = len(request.question) + len(json.dumps(context_items, ensure_ascii=False, separators=(",", ":")))
    if total_chars > MAX_CONTEXT_CHARS:
        _error(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "study_context_too_large", "StudyContext is too large.")

    try:
        answer, source_ids = study_assistant.ask_provider(request.question, context_items)
    except study_assistant.StudyAssistantNotConfigured:
        _error(status.HTTP_503_SERVICE_UNAVAILABLE, "study_assistant_not_configured", "Study Assistant is not configured.")
    except study_assistant.StudyAssistantUnavailable:
        _error(status.HTTP_503_SERVICE_UNAVAILABLE, "study_assistant_unavailable", "Study Assistant is temporarily unavailable.")
    except study_assistant.StudyAssistantMalformedResponse:
        _error(status.HTTP_502_BAD_GATEWAY, "study_assistant_bad_response", "Study Assistant returned an invalid response.")

    return StudyAskResponse(answer=answer, source_item_ids=source_ids)
