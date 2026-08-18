from __future__ import annotations

import gzip
import hashlib
from dataclasses import FrozenInstanceError

import pytest

from app.processing.ingestion import (
    InvalidEnvelopeInput,
    RawResultChecksumMismatch,
    RawResultSerializationError,
    RawResultSizeMismatch,
    RawResultStorageConflict,
    RawResultStorageWriteError,
    UnsafeMetadataError,
    ingest_artifact_result,
    ingest_inline_result,
    summarize_pages,
    _validate_single_evidence_source,
)
from app.processing.models import ProcessingPageIdentity
from app.processing.raw_result import (
    RawResultArtifactMetadata,
    RawResultEvidenceSource,
    RawResultIdentity,
    RawResultProviderProvenance,
    RawResultSourceProvenance,
)
from app.storage.errors import WriteFailure
from app.storage.local import LocalStorageProvider
from app.storage.models import StorageReference

SOURCE_SHA = "1" * 64


@pytest.fixture
def storage(tmp_path):
    return LocalStorageProvider(tmp_path / "objects")


@pytest.fixture
def identity():
    return RawResultIdentity(
        atlas_attempt_id="attempt-1",
        atlas_correlation_id="corr-1",
        document_id="doc-1",
        source_file_id="src-file-1",
        provider_name="provider-x",
        provider_job_id="job-1",
        provider_request_id="request-1",
        provider_result_profile="raw-json",
        provider_result_status="completed",
    )


@pytest.fixture
def source():
    return RawResultSourceProvenance(SOURCE_SHA, source_etag='"etag"', source_media_type="application/pdf")


def test_inline_json_is_deterministic_exact_and_does_not_mutate(storage, identity, source):
    payload = {"z": ["é", {"b": 2, "a": 1}], "a": {"provider_specific": True}}
    original = {"z": ["é", {"b": 2, "a": 1}], "a": {"provider_specific": True}}
    env = ingest_inline_result(storage=storage, identity=identity, source=source, provider=None, inline_result=payload)
    expected = '{"a":{"provider_specific":true},"z":["é",{"a":1,"b":2}]}'.encode("utf-8")
    assert storage.get(env.ingestion.storage_reference) == expected
    assert env.ingestion.payload_size_bytes == len(expected)
    assert env.ingestion.payload_sha256 == hashlib.sha256(expected).hexdigest()
    assert env.ingestion.evidence_source == RawResultEvidenceSource.INLINE_JSON
    assert env.ingestion.payload_media_type == "application/json"
    assert env.ingestion.payload_encoding == "utf-8"
    assert payload == original


def test_inline_json_key_order_independent(storage, identity, source):
    a = ingest_inline_result(storage=storage, identity=identity, source=source, provider=None, inline_result={"b": 2, "a": 1})
    b = ingest_inline_result(storage=storage, identity=identity, source=source, provider=None, inline_result={"a": 1, "b": 2})
    assert a.ingestion.payload_sha256 == b.ingestion.payload_sha256
    assert storage.get(a.ingestion.storage_reference) == storage.get(b.ingestion.storage_reference)


def test_inline_unserializable_rejected(storage, identity, source):
    with pytest.raises(RawResultSerializationError):
        ingest_inline_result(storage=storage, identity=identity, source=source, provider=None, inline_result={"bad": object()})


@pytest.mark.parametrize(
    "bad_identity",
    [
        {"atlas_attempt_id": ""},
        {"document_id": ""},
        {"source_file_id": ""},
        {"provider_name": ""},
        {"provider_job_id": ""},
        {"provider_result_profile": " "},
        {"provider_result_status": " "},
    ],
)
def test_envelope_identity_validation(storage, identity, source, bad_identity):
    changed = identity.__dict__ | bad_identity
    with pytest.raises(InvalidEnvelopeInput):
        ingest_inline_result(storage=storage, identity=RawResultIdentity(**changed), source=source, provider=None, inline_result={})


def test_invalid_checksums_and_negative_sizes_rejected(storage, identity):
    with pytest.raises(InvalidEnvelopeInput):
        ingest_inline_result(storage=storage, identity=identity, source=RawResultSourceProvenance("bad"), provider=None, inline_result={})
    with pytest.raises(InvalidEnvelopeInput):
        ingest_artifact_result(
            storage=storage,
            identity=identity,
            source=RawResultSourceProvenance(SOURCE_SHA),
            provider=None,
            artifact_bytes=b"x",
            artifact_metadata=RawResultArtifactMetadata(size_bytes=-1),
        )
    with pytest.raises(InvalidEnvelopeInput):
        ingest_artifact_result(
            storage=storage,
            identity=identity,
            source=RawResultSourceProvenance(SOURCE_SHA),
            provider=None,
            artifact_bytes=b"x",
            artifact_metadata=RawResultArtifactMetadata(checksum_sha256="bad"),
        )


def test_missing_payload_and_contradictory_evidence_rejected(storage, identity, source):
    with pytest.raises(InvalidEnvelopeInput):
        ingest_inline_result(storage=storage, identity=identity, source=source, provider=None, inline_result=None)
    with pytest.raises(InvalidEnvelopeInput):
        _validate_single_evidence_source(inline_result={"a": 1}, artifact_bytes=b"artifact")


def test_artifact_exact_bytes_metadata_and_gzip_preserved(storage, identity, source):
    data = gzip.compress(b"raw-result")
    meta = RawResultArtifactMetadata(media_type="application/json", compression="gzip", size_bytes=len(data), checksum_sha256=hashlib.sha256(data).hexdigest())
    env = ingest_artifact_result(storage=storage, identity=identity, source=source, provider=None, artifact_bytes=data, artifact_metadata=meta)
    assert storage.get(env.ingestion.storage_reference) == data
    assert env.ingestion.payload_size_bytes == len(data)
    assert env.ingestion.payload_sha256 == hashlib.sha256(data).hexdigest()
    assert env.ingestion.payload_compression == "gzip"
    assert env.ingestion.artifact_metadata == meta
    assert env.ingestion.evidence_source == RawResultEvidenceSource.ARTIFACT_BYTES


def test_artifact_checksum_and_size_mismatch_rejected(storage, identity, source):
    with pytest.raises(RawResultChecksumMismatch):
        ingest_artifact_result(storage=storage, identity=identity, source=source, provider=None, artifact_bytes=b"x", artifact_metadata=RawResultArtifactMetadata(checksum_sha256="0" * 64))
    with pytest.raises(RawResultSizeMismatch):
        ingest_artifact_result(storage=storage, identity=identity, source=source, provider=None, artifact_bytes=b"x", artifact_metadata=RawResultArtifactMetadata(size_bytes=2))


def test_create_only_idempotency_and_conflict(storage, identity, source):
    ref = StorageReference.generate()
    first = ingest_inline_result(storage=storage, identity=identity, source=source, provider=None, inline_result={"a": 1}, existing_storage_reference=ref)
    second = ingest_inline_result(storage=storage, identity=identity, source=source, provider=None, inline_result={"a": 1}, existing_storage_reference=ref)
    assert second.ingestion.storage_reference == first.ingestion.storage_reference
    with pytest.raises(RawResultStorageConflict):
        ingest_inline_result(storage=storage, identity=identity, source=source, provider=None, inline_result={"a": 2}, existing_storage_reference=ref)


def test_storage_failure_maps_safely(identity, source):
    class FailingStorage:
        def put(self, *args, **kwargs):
            raise WriteFailure("backend path /tmp/secret raw bytes")
    with pytest.raises(RawResultStorageWriteError) as exc:
        ingest_inline_result(storage=FailingStorage(), identity=identity, source=source, provider=None, inline_result={"secret": "raw"})
    message = str(exc.value)
    assert "attempt-1" in message and "provider-x" in message and "job-1" in message
    assert "raw" not in message and "/tmp/secret" not in message


def test_security_metadata_rejected_and_urls_not_returned(storage, identity, source):
    with pytest.raises(UnsafeMetadataError):
        ingest_inline_result(storage=storage, identity=identity, source=source, provider=RawResultProviderProvenance(configuration={"Authorization": "Bearer x"}), inline_result={})
    with pytest.raises(UnsafeMetadataError):
        ingest_artifact_result(storage=storage, identity=identity, source=source, provider=None, artifact_bytes=b"x", artifact_metadata=RawResultArtifactMetadata(provider_metadata={"artifact_url": "https://signed"}))
    env = ingest_artifact_result(storage=storage, identity=identity, source=source, provider=None, artifact_bytes=b"x", artifact_metadata=RawResultArtifactMetadata(artifact_id="art-1"))
    assert "url" not in repr(env).lower()


def test_page_summary_valid_missing_duplicate_and_empty():
    pages = [
        ProcessingPageIdentity("doc-1", 1, 0, 0, (1, 2)),
        ProcessingPageIdentity("doc-1", 2, 1, 1, (1, 2)),
    ]
    valid = summarize_pages(pages, expected_pages_total=2)
    assert valid.page_count_observed == 2
    assert valid.first_source_page == 1 and valid.last_source_page == 2
    assert valid.mapping_valid is True
    assert valid.source_ranges_represented == ((1, 2),)
    invalid = summarize_pages(pages + [pages[0]], expected_pages_total=3)
    assert invalid.duplicate_pages == (1,)
    assert invalid.missing_pages == (3,)
    assert invalid.mapping_valid is False
    empty = summarize_pages([], expected_pages_total=None)
    assert empty.page_count_observed == 0
    assert empty.mapping_valid is True


def test_envelope_is_frozen_and_no_sourcefile_mutation(storage, identity, source):
    class SourceFileLike:
        storage_reference = "original"
        retained = True
    source_file = SourceFileLike()
    env = ingest_inline_result(storage=storage, identity=identity, source=source, provider=None, inline_result={})
    with pytest.raises(FrozenInstanceError):
        env.identity.document_id = "changed"
    assert source_file.storage_reference == "original"
    assert source_file.retained is True


def test_inline_rejects_non_finite_numbers_and_other_unserializable_values(storage, identity, source):
    import math
    from datetime import datetime, timezone

    circular = []
    circular.append(circular)
    for payload in [
        {"nan": math.nan},
        {"infinity": math.inf},
        {"bytes": b"raw"},
        {"datetime": datetime.now(timezone.utc)},
        {"set": {1, 2}},
        {"custom": object()},
        circular,
    ]:
        with pytest.raises(RawResultSerializationError) as exc:
            ingest_inline_result(storage=storage, identity=identity, source=source, provider=None, inline_result=payload)
        assert "raw" not in str(exc.value)


def test_provider_specific_profile_status_remain_opaque(storage, identity, source):
    changed = identity.__dict__ | {
        "provider_result_profile": "vendor-x/diagnostic-v7",
        "provider_result_status": "vendor_state__done_with_warnings",
    }
    env = ingest_inline_result(
        storage=storage,
        identity=RawResultIdentity(**changed),
        source=source,
        provider=None,
        inline_result={"ok": True},
    )
    assert env.identity.provider_result_profile == "vendor-x/diagnostic-v7"
    assert env.identity.provider_result_status == "vendor_state__done_with_warnings"


def test_required_identity_rejects_unicode_whitespace_and_object_values(storage, identity, source):
    with pytest.raises(InvalidEnvelopeInput):
        ingest_inline_result(
            storage=storage,
            identity=RawResultIdentity(**(identity.__dict__ | {"atlas_attempt_id": "\u2003"})),
            source=source,
            provider=None,
            inline_result={},
        )
    with pytest.raises(InvalidEnvelopeInput):
        ingest_inline_result(
            storage=storage,
            identity=RawResultIdentity(**(identity.__dict__ | {"document_id": object()})),
            source=source,
            provider=None,
            inline_result={},
        )


def test_metadata_is_deep_frozen_and_detached_from_inputs(storage, identity, source):
    config = {"nested": {"value": ["original"]}}
    artifact_meta = {"safe": {"values": [1]}}
    provider = RawResultProviderProvenance(configuration=config)
    artifact = RawResultArtifactMetadata(provider_metadata=artifact_meta)
    config["nested"]["value"].append("mutated")
    artifact_meta["safe"]["values"].append(2)
    env = ingest_artifact_result(
        storage=storage,
        identity=identity,
        source=source,
        provider=provider,
        artifact_bytes=b"bytes",
        artifact_metadata=artifact,
    )
    assert env.provider.configuration["nested"]["value"] == ("original",)
    assert env.ingestion.artifact_metadata.provider_metadata["safe"]["values"] == (1,)
    with pytest.raises(TypeError):
        env.provider.configuration["new"] = "blocked"
    with pytest.raises(TypeError):
        env.ingestion.artifact_metadata.provider_metadata["safe"]["new"] = "blocked"


def test_nested_unsafe_metadata_rejected_but_raw_payload_path_preserved(storage, identity, source):
    with pytest.raises(UnsafeMetadataError):
        ingest_inline_result(
            storage=storage,
            identity=identity,
            source=source,
            provider=RawResultProviderProvenance(capabilities={"nested": [{"x-amz-signature": "abc"}]}),
            inline_result={},
        )
    with pytest.raises(UnsafeMetadataError):
        ingest_artifact_result(
            storage=storage,
            identity=identity,
            source=source,
            provider=None,
            artifact_bytes=b"x",
            artifact_metadata=RawResultArtifactMetadata(provider_metadata={"nested": {"cache-key": "abc"}}),
        )
    payload = {"blocks": [{"path": "provider/content/path", "text": "secret token_count only"}]}
    env = ingest_inline_result(storage=storage, identity=identity, source=source, provider=None, inline_result=payload)
    assert storage.get(env.ingestion.storage_reference) == b'{"blocks":[{"path":"provider/content/path","text":"secret token_count only"}]}'


def test_storage_put_result_mismatch_and_unexpected_exception_are_safe(identity, source):
    class WrongMetadataStorage:
        def put(self, data, reference=None, *, expected_size=None, expected_sha256=None):
            return type("Result", (), {
                "reference": StorageReference.generate(),
                "byte_size": len(data) + 1,
                "checksum_sha256": hashlib.sha256(data).hexdigest(),
            })()

    with pytest.raises(RawResultStorageWriteError) as exc:
        ingest_inline_result(storage=WrongMetadataStorage(), identity=identity, source=source, provider=None, inline_result={"safe": True})
    assert "unexpected size" in str(exc.value)
    assert "safe" not in str(exc.value)

    class ExplodingStorage:
        def put(self, *args, **kwargs):
            raise RuntimeError("/tmp/provider/path bearer token raw payload")

    with pytest.raises(RawResultStorageWriteError) as exc:
        ingest_inline_result(storage=ExplodingStorage(), identity=identity, source=source, provider=None, inline_result={"raw": "payload"})
    assert "/tmp/provider/path" not in str(exc.value)
    assert "payload" not in str(exc.value)


def test_storage_requested_reference_mismatch_rejected(identity, source):
    requested = StorageReference.generate()

    class WrongReferenceStorage:
        def put(self, data, reference=None, *, expected_size=None, expected_sha256=None):
            return type("Result", (), {
                "reference": StorageReference.generate(),
                "byte_size": len(data),
                "checksum_sha256": hashlib.sha256(data).hexdigest(),
            })()

    with pytest.raises(RawResultStorageWriteError) as exc:
        ingest_inline_result(
            storage=WrongReferenceStorage(),
            identity=identity,
            source=source,
            provider=None,
            inline_result={"safe": True},
            existing_storage_reference=requested,
        )
    assert "unexpected reference" in str(exc.value)
