"""Compose Staging durable processing-event hooks into the tested runtime."""
from __future__ import annotations

from pathlib import Path


PDF_INGESTION_PATH = Path("app/processing/pdf_ingestion.py")
PRESENTATION_BRIDGE_PATH = Path("app/processing/pdf_page_presentation_bridge.py")
MAIN_PATH = Path("app/main.py")

_EVENT_IMPORT = "from app.processing.processing_events import record_processing_event\n"


def _replace_once(path: Path, old: str, new: str, *, label: str) -> None:
    source = path.read_text(encoding="utf-8")
    if new in source:
        return
    if source.count(old) != 1:
        raise RuntimeError(f"Could not find unique {label} anchor in {path}")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


def _patch_pdf_ingestion() -> None:
    source = PDF_INGESTION_PATH.read_text(encoding="utf-8")
    if _EVENT_IMPORT not in source:
        anchor = "from app.processing.orchestration import PollingPolicy\n"
        if source.count(anchor) != 1:
            raise RuntimeError("Could not find unique pdf_ingestion processing import anchor")
        source = source.replace(anchor, anchor + _EVENT_IMPORT, 1)
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
        severity=("error" if event.endswith("_FAILED") else "info"),
        page_number=fields.get("page_number"),
        payload=fields,
    )
'''
    _replace_once(PDF_INGESTION_PATH, old, new, label="pdf_ingestion diagnostic")


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
