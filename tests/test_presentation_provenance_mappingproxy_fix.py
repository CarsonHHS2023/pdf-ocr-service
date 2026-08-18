from __future__ import annotations

from dataclasses import replace
import hashlib
import json

import pytest

from scripts.apply_presentation_provenance_fix import main as apply_fix

apply_fix()

from app.processing.ingestion import ingest_inline_result
from app.processing.pdf_page_presentation_lifecycle_compat import (
    _rebuild_presentation_provider_provenance,
)
from app.processing.raw_result import (
    RawResultIdentity,
    RawResultPageSummary,
    RawResultProviderProvenance,
    RawResultSourceProvenance,
)
from app.storage.models import PutResult, StorageReference


class RecordingStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(
        self,
        data: bytes,
        reference: StorageReference | str | None = None,
        *,
        expected_size: int | None = None,
        expected_sha256: str | None = None,
    ) -> PutResult:
        assert isinstance(data, bytes)
        assert expected_size in {None, len(data)}
        checksum = hashlib.sha256(data).hexdigest()
        assert expected_sha256 in {None, checksum}
        if reference is None:
            parsed = StorageReference.generate()
        elif isinstance(reference, StorageReference):
            parsed = reference
        else:
            parsed = StorageReference.parse(reference)
        self.objects[str(parsed)] = data
        return PutResult(parsed, len(data), checksum)


def _realistic_full_inline_payload() -> dict[str, object]:
    ordinary_page = {
        "page_number": 2,
        "page_index": 1,
        "local_page_index": 0,
        "source_page_range": {"page_start": 2, "page_end": 2},
        "width": 612.0,
        "height": 792.0,
        "markdown": "Ordinary OCR page",
        "blocks": [{"type": "paragraph", "text": "Ordinary OCR page"}],
        "metadata": {
            "provider_page_index": 0,
            "original_page_index": 1,
            "original_page_number": 2,
            "source_unit_id": "pdf-page:000002",
        },
    }
    return {
        "ok": True,
        "schema_version": "2026-07-10",
        "build_tag": "test-modal-build",
        "job_id": "pdf-job-test",
        "request_id": "request-test",
        "status": "completed",
        "profile": "full",
        "result_artifact": None,
        "documents": [
            {
                "document_id": "document-test",
                "status": "completed",
                "pages_total": 1,
                "pages_completed": 1,
                "tasks_total": 1,
                "tasks_completed": 1,
                "failed_tasks": 0,
                "pages": [
                    {
                        "page_number": 2,
                        "page_index": 1,
                        "markdown": "Ordinary OCR page",
                        "blocks": [
                            {"type": "paragraph", "text": "Ordinary OCR page"}
                        ],
                    }
                ],
                "raw_result": [ordinary_page],
                "error": None,
            }
        ],
        "statistics": {"documents_total": 1, "pages_total": 1},
        "diagnostics": {"artifact_generated": False},
        "error": None,
    }


def _ingested_envelope():
    storage = RecordingStorage()
    payload = _realistic_full_inline_payload()
    envelope = ingest_inline_result(
        storage=storage,
        identity=RawResultIdentity(
            atlas_attempt_id="pdf-ingest-test",
            atlas_correlation_id="correlation-test",
            document_id="document-test",
            source_file_id="source-file-test",
            provider_name="paddle-vl-api",
            provider_job_id="pdf-job-test",
            provider_request_id="request-test",
            provider_result_profile="full",
            provider_result_status="provider_completed",
        ),
        source=RawResultSourceProvenance(
            source_checksum_sha256="a" * 64,
            source_media_type="application/pdf",
        ),
        provider=RawResultProviderProvenance(
            build_tag="test-modal-build",
            configuration={"profile": "full", "status": "provider_completed"},
            capabilities={"result_profiles": ["summary", "standard", "full"]},
            timestamps={"completed_at": "2026-08-05T21:00:00Z"},
            warnings=({"code": "TEST_WARNING"},),
            errors=(),
        ),
        inline_result=payload,
        page_summary=RawResultPageSummary(
            page_count_observed=13,
            first_source_page=1,
            last_source_page=13,
            mapping_valid=True,
        ),
    )
    stored = next(iter(storage.objects.values()))
    assert json.loads(stored.decode("utf-8"))["profile"] == "full"
    return envelope


def test_legacy_dataclass_replace_reproduces_mappingproxy_type_error():
    envelope = _ingested_envelope()

    with pytest.raises(TypeError, match="mappingproxy"):
        replace(
            envelope.provider,
            configuration={"provider_input_kind": "presentation_subset"},
        )


def test_safe_rebuild_preserves_frozen_provider_metadata_after_inline_ingest():
    envelope = _ingested_envelope()
    configuration = {
        "profile": "full",
        "status": "provider_completed",
        "provider_input_kind": "presentation_ordinary_page_subset_pdf",
        "provider_input_page_count": 7,
        "presentation_render_page_count": 13,
    }

    rebuilt = _rebuild_presentation_provider_provenance(
        envelope.provider,
        configuration,
    )

    assert rebuilt.build_tag == "test-modal-build"
    assert rebuilt.configuration["provider_input_page_count"] == 7
    assert rebuilt.configuration["presentation_render_page_count"] == 13
    assert tuple(rebuilt.capabilities["result_profiles"]) == (
        "summary",
        "standard",
        "full",
    )
    assert rebuilt.timestamps["completed_at"] == "2026-08-05T21:00:00Z"
    assert rebuilt.warnings[0]["code"] == "TEST_WARNING"
    assert rebuilt.errors == ()
