from dataclasses import dataclass
from enum import Enum

class ProviderErrorCategory(str, Enum):
    CONFIGURATION="configuration_error"; AUTHENTICATION="authentication_error"; VALIDATION="validation_request_error"; CONFLICT="submission_conflict"; UNAVAILABLE="provider_unavailable"; TIMEOUT="timeout"; JOB_NOT_FOUND="job_not_found"; RESULT_NOT_READY="result_not_ready"; RESULT_EXPIRED="result_expired"; ARTIFACT_MISSING="artifact_missing_expired"; EXECUTION_FAILED="provider_execution_failure"; MALFORMED_RESPONSE="malformed_provider_response"; UNEXPECTED="unexpected_provider_error"

@dataclass
class ProviderErrorDetail:
    category: ProviderErrorCategory
    safe_message: str
    http_status: int|None=None
    provider_code: str|None=None
    retryable: bool=False
    provider_job_id: str|None=None
    provider_request_id: str|None=None

class ProviderClientError(Exception):
    def __init__(self, detail: ProviderErrorDetail):
        self.detail=detail
        super().__init__(f"{detail.category.value}: {detail.safe_message}")
