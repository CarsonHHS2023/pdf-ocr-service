"""Compose Staging durable processing-event hooks into the tested runtime."""
from __future__ import annotations

from pathlib import Path


PDF_INGESTION_PATH = Path("app/processing/pdf_ingestion.py")
PRESENTATION_BRIDGE_PATH = Path("app/processing/pdf_page_presentation_bridge.py")
MAIN_PATH = Path("app/main.py")

_EVENT_IMPORT = "from app.processing.processing_events import record_processing_event\n"
_PROVIDER_ERROR_IMPORT = "from app.processing.errors import ProviderClientError\n"


def _replace_once(path: Path, old: str, new: str, *, label: str) -> None:
    source = path.read_text(encoding="utf-8")
    if new in source:
        return
    if source.count(old) != 1:
        raise RuntimeError(f"Could not find unique {label} anchor in {path}")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


def _patch_pdf_ingestion() -> None:
    source = PDF_INGESTION_PATH.read_text(encoding="utf-8")
    anchor = "from app.processing.orchestration import PollingPolicy\n"
    if _EVENT_IMPORT not in source or _PROVIDER_ERROR_IMPORT not in source:
        if source.count(anchor) != 1:
            raise RuntimeError("Could not find unique pdf_ingestion processing import anchor")
        additions = ""
        if _PROVIDER_ERROR_IMPORT not in source:
            additions += _PROVIDER_ERROR_IMPORT
        if _EVENT_IMPORT not in source:
            additions += _EVENT_IMPORT
        source = source.replace(anchor, anchor + additions, 1)
        PDF_INGESTION_PATH.write_text(source, encoding="utf-8")

    old = '''def _diagnostic(event: str, **fields: object) -> None:
    payload = " ".join(f"{name}={value}" for name, value in fields.items())
    message = f"{event} {payload}".rstrip()
    logger.info(message)
    print(message, file=sys.stderr, flush=True)
'''
    new = '''def _diagnostic(event: str, **fields: object) -> None:
    payload = " ".join(f"{name}={value}" for name, value in fields.items())
    message = f"{event} {payload}".rstrip()
    logger.info(message)
    print(message, file=sys.stderr, flush=True)
    record_processing_event(
        processing_run_id=fields.get("processing_attempt_id"),
        document_id=fields.get("document_id"),
        event_name=event,
        severity=("error" if event.endswith(("_FAILED", "_FAILURE")) else "info"),
        page_number=fields.get("page_number"),
        payload=fields,
    )
'''
    _replace_once(PDF_INGESTION_PATH, old, new, label="pdf_ingestion diagnostic")

    old = '''def _safe_failure_message(exc: BaseException | None = None) -> str:
    if isinstance(exc, IntegrationError):
        return exc.safe_message
    if isinstance(exc, PdfPreprocessingCapacityError):
        return "PDF preprocessing capacity is temporarily full; retry later"
    if isinstance(exc, BookSourceTooLarge):
        return "PDF source exceeds the current application processing limit"
    return "PDF processing failed before Reader v2 content became ready"
'''
    new = '''def _safe_failure_message(exc: BaseException | None = None) -> str:
    if isinstance(exc, IntegrationError):
        return exc.safe_message
    if isinstance(exc, PdfPreprocessingCapacityError):
        return "PDF preprocessing capacity is temporarily full; retry later"
    if isinstance(exc, BookSourceTooLarge):
        return "PDF source exceeds the current application processing limit"
    return "PDF processing failed before Reader v2 content became ready"


def _durable_failure_fields(exc: BaseException) -> dict[str, object]:
    """Extract bounded non-secret provider failure metadata already held in memory."""
    if not isinstance(exc, IntegrationError) or exc.orchestration_error is None:
        return {}

    orchestration_error = exc.orchestration_error
    fields: dict[str, object] = {
        "integration_error_category": exc.category.value,
        "orchestration_error_category": orchestration_error.category.value,
        "orchestration_phase": orchestration_error.phase.value,
        "provider_error_code": orchestration_error.provider_error_code,
        "retryable": orchestration_error.retryable,
        "elapsed_seconds": orchestration_error.elapsed_seconds,
        "poll_count": orchestration_error.poll_count,
    }
    provider_cause = orchestration_error.__cause__
    if isinstance(provider_cause, ProviderClientError):
        fields.update(
            {
                "provider_error_category": provider_cause.detail.category.value,
                "provider_http_status": provider_cause.detail.http_status,
                "provider_error_code": (
                    provider_cause.detail.provider_code
                    or orchestration_error.provider_error_code
                ),
                "retryable": provider_cause.detail.retryable,
            }
        )
    return fields


def _record_unhandled_failure_event(
    *,
    document_id: str,
    processing_attempt_id: str,
    exc: BaseException,
) -> None:
    """Persist one safe failure event without changing the existing stdout contract."""
    payload: dict[str, object] = {
        "document_id": document_id,
        "processing_attempt_id": processing_attempt_id,
        "error_type": type(exc).__name__,
        **_durable_failure_fields(exc),
    }
    record_processing_event(
        processing_run_id=processing_attempt_id,
        document_id=document_id,
        event_name="PDF_INGESTION_UNHANDLED_FAILURE",
        severity="error",
        payload=payload,
    )
'''
    _replace_once(PDF_INGESTION_PATH, old, new, label="durable provider failure metadata")

    # Provider-result diagnostics may have already expanded the surrounding
    # stdout block. Anchor only on the stable failure marker and leave that
    # stdout/logging behavior byte-for-byte intact.
    old = '''        print(
            "PDF_INGESTION_UNHANDLED_FAILURE "
'''
    new = '''        _record_unhandled_failure_event(
            document_id=document_id,
            processing_attempt_id=ids.processing_attempt_id,
            exc=exc,
        )
        print(
            "PDF_INGESTION_UNHANDLED_FAILURE "
'''
    _replace_once(PDF_INGESTION_PATH, old, new, label="durable ingestion failure event")


def _patch_presentation_bridge() -> None:
    source = PRESENTATION_BRIDGE_PATH.read_text(encoding="utf-8")
    if _EVENT_IMPORT not in source:
        anchor = "from app.storage.models import StorageReference\n"
        if source.count(anchor) != 1:
            raise RuntimeError("Could not find unique presentation bridge storage import anchor")
        source = source.replace(anchor, _EVENT_IMPORT + anchor, 1)
        PRESENTATION_BRIDGE_PATH.write_text(source, encoding="utf-8")

    old = '''def _diagnostic(event: str, **fields: object) -> None:
    payload = " ".join(f"{name}={value}" for name, value in sorted(fields.items()))
    _logger.info("%s %s", event, payload)
'''
    new = '''def _diagnostic(event: str, **fields: object) -> None:
    payload = " ".join(f"{name}={value}" for name, value in sorted(fields.items()))
    _logger.info("%s %s", event, payload)
    durable_event = (
        event in {
            "PDF_PAGE_CLASSIFICATION_PLANNED",
            "PDF_PAGE_CLASSIFICATION_CONFIG",
            "PDF_PROVIDER_PAGE_MAP_CREATED",
        }
        or event.endswith("_SUMMARY")
        or event.endswith("_FAILED")
    )
    if durable_event:
        record_processing_event(
            processing_run_id=fields.get("processing_attempt_id"),
            document_id=fields.get("document_id"),
            event_name=event,
            severity=("error" if event.endswith("_FAILED") else "info"),
            page_number=(fields.get("page_number") or fields.get("original_page_number")),
            payload=fields,
        )
'''
    _replace_once(PRESENTATION_BRIDGE_PATH, old, new, label="presentation diagnostic")


def _patch_main_router() -> None:
    old = '''    processing_operator,
    reader,
'''
    new = '''    processing_operator,
    processing_events,
    reader,
'''
    _replace_once(MAIN_PATH, old, new, label="processing events router import")

    old = '''app.include_router(processing_operator.router)
app.include_router(reader.router)
'''
    new = '''app.include_router(processing_operator.router)
app.include_router(processing_events.router)
app.include_router(reader.router)
'''
    _replace_once(MAIN_PATH, old, new, label="processing events router include")


def patch_durable_processing_events() -> None:
    """Install coarse durable events; keep high-volume page profiles in stdout."""
    _patch_pdf_ingestion()
    _patch_presentation_bridge()
    _patch_main_router()


def main() -> None:
    patch_durable_processing_events()


if __name__ == "__main__":
    main()
