from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

class ProcessingRunStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass(frozen=True, slots=True)
class ProcessingRunCreate:
    processing_run_ref: str
    document_ref: str
    source_file_ref: str | None = None
    status: ProcessingRunStatus | str = ProcessingRunStatus.CREATED
    provider_ref: str | None = None
    provider_model_ref: str | None = None
    processing_policy_ref: str | None = None
    idempotency_key: str | None = None
    raw_result_ref: str | None = None
    structured_processing_result_ref: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    safe_error_code: str | None = None
    safe_error_summary: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    extensions: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class ProcessingRunState:
    processing_run_ref: str
    document_ref: str
    source_file_ref: str | None
    status: str
    provider_ref: str | None
    provider_model_ref: str | None
    processing_policy_ref: str | None
    idempotency_key: str | None
    raw_result_ref: str | None
    structured_processing_result_ref: str | None
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    safe_error_code: str | None
    safe_error_summary: str | None
    metrics: dict[str, Any]
    extensions: dict[str, Any]
    created_at: datetime

@dataclass(frozen=True, slots=True)
class ProcessingRunSummary:
    processing_run_ref: str
    document_ref: str
    source_file_ref: str | None
    status: str
    provider_ref: str | None
    provider_model_ref: str | None
    processing_policy_ref: str | None
    raw_result_ref: str | None
    structured_processing_result_ref: str | None
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    created_at: datetime
