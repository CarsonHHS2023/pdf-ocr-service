"""Surface bounded provider-result and remap diagnostics in hosted test logs."""
from __future__ import annotations

from pathlib import Path


def _replace_once(path: Path, old: str, new: str, *, label: str) -> None:
    source = path.read_text(encoding="utf-8")
    if new in source:
        return
    if source.count(old) != 1:
        raise RuntimeError(f"Could not find unique {label} in {path}")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


def _patch_processing_log_handler() -> None:
    path = Path("app/processing/__init__.py")
    old = '''install_refinement_provider_stderr_handler()

__all__ = ["install_refinement_provider_stderr_handler"]
'''
    new = '''install_refinement_provider_stderr_handler()

_BOUNDED_RUNTIME_EVENT_PREFIXES = (
    "PDF_PAGE_",
    "PDF_PROVIDER_",
    "PDF_CANONICALIZATION_",
    "PDF_OPENCV_",
    "PDF_ORCHESTRATION_",
    "PDF_INTEGRATION_",
)
_BOUNDED_RUNTIME_MESSAGE_PREFIXES = (
    "Production PDF ingestion failed ",
    "PDF canonicalization failed ",
)
_BOUNDED_RUNTIME_STDERR_HANDLER_MARKER = "_atlas_pdf_runtime_stderr"


class _BoundedPdfRuntimeFilter(logging.Filter):
    """Surface only bounded PDF lifecycle fields, never request data or secrets."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return message.startswith(_BOUNDED_RUNTIME_EVENT_PREFIXES) or message.startswith(
            _BOUNDED_RUNTIME_MESSAGE_PREFIXES
        )


def install_bounded_pdf_runtime_stderr_handler() -> None:
    logger = logging.getLogger("uvicorn.error")
    if any(
        getattr(handler, _BOUNDED_RUNTIME_STDERR_HANDLER_MARKER, False)
        for handler in logger.handlers
    ):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(_BoundedPdfRuntimeFilter())
    setattr(handler, _BOUNDED_RUNTIME_STDERR_HANDLER_MARKER, True)
    logger.addHandler(handler)


install_bounded_pdf_runtime_stderr_handler()

__all__ = [
    "install_bounded_pdf_runtime_stderr_handler",
    "install_refinement_provider_stderr_handler",
]
'''
    _replace_once(path, old, new, label="bounded PDF runtime handler anchor")


def _patch_presentation_result_remap() -> None:
    path = Path("app/processing/pdf_page_presentation_bridge.py")
    old = '''        async def get_job_result(self, job_id: str, profile: str | None = None):
            result = await self._delegate.get_job_result(job_id, profile)
            documents = _remap_documents(
                result.documents or [],
                self._provider_input,
            )
            raw_payload = result.raw_provider_payload
            if isinstance(raw_payload, Mapping):
                raw_payload = _remap_payload(
                    raw_payload,
                    self._provider_input,
                )
            return replace(
                result,
                documents=documents,
                raw_provider_payload=raw_payload,
            )
'''
    new = '''        async def get_job_result(self, job_id: str, profile: str | None = None):
            provider_input = self._provider_input
            _diagnostic(
                "PDF_PROVIDER_RESULT_FETCH_STARTED",
                job_id=job_id,
                profile=profile,
                provider_page_count=provider_input.provider_page_count,
                provider_page_map_count=len(provider_input.provider_page_map),
            )
            try:
                result = await self._delegate.get_job_result(job_id, profile)
            except Exception as exc:
                _diagnostic(
                    "PDF_PROVIDER_RESULT_STAGE_FAILED",
                    stage="fetch",
                    error_type=type(exc).__name__,
                    provider_page_count=provider_input.provider_page_count,
                    provider_page_map_count=len(provider_input.provider_page_map),
                )
                raise

            raw_payload = result.raw_provider_payload
            raw_documents = (
                raw_payload.get("documents")
                if isinstance(raw_payload, Mapping)
                else None
            )
            _diagnostic(
                "PDF_PROVIDER_RESULT_RECEIVED",
                status=getattr(result.status, "value", result.status),
                profile=result.profile,
                documents_count=len(result.documents or []),
                raw_payload_documents_count=(
                    len(raw_documents) if isinstance(raw_documents, list) else 0
                ),
                result_artifact_present=bool(result.result_artifact),
                provider_page_count=provider_input.provider_page_count,
                provider_page_map_count=len(provider_input.provider_page_map),
            )
            try:
                documents = _remap_documents(
                    result.documents or [],
                    provider_input,
                )
            except Exception as exc:
                _diagnostic(
                    "PDF_PROVIDER_RESULT_STAGE_FAILED",
                    stage="documents_remap",
                    error_type=type(exc).__name__,
                    documents_count=len(result.documents or []),
                    provider_page_count=provider_input.provider_page_count,
                    provider_page_map_count=len(provider_input.provider_page_map),
                )
                raise

            if isinstance(raw_payload, Mapping):
                try:
                    raw_payload = _remap_payload(raw_payload, provider_input)
                except Exception as exc:
                    _diagnostic(
                        "PDF_PROVIDER_RESULT_STAGE_FAILED",
                        stage="raw_payload_remap",
                        error_type=type(exc).__name__,
                        raw_payload_documents_count=(
                            len(raw_documents)
                            if isinstance(raw_documents, list)
                            else 0
                        ),
                        provider_page_count=provider_input.provider_page_count,
                        provider_page_map_count=len(provider_input.provider_page_map),
                    )
                    raise
            _diagnostic(
                "PDF_PROVIDER_RESULT_REMAP_COMPLETED",
                documents_count=len(documents),
                original_page_count=int(
                    provider_input.presentation_manifest.get("page_count") or 0
                ),
                provider_page_count=provider_input.provider_page_count,
            )
            return replace(
                result,
                documents=documents,
                raw_provider_payload=raw_payload,
            )
'''
    _replace_once(path, old, new, label="presentation result remap method")


def _patch_orchestration_stages() -> None:
    path = Path("app/processing/orchestration.py")
    _replace_once(
        path,
        "import re\n",
        "import re\nimport sys\n",
        label="orchestration sys import",
    )
    old = '''            page_summary = _page_summary(request, result)
            phase = OrchestrationPhase.DOWNLOADING_ARTIFACT if result.result_artifact else OrchestrationPhase.INGESTING_RAW_RESULT
            raw = await self._ingest(request, result, page_summary)
'''
    new = '''            try:
                page_summary = _page_summary(request, result)
            except Exception as exc:
                print(
                    "PDF_ORCHESTRATION_STAGE_FAILED "
                    f"stage=page_summary error_type={type(exc).__name__} "
                    f"provider_job_id={request.provider_job_id} "
                    f"documents_count={len(result.documents or [])}",
                    file=sys.stderr,
                    flush=True,
                )
                raise
            phase = OrchestrationPhase.DOWNLOADING_ARTIFACT if result.result_artifact else OrchestrationPhase.INGESTING_RAW_RESULT
            try:
                raw = await self._ingest(request, result, page_summary)
            except Exception as exc:
                print(
                    "PDF_ORCHESTRATION_STAGE_FAILED "
                    f"stage=raw_result_ingest error_type={type(exc).__name__} "
                    f"provider_job_id={request.provider_job_id} "
                    f"evidence_kind={'artifact' if result.result_artifact else 'inline'}",
                    file=sys.stderr,
                    flush=True,
                )
                raise
'''
    _replace_once(path, old, new, label="orchestration page-summary and ingest stages")


def _patch_ingestion_failure_summary() -> None:
    path = Path("app/processing/pdf_ingestion.py")
    old = '''        print(
            "PDF_INGESTION_UNHANDLED_FAILURE "
            f"document_id={document_id} processing_attempt_id={ids.processing_attempt_id} "
            f"error_type={type(exc).__name__}",
            file=sys.stderr,
            flush=True,
        )
'''
    new = '''        integration_category = getattr(getattr(exc, "category", None), "value", None)
        orchestration_error = getattr(exc, "orchestration_error", None)
        orchestration_category = getattr(
            getattr(orchestration_error, "category", None),
            "value",
            None,
        )
        orchestration_phase = getattr(
            getattr(orchestration_error, "phase", None),
            "value",
            None,
        )
        grant_final_state = getattr(
            getattr(exc, "grant_final_state", None),
            "value",
            None,
        )
        print(
            "PDF_INGESTION_UNHANDLED_FAILURE "
            f"document_id={document_id} processing_attempt_id={ids.processing_attempt_id} "
            f"error_type={type(exc).__name__} "
            f"integration_category={integration_category} "
            f"orchestration_category={orchestration_category} "
            f"orchestration_phase={orchestration_phase} "
            f"grant_final_state={grant_final_state} "
            f"revocation_succeeded={getattr(exc, 'revocation_succeeded', None)}",
            file=sys.stderr,
            flush=True,
        )
'''
    _replace_once(path, old, new, label="ingestion failure diagnostic")


def main() -> None:
    _patch_processing_log_handler()
    _patch_presentation_result_remap()
    _patch_orchestration_stages()
    _patch_ingestion_failure_summary()


if __name__ == "__main__":
    main()
