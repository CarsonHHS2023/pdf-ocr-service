"""Compose Staging durable processing-event hooks into the tested runtime."""
from __future__ import annotations

import ast
from pathlib import Path
import re


PDF_INGESTION_PATH = Path("app/processing/pdf_ingestion.py")
PRESENTATION_BRIDGE_PATH = Path("app/processing/pdf_page_presentation_bridge.py")
CLASSIFICATION_OBSERVABILITY_PATH = Path(
    "app/processing/pdf_page_classification_observability_compat.py"
)
PROVIDER_SHARDING_PATH = Path("app/processing/pdf_provider_sharding.py")
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


def _patch_document_terminal_state_correlation() -> None:
    source = PDF_INGESTION_PATH.read_text(encoding="utf-8")
    old_signature = (
        "def _set_document_terminal_state(document_id: str, *, status: str, "
        "error_message: str | None) -> None:\n"
    )
    new_signature = '''def _set_document_terminal_state(
    document_id: str,
    *,
    processing_attempt_id: str | None = None,
    status: str,
    error_message: str | None,
) -> None:
'''
    if new_signature not in source:
        if source.count(old_signature) != 1:
            raise RuntimeError("Could not find document terminal state signature")
        source = source.replace(old_signature, new_signature, 1)

    old_event = '''        _diagnostic(
            "PDF_DOCUMENT_STATE_UPDATED",
            document_id=document_id,
            status=status,
            has_error=bool(error_message),
        )
'''
    new_event = '''        _diagnostic(
            "PDF_DOCUMENT_STATE_UPDATED",
            document_id=document_id,
            processing_attempt_id=processing_attempt_id,
            status=status,
            has_error=bool(error_message),
        )
'''
    if new_event not in source:
        if source.count(old_event) != 1:
            raise RuntimeError("Could not find document terminal state diagnostic")
        source = source.replace(old_event, new_event, 1)

    function_start = source.index("async def process_pdf_document_background(")
    prefix = source[:function_start]
    body = source[function_start:]

    multiline = re.compile(
        r"(_set_document_terminal_state\(\n(?P<indent>[ \t]+)document_id,\n)"
        r"(?![ \t]+processing_attempt_id=ids\.processing_attempt_id,)"
    )

    def add_multiline_correlation(match: re.Match[str]) -> str:
        indent = match.group("indent")
        return (
            match.group(1)
            + indent
            + "processing_attempt_id=ids.processing_attempt_id,\n"
        )

    body = multiline.sub(add_multiline_correlation, body)
    body = body.replace(
        "_set_document_terminal_state(document_id, status=",
        "_set_document_terminal_state(\n"
        "            document_id,\n"
        "            processing_attempt_id=ids.processing_attempt_id,\n"
        "            status=",
    )
    source = prefix + body

    parsed = ast.parse(source)
    background = next(
        (
            node
            for node in parsed.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "process_pdf_document_background"
        ),
        None,
    )
    if background is None:
        raise RuntimeError("Could not find process_pdf_document_background")
    calls = [
        node
        for node in ast.walk(background)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_set_document_terminal_state"
    ]
    if not calls:
        raise RuntimeError("No document terminal state calls were found")
    missing = [
        node.lineno
        for node in calls
        if not any(keyword.arg == "processing_attempt_id" for keyword in node.keywords)
    ]
    if missing:
        raise RuntimeError(
            f"Document terminal state calls lack processing correlation at lines {missing}"
        )
    PDF_INGESTION_PATH.write_text(source, encoding="utf-8")


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

    source = PDF_INGESTION_PATH.read_text(encoding="utf-8")
    durable_call = '''        _record_unhandled_failure_event(
            document_id=document_id,
            processing_attempt_id=ids.processing_attempt_id,
            exc=exc,
        )
'''
    if durable_call not in source:
        marker_start = source.index(
            '        print(\n            "PDF_INGESTION_UNHANDLED_FAILURE "\n'
        )
        marker_end = source.index(
            '        logger.exception(\n',
            marker_start,
        )
        source = source[:marker_end] + durable_call + source[marker_end:]
        PDF_INGESTION_PATH.write_text(source, encoding="utf-8")
    else:
        marker_start = source.index(
            '        print(\n            "PDF_INGESTION_UNHANDLED_FAILURE "\n'
        )
        durable_start = source.index(durable_call)
        if durable_start < marker_start:
            source = source.replace(durable_call, "", 1)
            marker_start = source.index(
                '        print(\n            "PDF_INGESTION_UNHANDLED_FAILURE "\n'
            )
            marker_end = source.index(
                '        logger.exception(\n',
                marker_start,
            )
            source = source[:marker_end] + durable_call + source[marker_end:]
            PDF_INGESTION_PATH.write_text(source, encoding="utf-8")
    _patch_document_terminal_state_correlation()


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


def _patch_provider_result_stage_failure_correlation(
    path: Path = PRESENTATION_BRIDGE_PATH,
) -> None:
    """Correlate provider result-stage failures with the durable ProcessingRun."""
    source = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r'(_diagnostic\(\n(?P<indent>[ \t]+)"PDF_PROVIDER_RESULT_STAGE_FAILED",\n)'
        r'(?![ \t]+processing_attempt_id=provider_input\.processing_attempt_id,)'
    )

    def correlate(match: re.Match[str]) -> str:
        indent = match.group("indent")
        return (
            match.group(1)
            + indent
            + "processing_attempt_id=provider_input.processing_attempt_id,\n"
        )

    source, _ = pattern.subn(correlate, source)
    parsed = ast.parse(source)
    calls = [
        node
        for node in ast.walk(parsed)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_diagnostic"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "PDF_PROVIDER_RESULT_STAGE_FAILED"
    ]
    if not calls:
        # Raw source has not yet received the production-equivalent result-stage
        # overlays. The final Staging composition is validated when calls exist.
        return
    missing = [
        node.lineno
        for node in calls
        if not any(keyword.arg == "processing_attempt_id" for keyword in node.keywords)
    ]
    if missing:
        raise RuntimeError(
            f"Provider result-stage failures lack processing correlation at lines {missing}"
        )
    path.write_text(source, encoding="utf-8")


def _patch_classification_observability_timeline(
    path: Path = CLASSIFICATION_OBSERVABILITY_PATH,
) -> None:
    """Persist only low-frequency classification config/summary from the final sink."""
    source = path.read_text(encoding="utf-8")
    diagnostic_anchor = "def _diagnostic(event: str, **fields: object) -> None:\n"
    if diagnostic_anchor not in source:
        # Raw source delegates diagnostics to the already-patched presentation
        # bridge. A later Staging overlay introduces this local sink.
        return

    if _EVENT_IMPORT not in source:
        import_anchor = (
            "from app.processing import pdf_page_presentation_preprocess_compat as preprocess\n"
        )
        if source.count(import_anchor) != 1:
            raise RuntimeError("Could not find classification observability import anchor")
        source = source.replace(import_anchor, import_anchor + _EVENT_IMPORT, 1)

    old = (
        "def _diagnostic(event: str, **fields: object) -> None:\n"
        "    \"\"\"Emit one safe bounded event to both logger and runtime stderr.\"\"\"\n"
        "    payload = \" \".join(f\"{name}={value}\" for name, value in fields.items())\n"
        "    message = f\"{event} {payload}\".rstrip()\n"
        "    _logger.info(message)\n"
        "    print(message, file=sys.stderr, flush=True)\n"
    )
    new = old + (
        "    if event in {\n"
        "        \"PDF_PAGE_CLASSIFICATION_CONFIG\",\n"
        "        \"PDF_PAGE_CLASSIFICATION_SUMMARY\",\n"
        "    }:\n"
        "        record_processing_event(\n"
        "            processing_run_id=fields.get(\"processing_attempt_id\"),\n"
        "            document_id=fields.get(\"document_id\"),\n"
        "            event_name=event,\n"
        "            severity=\"info\",\n"
        "            page_number=fields.get(\"page_number\"),\n"
        "            payload=fields,\n"
        "        )\n"
    )
    if new not in source:
        if source.count(old) != 1:
            raise RuntimeError("Could not find final classification diagnostic sink")
        source = source.replace(old, new, 1)
    path.write_text(source, encoding="utf-8")


def _patch_provider_shard_failure_metadata() -> None:
    """Preserve bounded Provider HTTP metadata when sharded outcomes absorb errors."""
    source = PROVIDER_SHARDING_PATH.read_text(encoding="utf-8")

    provider_error_import = "from app.processing.errors import ProviderClientError\n"
    if provider_error_import not in source:
        import_anchor = "from app.processing.ingestion import canonicalize_inline_json, ingest_artifact_result\n"
        if source.count(import_anchor) != 1:
            raise RuntimeError("Could not find provider sharding error import anchor")
        source = source.replace(import_anchor, import_anchor + provider_error_import, 1)

    helper_anchor = "Diagnostic = Callable[..., None]\n\n\n"
    helper_body = '''def _provider_failure_metadata(error: Exception) -> dict[str, object]:
    """Extract bounded Provider metadata from IntegrationError cause chains."""
    if not isinstance(error, IntegrationError) or error.orchestration_error is None:
        return {}
    provider_cause = error.orchestration_error.__cause__
    if not isinstance(provider_cause, ProviderClientError):
        return {}
    return {
        "provider_error_category": provider_cause.detail.category.value,
        "provider_http_status": provider_cause.detail.http_status,
        "provider_error_code": (
            provider_cause.detail.provider_code
            or error.orchestration_error.provider_error_code
        ),
    }


'''
    if helper_body not in source:
        if source.count(helper_anchor) != 1:
            raise RuntimeError("Could not find provider sharding metadata helper anchor")
        source = source.replace(helper_anchor, helper_anchor + helper_body, 1)

    raw_failure = '''                error_category=exc.category.value,
                cleanup_safe=shard_cleanup_safe,
            )
'''
    raw_failure_enriched = '''                error_category=exc.category.value,
                cleanup_safe=shard_cleanup_safe,
                **_provider_failure_metadata(exc),
            )
'''
    if raw_failure in source:
        source = source.replace(raw_failure, raw_failure_enriched, 1)

    final_failure_fields = '''            "provider_percent_complete": getattr(progress, "percent_complete", None),
        }
'''
    final_failure_fields_enriched = '''            "provider_percent_complete": getattr(progress, "percent_complete", None),
            **_provider_failure_metadata(error),
        }
'''
    if final_failure_fields in source:
        source = source.replace(final_failure_fields, final_failure_fields_enriched, 1)

    if "def failure_fields(error: Exception)" in source:
        start = source.index("def failure_fields(error: Exception)")
        end = source.index("    def batch_terminal", start)
        if "_provider_failure_metadata(error)" not in source[start:end]:
            raise RuntimeError("Final shard failure fields lack Provider metadata preservation")
    elif "PDF_PROVIDER_SHARD_FAILED" in source and "_provider_failure_metadata(exc)" not in source:
        raise RuntimeError("Raw shard failure diagnostic lacks Provider metadata preservation")

    PROVIDER_SHARDING_PATH.write_text(source, encoding="utf-8")


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
    raw_old = '''def _diagnostic(event: str, **fields: object) -> None:
    payload = " ".join(f"{name}={value}" for name, value in fields.items())
    _logger.info("%s %s", event, payload)
'''
    source = SHARDING_COMPAT_PATH.read_text(encoding="utf-8")
    if durable_body in source:
        return
    if final_old in source:
        source = source.replace(final_old, final_old + durable_body, 1)
    elif raw_old in source:
        source = source.replace(raw_old, raw_old + durable_body, 1)
    else:
        raise RuntimeError("Could not find provider sharding diagnostic shape")
    SHARDING_COMPAT_PATH.write_text(source, encoding="utf-8")


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
    if 'event_name="PDF_PROVIDER_SOURCE_ACCESS"' in source:
        return

    final_fallback = '''            logger.warning(message)
            print(message, file=sys.stderr, flush=True)
            return None
'''
    raw_fallback = '''            logger.warning(
                "PDF_PROVIDER_SOURCE_ACCESS route=atlas_source_transport_fallback "
                "byte_size=%s expires_seconds=%s reason=%s",
                safe_size,
                expires_seconds,
                type(exc).__name__,
            )
            return None
'''
    fallback_event = '''            record_processing_event(
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
'''
    if final_fallback in source:
        source = source.replace(
            final_fallback,
            final_fallback.replace("            return None\n", fallback_event + "            return None\n"),
            1,
        )
    elif raw_fallback in source:
        source = source.replace(
            raw_fallback,
            raw_fallback.replace("            return None\n", fallback_event + "            return None\n"),
            1,
        )
    else:
        raise RuntimeError("Could not find provider source-access fallback shape")

    final_success = '''        logger.info(message)
        print(message, file=sys.stderr, flush=True)
        return TemporarySourceTransportUrl(url)
'''
    raw_success = '''        logger.info(
            "PDF_PROVIDER_SOURCE_ACCESS route=presigned_object_get "
            "host=%s byte_size=%s expires_seconds=%s",
            parsed.hostname or "unknown",
            safe_size,
            expires_seconds,
        )
        return TemporarySourceTransportUrl(url)
'''
    success_event = '''        record_processing_event(
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
'''
    if final_success in source:
        source = source.replace(
            final_success,
            final_success.replace(
                "        return TemporarySourceTransportUrl(url)\n",
                success_event + "        return TemporarySourceTransportUrl(url)\n",
            ),
            1,
        )
    elif raw_success in source:
        source = source.replace(
            raw_success,
            raw_success.replace(
                "        return TemporarySourceTransportUrl(url)\n",
                success_event + "        return TemporarySourceTransportUrl(url)\n",
            ),
            1,
        )
    else:
        raise RuntimeError("Could not find provider source-access success shape")
    SOURCE_ACCESS_PATH.write_text(source, encoding="utf-8")


def _patch_source_factory_correlations() -> None:
    ingestion = PDF_INGESTION_PATH.read_text(encoding="utf-8")
    single_old = '''        provider_source_url_factory = build_provider_input_source_url_factory(
            storage=storage,
            reference=provider_delivery.storage_reference,
            byte_size=provider_delivery.byte_size,
        )
'''
    single_new = '''        provider_source_url_factory = build_provider_input_source_url_factory(
            storage=storage,
            reference=provider_delivery.storage_reference,
            byte_size=provider_delivery.byte_size,
            processing_run_id=ids.processing_attempt_id,
            document_id=document_id,
        )
'''
    if single_old in ingestion:
        ingestion = ingestion.replace(single_old, single_new, 1)
        PDF_INGESTION_PATH.write_text(ingestion, encoding="utf-8")

    if not PROVIDER_SHARDING_PATH.exists():
        return
    sharding = PROVIDER_SHARDING_PATH.read_text(encoding="utf-8")
    shard_pattern = re.compile(
        r"(?P<prefix>shard_source_url_factory = build_provider_input_source_url_factory\(\n"
        r"(?P<indent>[ \t]+)storage=storage,\n"
        r"(?P=indent)reference=shard_delivery\.storage_reference,\n"
        r"(?P=indent)byte_size=shard_delivery\.byte_size,\n)"
        r"(?![ \t]+processing_run_id=processing_attempt_id,)"
    )

    def correlate_shard(match: re.Match[str]) -> str:
        indent = match.group("indent")
        return (
            match.group("prefix")
            + indent
            + "processing_run_id=processing_attempt_id,\n"
            + indent
            + "document_id=descriptor.document_id,\n"
        )

    sharding, changed = shard_pattern.subn(correlate_shard, sharding)
    if changed:
        PROVIDER_SHARDING_PATH.write_text(sharding, encoding="utf-8")

    final = PROVIDER_SHARDING_PATH.read_text(encoding="utf-8")
    if "shard_source_url_factory = build_provider_input_source_url_factory(" in final:
        start = final.index("shard_source_url_factory = build_provider_input_source_url_factory(")
        call = final[start : start + 700]
        if "processing_run_id=processing_attempt_id" not in call:
            raise RuntimeError("Final shard source factory lacks processing correlation")
        if "document_id=descriptor.document_id" not in call:
            raise RuntimeError("Final shard source factory lacks document correlation")


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
    _patch_provider_result_stage_failure_correlation()
    _patch_classification_observability_timeline()
    _patch_provider_shard_failure_metadata()
    _patch_provider_sharding_timeline()
    _patch_provider_source_access_timeline()
    _patch_source_factory_correlations()
    _patch_main_router()


def main() -> None:
    patch_durable_processing_events()


if __name__ == "__main__":
    main()
