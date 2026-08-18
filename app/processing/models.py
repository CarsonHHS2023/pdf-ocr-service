from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

class ProviderLifecycleStatus(str, Enum):
    QUEUED="queued"; RUNNING="running"; PROVIDER_COMPLETED="provider_completed"; PROVIDER_PARTIAL_FAILED="provider_partial_failed"; FAILED="failed"; EXPIRED="expired"

@dataclass(frozen=True)
class ProviderProgress:
    pages_total:int|None=None; pages_completed:int|None=None; tasks_total:int|None=None; tasks_completed:int|None=None; percent_complete:float|None=None; provider_execution_complete:bool=False

@dataclass(frozen=True)
class ProviderSubmission:
    job_id:str; request_id:str|None; status:ProviderLifecycleStatus; poll_url:str|None=None; result_url:str|None=None; raw_provider_payload:dict[str,Any]|None=None

@dataclass(frozen=True)
class ProviderJobStatus:
    job_id:str; request_id:str|None; status:ProviderLifecycleStatus; result_ready:bool; progress:ProviderProgress; error:Any=None; raw_provider_payload:dict[str,Any]|None=None

@dataclass(frozen=True)
class ProviderResult:
    job_id:str; request_id:str|None; status:ProviderLifecycleStatus; profile:str; result_artifact:dict[str,Any]|None; documents:list[dict[str,Any]]=field(default_factory=list); raw_provider_payload:dict[str,Any]|None=None

@dataclass(frozen=True)
class ArtifactMetadata:
    artifact_id:str|None=None; download_endpoint:str|None=None; format:str|None=None; compression:str|None=None; size_bytes:int|None=None; sha256:str|None=None

@dataclass(frozen=True)
class ProviderArtifact:
    job_id:str; content:bytes; metadata:ArtifactMetadata

@dataclass(frozen=True)
class ProcessingPageIdentity:
    document_id:str; page_number:int; page_index:int; local_page_index:int; source_page_range:tuple[int,int]

class DocumentProcessingProvider(Protocol):
    async def submit_job(self, request): ...
    async def get_job_status(self, job_id:str): ...
    async def get_job_result(self, job_id:str, profile:str|None=None): ...
    async def get_job_artifact(self, job_id:str, metadata:ArtifactMetadata|None=None): ...
