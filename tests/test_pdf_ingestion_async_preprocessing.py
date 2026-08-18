import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

from app.processing import pdf_ingestion


def _descriptor(pdf_bytes: bytes, *, name: str = "test.pdf") -> SimpleNamespace:
    return SimpleNamespace(
        storage_reference=object(),
        byte_size=len(pdf_bytes),
        sha256=hashlib.sha256(pdf_bytes).hexdigest(),
        filename=name,
    )


def test_ocrmypdf_provider_preprocessing_uses_bounded_dedicated_executor() -> None:
    source = Path("app/processing/pdf_ingestion.py").read_text(encoding="utf-8")

    assert "from concurrent.futures import ThreadPoolExecutor" in source
    assert "_PDF_PREPROCESSING_EXECUTOR = ThreadPoolExecutor(" in source
    assert "max_workers=PDF_PREPROCESSING_MAX_CONCURRENCY" in source
    assert "_PDF_PREPROCESSING_CAPACITY = threading.BoundedSemaphore(" in source
    assert "_PDF_PREPROCESSING_CAPACITY.acquire(blocking=False)" in source
    assert "_PDF_PREPROCESSING_EXECUTOR.submit(" in source
    assert "asyncio.wrap_future(concurrent_future)" in source
    assert "concurrent_future.add_done_callback(job_state.on_worker_done)" in source
    assert "result = await asyncio.shield(wrapped_future)" in source
    assert "expected_page_count=expected_page_count" in source
    assert "abandoned_input = await asyncio.shield" not in source
    assert "asyncio.to_thread(" not in source
    assert source.index("geometry_input = await _prepare_geometry_provider_input_async(") < source.index(
        "outcome = await service.process(request)"
    )


def test_dedicated_preprocessing_executor_serializes_jobs() -> None:
    first_entered = threading.Event()
    second_entered = threading.Event()
    release = threading.Event()
    active = 0
    max_active = 0
    lock = threading.Lock()

    def work(name: str) -> str:
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            if name == "first":
                first_entered.set()
                assert release.wait(timeout=2.0)
            else:
                second_entered.set()
            return name
        finally:
            with lock:
                active -= 1

    first = pdf_ingestion._PDF_PREPROCESSING_EXECUTOR.submit(work, "first")
    assert first_entered.wait(timeout=1.0)

    second = pdf_ingestion._PDF_PREPROCESSING_EXECUTOR.submit(work, "second")
    assert not second_entered.wait(timeout=0.1)

    release.set()
    assert first.result(timeout=2.0) == "first"
    assert second.result(timeout=2.0) == "second"
    assert second_entered.is_set()
    assert max_active == 1


def test_submission_capacity_rejects_excess_before_reading_source(monkeypatch) -> None:
    pdf_bytes = b"%PDF-bounded-capacity"
    descriptor = _descriptor(pdf_bytes)
    started = threading.Event()
    release = threading.Event()
    get_calls = 0
    capacity = threading.BoundedSemaphore(1)

    class Storage:
        def get(self, reference):
            nonlocal get_calls
            assert reference is descriptor.storage_reference
            get_calls += 1
            return pdf_bytes

    def fake_prepare_geometry_provider_input(**kwargs):
        assert kwargs["expected_page_count"] == 1
        started.set()
        assert release.wait(timeout=2.0)
        return SimpleNamespace(storage_reference=object())

    monkeypatch.setattr(pdf_ingestion, "_PDF_PREPROCESSING_CAPACITY", capacity)
    monkeypatch.setattr(
        pdf_ingestion,
        "prepare_geometry_provider_input",
        fake_prepare_geometry_provider_input,
    )

    async def scenario() -> None:
        first = asyncio.create_task(
            pdf_ingestion._prepare_geometry_provider_input_async(
                storage=Storage(),
                descriptor=descriptor,
                processing_attempt_id="attempt-1",
                document_id="document-1",
                expected_page_count=1,
            )
        )
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.01)
        assert started.is_set()

        with pytest.raises(pdf_ingestion.PdfPreprocessingCapacityError):
            await pdf_ingestion._prepare_geometry_provider_input_async(
                storage=Storage(),
                descriptor=descriptor,
                processing_attempt_id="attempt-2",
                document_id="document-2",
                expected_page_count=1,
            )

        assert get_calls == 1
        release.set()
        await first

    asyncio.run(scenario())

    assert capacity.acquire(blocking=False)
    capacity.release()


def test_repeated_cancellation_cannot_interrupt_cleanup(monkeypatch) -> None:
    pdf_bytes = b"%PDF-cancellation"
    descriptor = _descriptor(pdf_bytes)
    started = threading.Event()
    release = threading.Event()
    deleted_event = threading.Event()
    deleted: list[object] = []
    storage_reference = object()
    capacity = threading.BoundedSemaphore(1)

    class Storage:
        def get(self, reference):
            assert reference is descriptor.storage_reference
            return pdf_bytes

        def delete(self, reference):
            deleted.append(reference)
            deleted_event.set()

    def fake_prepare_geometry_provider_input(**kwargs):
        assert kwargs["processing_attempt_id"] == "attempt-1"
        assert kwargs["expected_page_count"] == 1
        started.set()
        assert release.wait(timeout=2.0)
        return SimpleNamespace(storage_reference=storage_reference)

    monkeypatch.setattr(pdf_ingestion, "_PDF_PREPROCESSING_CAPACITY", capacity)
    monkeypatch.setattr(
        pdf_ingestion,
        "prepare_geometry_provider_input",
        fake_prepare_geometry_provider_input,
    )

    async def scenario() -> None:
        task = asyncio.create_task(
            pdf_ingestion._prepare_geometry_provider_input_async(
                storage=Storage(),
                descriptor=descriptor,
                processing_attempt_id="attempt-1",
                document_id="document-1",
                expected_page_count=1,
            )
        )
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.01)
        assert started.is_set()

        task.cancel()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        release.set()
        for _ in range(200):
            if deleted_event.is_set():
                break
            await asyncio.sleep(0.01)
        assert deleted_event.is_set()

    asyncio.run(scenario())

    assert deleted == [storage_reference]
    assert capacity.acquire(blocking=False)
    capacity.release()
