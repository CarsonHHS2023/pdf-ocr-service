from __future__ import annotations

import hashlib
import inspect
from types import SimpleNamespace

import pytest

from app.processing import pdf_page_presentation_lifecycle_compat as lifecycle
from app.storage import dependencies as storage_dependencies
from app.storage import provider_input_access
from app.storage.models import PutResult, StorageReference


class FakeRouter:
    def __init__(self) -> None:
        self.calls = []

    def put(self, data, reference=None, *, expected_size=None, expected_sha256=None):
        payload = bytes(data)
        ref = StorageReference.parse(str(reference))
        digest = hashlib.sha256(payload).hexdigest()
        self.calls.append(
            {
                "data": payload,
                "reference": ref,
                "expected_size": expected_size,
                "expected_sha256": expected_sha256,
            }
        )
        return PutResult(ref, len(payload), digest)


def _require_staging_provider_overlay() -> None:
    source = inspect.getsource(lifecycle._store_deferred_subset)
    if "select_provider_input_storage" not in source:
        pytest.skip("Staging provider-input materialization overlay is not installed")


def test_deferred_subset_uses_remote_first_router_and_exact_delivery_identity(
    monkeypatch,
) -> None:
    _require_staging_provider_overlay()
    render_reference = StorageReference.parse("src_" + "1" * 32)
    provider_reference = StorageReference.parse("src_" + "2" * 32)
    content = b"%PDF-provider-shard"
    checksum = hashlib.sha256(content).hexdigest()
    provider_input = SimpleNamespace(
        provider_pdf_bytes=content,
        storage_reference=render_reference,
        provider_storage_reference=provider_reference,
        provider_byte_size=len(content),
        provider_checksum_sha256=checksum,
    )
    base_storage = object()
    router = FakeRouter()
    observed = []

    monkeypatch.setattr(
        storage_dependencies,
        "get_storage_provider",
        lambda: base_storage,
    )

    def select(storage):
        observed.append(storage)
        return router

    monkeypatch.setattr(provider_input_access, "select_provider_input_storage", select)

    returned_storage = lifecycle._store_deferred_subset(provider_input)

    assert returned_storage is router
    assert observed == [base_storage]
    assert router.calls == [
        {
            "data": content,
            "reference": provider_reference,
            "expected_size": len(content),
            "expected_sha256": checksum,
        }
    ]


def test_no_deferred_bytes_performs_no_storage_resolution(monkeypatch) -> None:
    _require_staging_provider_overlay()
    calls = []
    monkeypatch.setattr(
        storage_dependencies,
        "get_storage_provider",
        lambda: calls.append("unexpected"),
    )

    result = lifecycle._store_deferred_subset(
        SimpleNamespace(provider_pdf_bytes=None)
    )

    assert result is None
    assert calls == []
