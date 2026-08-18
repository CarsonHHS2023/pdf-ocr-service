"""Bounded server-side Study Assistant gateway for StudyContext v1."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable

import httpx


class StudyAssistantError(RuntimeError): pass
class StudyAssistantNotConfigured(StudyAssistantError): pass
class StudyAssistantUnavailable(StudyAssistantError): pass
class StudyAssistantMalformedResponse(StudyAssistantError): pass


@dataclass(frozen=True, slots=True)
class StudyAssistantConfig:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: float = 30.0
    temperature: float = 0.0
    max_output_tokens: int = 800

    @classmethod
    def from_env(cls) -> "StudyAssistantConfig":
        base_url = os.getenv("ATLAS_STUDY_LLM_API_BASE_URL", "").strip()
        api_key = os.getenv("ATLAS_STUDY_LLM_API_KEY", "").strip()
        model = os.getenv("ATLAS_STUDY_LLM_MODEL", "").strip()
        if not base_url or not api_key or not model:
            raise StudyAssistantNotConfigured("Study Assistant is not configured")
        try:
            return cls(
                base_url=base_url,
                api_key=api_key,
                model=model,
                timeout_seconds=float(os.getenv("ATLAS_STUDY_LLM_TIMEOUT_SECONDS", "30")),
                temperature=float(os.getenv("ATLAS_STUDY_LLM_TEMPERATURE", "0")),
                max_output_tokens=int(os.getenv("ATLAS_STUDY_LLM_MAX_OUTPUT_TOKENS", "800")),
            )
        except (TypeError, ValueError) as exc:
            raise StudyAssistantNotConfigured("Study Assistant configuration is invalid") from exc


ClientFactory = Callable[..., httpx.Client]


def build_messages(question: str, items: list[dict[str, Any]]) -> list[dict[str, str]]:
    system = (
        "You are a document study assistant. Answer document-specific questions only from the supplied StudyContext. "
        "If the context is insufficient, say so clearly. Distinguish user-authored notes from source excerpts. "
        "Do not invent quotations or page numbers. Return JSON only with keys answer and source_item_ids. "
        "source_item_ids must contain only item_id values from the supplied context that support the answer."
    )
    user = json.dumps({"question": question, "study_context_items": items}, ensure_ascii=False, separators=(",", ":"))
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def ask_provider(question: str, items: list[dict[str, Any]], *, config: StudyAssistantConfig | None = None,
                 client_factory: ClientFactory = httpx.Client) -> tuple[str, list[str]]:
    cfg = config or StudyAssistantConfig.from_env()
    payload = {
        "model": cfg.model,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_output_tokens,
        "response_format": {"type": "json_object"},
        "messages": build_messages(question, items),
    }
    try:
        with client_factory(timeout=cfg.timeout_seconds) as client:
            response = client.post(
                cfg.base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
    except (httpx.TimeoutException, httpx.RequestError, httpx.HTTPStatusError) as exc:
        raise StudyAssistantUnavailable("Study Assistant provider is unavailable") from exc
    except Exception as exc:
        raise StudyAssistantUnavailable("Study Assistant provider request failed") from exc

    try:
        choices = body["choices"]
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError("choice count")
        content = choices[0]["message"]["content"]
        parsed = json.loads(content)
        if not isinstance(parsed, dict) or set(parsed) != {"answer", "source_item_ids"}:
            raise ValueError("response shape")
        answer = parsed["answer"]
        source_ids = parsed["source_item_ids"]
        allowed = {str(item["item_id"]) for item in items}
        if not isinstance(answer, str) or not answer.strip() or len(answer) > 12000:
            raise ValueError("answer")
        if not isinstance(source_ids, list) or any(not isinstance(v, str) or v not in allowed for v in source_ids):
            raise ValueError("source ids")
        return answer.strip(), list(dict.fromkeys(source_ids))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise StudyAssistantMalformedResponse("Study Assistant provider response was malformed") from exc
