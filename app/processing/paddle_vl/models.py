from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse
from app.processing.errors import ProviderClientError, ProviderErrorDetail, ProviderErrorCategory

SCHEMA_VERSION="2026-07-10"

def _non_empty(v,n):
    if not v or not str(v).strip():
        raise ProviderClientError(ProviderErrorDetail(ProviderErrorCategory.VALIDATION,f"{n} must be non-empty"))

@dataclass(frozen=True)
class PaddleVLOptions:
    batch_size:int=50; max_concurrent_workers:int=5; fail_fast:bool=False; ttl_seconds:int=3600; pdf_download_timeout_seconds:float|None=None; max_pdf_bytes:int|None=None
    def to_provider_json(self):
        d={"batch_size":self.batch_size,"max_concurrent_workers":self.max_concurrent_workers,"fail_fast":self.fail_fast,"ttl_seconds":self.ttl_seconds}
        if self.pdf_download_timeout_seconds is not None: d["pdf_download_timeout_seconds"]=self.pdf_download_timeout_seconds
        if self.max_pdf_bytes is not None: d["max_pdf_bytes"]=self.max_pdf_bytes
        for k,v in d.items():
            if isinstance(v,(int,float)) and not isinstance(v,bool) and v<=0: raise ProviderClientError(ProviderErrorDetail(ProviderErrorCategory.VALIDATION,f"{k} must be positive"))
        return d

@dataclass(frozen=True)
class PaddleVLDocument:
    document_id:str; pdf_source_url:str=field(repr=False); pdf_source_etag:str|None=None; pdf_source_sha256:str|None=None
    def to_provider_json(self):
        _non_empty(self.document_id,"document_id")
        if urlparse(self.pdf_source_url).scheme != "https": raise ProviderClientError(ProviderErrorDetail(ProviderErrorCategory.VALIDATION,"pdf_source_url must use HTTPS"))
        if self.pdf_source_sha256 is not None and (len(self.pdf_source_sha256)!=64 or any(c not in '0123456789abcdefABCDEF' for c in self.pdf_source_sha256)):
            raise ProviderClientError(ProviderErrorDetail(ProviderErrorCategory.VALIDATION,"pdf_source_sha256 must be a 64-character SHA-256 hex digest"))
        d={"document_id":self.document_id,"pdf_source_url":self.pdf_source_url}
        if self.pdf_source_etag is not None: d["pdf_source_etag"]=self.pdf_source_etag
        if self.pdf_source_sha256 is not None: d["pdf_source_sha256"]=self.pdf_source_sha256
        return d

@dataclass(frozen=True)
class PaddleVLJobRequest:
    job_id:str; request_id:str|None; documents:list[PaddleVLDocument]; schema_version:str=SCHEMA_VERSION; options:PaddleVLOptions=field(default_factory=PaddleVLOptions)
    def to_provider_json(self):
        _non_empty(self.job_id,"job_id")
        if self.request_id is not None: _non_empty(self.request_id,"request_id")
        if len(self.documents)!=1: raise ProviderClientError(ProviderErrorDetail(ProviderErrorCategory.VALIDATION,"exactly one document is supported for the initial adapter"))
        d={"schema_version":self.schema_version,"job_id":self.job_id,"request_id":self.request_id,"documents":[x.to_provider_json() for x in self.documents],"options":self.options.to_provider_json()}
        return d
