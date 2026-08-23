"""Compose Staging durable processing-event hooks into the tested runtime."""
from __future__ import annotations

from pathlib import Path


PDF_INGESTION_PATH = Path("app/processing/pdf_ingestion.py")
PRESENTATION_BRIDGE_PATH = Path("app/processing/pdf_page_presentation_bridge.py")
SHARDING_COMPAT_PATH = Path("app/processing/pdf_provider_sharding_compat.py")
SOURCE_ACCESS_PATH = Path("app/processing/provider_input_source_access.py")
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

    # Document-state events previously lacked the run correlation key, so the
    # durable recorder correctly rejected them. Thread the already-available
    # processing attempt through every terminal-state update without changing
    # the business state transition itself.
    old = '''def _set_document_terminal_state(document_id: str, *, status: str, error_message: str | None) -> None:
'''
    new = '''def _set_document_terminal_state(
    document_id: str,
    *,
    processing_attempt_id: str | None = None,
    status: str,
    error_message: str | None,
) -> None:
'''
    _replace_once(PDF_INGESTION_PATH, old, new, label="document terminal state correlation signature")

    old = '''        _diagnostic(
            "PDF_DOCUMENT_STATE_UPDATED",
            document_id=document_id,
            status=status,
            has_error=bool(error_message),
        )
'''
    new = '''        _diagnostic(
            "PDF_DOCUMENT_STATE_UPDATED",
            document_id=document_id,
            processing_attempt_id=processing_attempt_id,
            status=status,
            has_error=bool(error_message),
        )
'''
    _replace_once(PDF_INGESTION_PATH, old, new, label="document terminal state durable event")

    terminal_calls = (
        (
            '''            _set_document_terminal_state(
                document_id,
                status="failed",
                error_message="Retained PDF source metadata is unavailable",
            )
''',
            '''            _set_document_terminal_state(
                document_id,
                processing_attempt_id=ids.processing_attempt_id,
                status="failed",
                error_message="Retained PDF source metadata is unavailable",
            )
''',
            "retained source unavailable terminal state",
        ),
        (
            '''            _set_document_terminal_state(
                document_id,
                status="failed",
                error_message="Retained PDF source metadata is incomplete",
            )
''',
            '''            _set_document_terminal_state(
                document_id,
                processing_attempt_id=ids.processing_attempt_id,
                status="failed",
                error_message="Retained PDF source metadata is incomplete",
            )
''',
            "retained source incomplete terminal state",
        ),
        (
            '''        _set_document_terminal_state(
            document_id,
            status="failed",
            error_message=exc.safe_message,
        )
''',
            '''        _set_document_terminal_state(
            document_id,
            processing_attempt_id=ids.processing_attempt_id,
            status="failed",
            error_message=exc.safe_message,
        )
''',
            "provider configuration terminal state",
        ),
        (
            '''            _set_document_terminal_state(
                document_id,
                status="failed",
                error_message=error_message,
            )
''',
            '''            _set_document_terminal_state(
                document_id,
                processing_attempt_id=ids.processing_attempt_id,
                status="failed",
                error_message=error_message,
            )
''',
            "provider outcome terminal state",
        ),
        (
            '''            _set_document_terminal_state(
                document_id,
                status="failed",
                error_message="Reader v2 canonical selection is inconsistent with processing result",
            )
''',
            '''            _set_document_terminal_state(
                document_id,
                processing_attempt_id=ids.processing_attempt_id,
                status="failed",
                error_message="Reader v2 canonical selection is inconsistent with processing result",
            )
''',
            "canonical selection terminal state",
        ),
        (
            '''        _set_document_terminal_state(document_id, status="completed", error_message=None)
''',
            '''        _set_document_terminal_state(
            document_id,
            processing_attempt_id=ids.processing_attempt_id,
            status="completed",
            error_message=None,
        )
''',
            "completed terminal state",
        ),
        (
            '''        _set_document_terminal_state(
            document_id,
            status="failed",
            error_message=_safe_failure_message(exc),
        )
''',
            '''        _set_document_terminal_state(
            document_id,
            processing_attempt_id=ids.processing_attempt_id,
            status="failed",
            error_message=_safe_failure_message(exc),
        )
''',
            "unhandled failure terminal state",
        ),
    )
    for old_call, new_call, label in terminal_calls:
        _replace_once(PDF_INGESTION_PATH, old_call, new_call, label=label)


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


def _patch_provider_sharding_timeline() -> None:
    source = SHARDING_COMPAT_PATH.read_text(encoding="utf-8")
    if _EVENT_IMPORT not in source:
        anchor = "from app.processing.models import ProviderLifecycleStatus\n"
        if source.count(anchor) != 1:
            raise RuntimeError("Could not find unique sharding compat event import anchor")
        source = source.replace(anchor, anchor + _EVENT_IMPORT, 1)
        SHARDING_COMPAT_PATH.write_text(source, encoding="utf-8")

    durable_body = '''    durable_event = (
        event in {
            "PDF_PROVIDER_DELIVERY_READY",
            "PDF_PROVIDER_SHARDING_DECISION",
            "PDF_PROVIDER_TRANSPORT_SHARDING_DECISION",
            "PDF_PROVIDER_TRANSPORT_SHARDING_STARTED",
            "PDF_PROVIDER_TRANSPORT_SHARDING_TERMINAL",
            "PDF_PROVIDER_SHARD_INPUT_DELETE_WARNING",
            "PDF_PROVIDER_SHARD_INPUT_ALREADY_DELETED",
        }
        or event.endswith("_FAILED")
    )
    if durable_event:
        severity = (
            "error"
            if event.endswith("_FAILED")
            else "warning"
            if event.endswith("_WARNING")
            else "info"
        )
        record_processing_event(
            processing_run_id=fields.get("processing_attempt_id"),
            document_id=fields.get("document_id"),
            event_name=event,
            severity=severity,
            page_number=fields.get("page_number"),
            payload=fields,
        )
'''
    final_old = '''def _diagnostic(event: str, **fields: object) -> None:
    payload = " ".join(f"{name}={value}" for name, value in fields.items())
    message = f"{event} {payload}".rstrip()
    _logger.info(message)
    print(message, file=sys.stderr, flush=True)
'''
    final_new = final_old + durable_body
    raw_old = '''def _diagnostic(event: str, **fields: object) -> None:
    payload = " ".join(f"{name}={value}" for name, value in fields.items())
    _logger.info("%s %s", event, payload)
'''
    raw_new = raw_old + durable_body

    source = SHARDING_COMPAT_PATH.read_text(encoding="utf-8")
    if final_new in source or raw_new in source:
        return
    if final_old in source:
        SHARDING_COMPAT_PATH.write_text(
            source.replace(final_old, final_new, 1),
            encoding="utf-8",
        )
        return
    if raw_old in source:
        SHARDING_COMPAT_PATH.write_text(
            source.replace(raw_old, raw_new, 1),
            encoding="utf-8",
        )
        return
    raise RuntimeError("Could not find provider sharding diagnostic shape")


def _patch_provider_source_access_timeline() -> None:
    source = SOURCE_ACCESS_PATH.read_text(encoding="utf-8")
    if _EVENT_IMPORT not in source:
        anchor = "from app.processing.integration import TemporarySourceTransportUrl\n"
        if source.count(anchor) != 1:
            raise RuntimeError("Could not find unique provider source-access event import anchor")
        source = source.replace(anchor, anchor + _EVENT_IMPORT, 1)
        SOURCE_ACCESS_PATH.write_text(source, encoding="utf-8")

    old = '''def build_provider_input_source_url_factory(
    *,
    storage: object,
    reference: StorageReference,
    byte_size: int,
):
'''
    new = '''def build_provider_input_source_url_factory(
    *,
    storage: object,
    reference: StorageReference,
    byte_size: int,
    processing_run_id: str | None = None,
    document_id: str | None = None,
):
'''
    _replace_once(SOURCE_ACCESS_PATH, old, new, label="provider source-access correlation")

    source = SOURCE_ACCESS_PATH.read_text(encoding="utf-8")
    final_fallback_old = '''            logger.warning(message)
            print(message, file=sys.stderr, flush=True)
            return None
'''
    final_fallback_new = '''            logger.warning(message)
            print(message, file=sys.stderr, flush=True)
            record_processing_event(
                processing_run_id=processing_run_id,
                document_id=document_id,
                event_name="PDF_PROVIDER_SOURCE_ACCESS",
                severity="warning",
                payload={
                    "route": "atlas_source_transport_fallback",
                    "byte_size": safe_size,
                    "expires_seconds": expires_seconds,
                    "reason": type(exc).__name__,
                },
            )
            return None
'''
    raw_fallback_old = '''            logger.warning(
                "PDF_PROVIDER_SOURCE_ACCESS route=atlas_source_transport_fallback "
                "byte_size=%s expires_seconds=%s reason=%s",
                safe_size,
                expires_seconds,
                type(exc).__name__,
            )
            return None
'''
    raw_fallback_new = '''            logger.warning(
                "PDF_PROVIDER_SOURCE_ACCESS route=atlas_source_transport_fallback "
                "byte_size=%s expires_seconds=%s reason=%s",
                safe_size,
                expires_seconds,
                type(exc).__name__,
            )
            record_processing_event(
                processing_run_id=processing_run_id,
                document_id=document_id,
                event_name="PDF_PROVIDER_SOURCE_ACCESS",
                severity="warning",
                payload={
                    "route": "atlas_source_transport_fallback",
                    "byte_size": safe_size,
                    "expires_seconds": expires_seconds,
                    "reason": type(exc).__name__,
                },
            )
            return None
'''
    if final_fallback_new not in source and raw_fallback_new not in source:
        if final_fallback_old in source:
            source = source.replace(final_fallback_old, final_fallback_new, 1)
        elif raw_fallback_old in source:
            source = source.replace(raw_fallback_old, raw_fallback_new, 1)
        else:
            raise RuntimeError("Could not find provider source-access fallback shape")
        SOURCE_ACCESS_PATH.write_text(source, encoding="utf-8")

    source = SOURCE_ACCESS_PATH.read_text(encoding="utf-8")
    final_success_old = '''        logger.info(message)
        print(message, file=sys.stderr, flush=True)
        return TemporarySourceTransportUrl(url)
'''
    final_success_new = '''        logger.info(message)
        print(message, file=sys.stderr, flush=True)
        record_processing_event(
            processing_run_id=processing_run_id,
            document_id=document_id,
            event_name="PDF_PROVIDER_SOURCE_ACCESS",
            severity="info",
            payload={
                "route": "presigned_object_get",
                "host": parsed.hostname or "unknown",
                "byte_size": safe_size,
                "expires_seconds": expires_seconds,
            },
        )
        return TemporarySourceTransportUrl(url)
'''
    raw_success_old = '''        logger.info(
            "PDF_PROVIDER_SOURCE_ACCESS route=presigned_object_get "
            "host=%s byte_size=%s expires_seconds=%s",
            parsed.hostname or "unknown",
            safe_size,
            expires_seconds,
        )
        return TemporarySourceTransportUrl(url)
'''
    raw_success_new = '''        logger.info(
            "PDF_PROVIDER_SOURCE_ACCESS route=presigned_object_get "
            "host=%s byte_size=%s expires_seconds=%s",
            parsed.hostname or "unknown",
            safe_size,
            expires_seconds,
        )
        record_processing_event(
            processing_run_id=processing_run_id,
            document_id=document_id,
            event_name="PDF_PROVIDER_SOURCE_ACCESS",
            severity="info",
            payload={
                "route": "presigned_object_get",
                "host": parsed.hostname or "unknown",
                "byte_size": safe_size,
                "expires_seconds": expires_seconds,
            },
        )
        return TemporarySourceTransportUrl(url)
'''
    if final_success_new not in source and raw_success_new not in source:
        if final_success_old in source:
            source = source.replace(final_success_old, final_success_new, 1)
        elif raw_success_old in source:
            source = source.replace(raw_success_old, raw_success_new, 1)
        else:
            raise RuntimeError("Could not find provider source-access success shape")
        SOURCE_ACCESS_PATH.write_text(source, encoding="utf-8")


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
    """Install coarse durable events; keep high-volume heartbeats in checkpoints/stdout."""
    _patch_pdf_ingestion()
    _patch_presentation_bridge()
    _patch_provider_sharding_timeline()
    _patch_provider_source_access_timeline()
    _patch_main_router()


def main() -> None:
    patch_durable_processing_events()


if __name__ == "__main__":
    main()
