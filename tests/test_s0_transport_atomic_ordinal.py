from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from app.processing.transport.service import InMemoryTransportGrantService
from app.storage.models import StorageReference


RUN_ID = "pdf-ingest-" + "7" * 32
DOCUMENT_ID = "77777777-7777-4777-8777-777777777777"
SOURCE_FILE_ID = "88888888-8888-4888-8888-888888888888"
SOURCE_REF = StorageReference.parse("src_" + "7" * 32)


def _require_atomic_overlay() -> None:
    if not hasattr(InMemoryTransportGrantService, "record_retrieval_with_ordinal"):
        pytest.skip("S0.3.2 atomic transport ordinal overlay is not installed")


def _grant(service: InMemoryTransportGrantService, *, max_retrieval_count: int = 4):
    return service.create_grant(
        storage_reference=SOURCE_REF,
        atlas_attempt_id=RUN_ID,
        document_id=DOCUMENT_ID,
        source_file_id=SOURCE_FILE_ID,
        source_sha256="a" * 64,
        source_byte_size=6,
        media_type="application/pdf",
        max_retrieval_count=max_retrieval_count,
    )


def test_concurrent_retrievals_receive_distinct_atomic_ordinals() -> None:
    _require_atomic_overlay()
    service = InMemoryTransportGrantService()
    created = _grant(service, max_retrieval_count=2)
    barrier = Barrier(2)

    def retrieve_once() -> int:
        barrier.wait()
        authorized, ordinal = service.record_retrieval_with_ordinal(created.token)
        assert authorized.grant_id == created.descriptor.grant_id
        return ordinal

    with ThreadPoolExecutor(max_workers=2) as executor:
        ordinals = list(executor.map(lambda _: retrieve_once(), range(2)))

    assert sorted(ordinals) == [1, 2]
    descriptor = service.inspect(created.descriptor.grant_id)
    assert descriptor is not None
    assert descriptor.retrieval_count == 2


def test_existing_record_retrieval_api_is_preserved() -> None:
    _require_atomic_overlay()
    service = InMemoryTransportGrantService()
    created = _grant(service, max_retrieval_count=2)

    authorized = service.record_retrieval(created.token)

    assert authorized.grant_id == created.descriptor.grant_id
    descriptor = service.inspect(created.descriptor.grant_id)
    assert descriptor is not None
    assert descriptor.retrieval_count == 1


def test_source_transport_consumes_atomic_ordinal_without_post_record_inspect() -> None:
    source = Path("app/routers/source_transport.py").read_text(encoding="utf-8")
    if "record_provider_source_transport_read" not in source:
        pytest.skip("S0.3.2 source-transport overlay is not installed")

    assert "record_retrieval_with_ordinal(token)" in source
    assert "grants.inspect(" not in source
    assert "record_provider_source_transport_read(" in source
