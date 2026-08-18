"""Byte-bounded transport sharding for large preprocessed PDF provider inputs."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, fields, replace
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import fitz  # type: ignore[import]

from app.processing.ingestion import canonicalize_inline_json, ingest_artifact_result
from app.processing.integration import (
    EndToEndProcessingIntegrationService,
    IntegrationError,
    ProcessingIntegrationRequest,
    RetainedSourceDescriptor,
)
from app.processing.orchestration import PollingPolicy
from app.processing.pdf_canonicalization import _decode_json_payload, _matching_document
from app.processing.raw_result import (
    RawProcessingResultEnvelope,
    RawResultArtifactMetadata,
    RawResultIdentity,
    RawResultPageSummary,
    RawResultProviderProvenance,
)
from app.processing.transport.dependencies import get_transport_grant_service
from app.processing.transport.models import TransportGrantState
from app.storage.models import StorageReference

_MIB = 1024 * 1024
PROVIDER_TRANSPORT_SHARD_TARGET_BYTES = 80 * _MIB
PROVIDER_TRANSPORT_SHARD_MAX_BYTES = 95 * _MIB


class ProviderTransportShardError(RuntimeError):
    """Safe local failure while planning, materializing, or merging provider shards."""


@dataclass(frozen=True, slots=True)
class ProviderInputShardPlan:
    shard_index: int
    provider_page_start: int
    provider_page_end: int
    provider_page_count: int
    serialized_size_bytes: int


@dataclass(frozen=True, slots=True)
class ProviderShardEvidence:
    plan: ProviderInputShardPlan
    provider_job_id: str
    provider_request_id: str
    envelope: RawProcessingResultEnvelope = field(repr=False)


@dataclass(frozen=True, slots=True)
class ProviderTransportShardRunResult:
    canonicalization: Any | None
    raw_result: RawProcessingResultEnvelope | None = field(repr=False)
    error: Exception | None = field(default=None, repr=False)
    cleanup_safe: bool = False
    submission_started: bool = False
    shard_count: int = 0


Diagnostic = Callable[..., None]


def provider_transport_sharding_required(
    provider_input: Any,
    *,
    target_bytes: int = PROVIDER_TRANSPORT_SHARD_TARGET_BYTES,
) -> bool:
    _validate_limits(target_bytes, PROVIDER_TRANSPORT_SHARD_MAX_BYTES)
    page_count = _provider_page_count(provider_input)
    return page_count > 0 and _provider_byte_size(provider_input) > target_bytes


def plan_provider_input_shards(
    storage: Any,
    provider_input: Any,
    *,
    target_bytes: int = PROVIDER_TRANSPORT_SHARD_TARGET_BYTES,
    max_bytes: int = PROVIDER_TRANSPORT_SHARD_MAX_BYTES,
) -> tuple[ProviderInputShardPlan, ...]:
    """Plan PDF page-boundary shards without lowering rendering quality.

    ``serialized_size_bytes`` is planning evidence, not an integrity invariant.
    PyMuPDF can emit slightly different object-table/document-ID bytes when the
    same page range is serialized again for materialization. The materialized
    shard is therefore re-checked independently against ``max_bytes``.
    """
    _validate_limits(target_bytes, max_bytes)
    page_count = _provider_page_count(provider_input)
    if page_count <= 0 or _provider_byte_size(provider_input) <= target_bytes:
        return ()

    content = _provider_pdf_bytes(storage, provider_input)
    document = fitz.open(stream=content, filetype="pdf")
    try:
        if document.page_count != page_count:
            raise ProviderTransportShardError(
                "provider PDF page count does not match provider page map"
            )
        plans: list[ProviderInputShardPlan] = []
        average_bytes_per_page = max(1.0, len(content) / page_count)
        candidate_page_cap = max(
            1,
            int(target_bytes / average_bytes_per_page * 1.10),
        )
        start = 0
        while start < page_count:
            end, size = _largest_target_bounded_range(
                document,
                start,
                target_bytes=target_bytes,
                max_bytes=max_bytes,
                candidate_page_cap=candidate_page_cap,
            )
            plans.append(
                ProviderInputShardPlan(
                    shard_index=len(plans),
                    provider_page_start=start,
                    provider_page_end=end,
                    provider_page_count=end - start + 1,
                    serialized_size_bytes=size,
                )
            )
            start = end + 1
        return tuple(plans)
    finally:
        document.close()


def materialize_provider_input_shard(
    storage: Any,
    provider_input: Any,
    plan: ProviderInputShardPlan,
    *,
    shard_count: int,
    max_bytes: int = PROVIDER_TRANSPORT_SHARD_MAX_BYTES,
) -> Any:
    """Create one shard input while keeping the full render PDF unchanged."""
    if shard_count <= 1 or not 0 <= plan.shard_index < shard_count:
        raise ProviderTransportShardError("provider shard index/count is invalid")
    content = _provider_pdf_bytes(storage, provider_input)
    document = fitz.open(stream=content, filetype="pdf")
    try:
        if not 0 <= plan.provider_page_start <= plan.provider_page_end < document.page_count:
            raise ProviderTransportShardError("provider shard page range is invalid")
        shard_bytes = _serialize_page_range(
            document,
            plan.provider_page_start,
            plan.provider_page_end,
        )
    finally:
        document.close()

    # The planning serialization and this materialization serialization need not
    # have byte-for-byte identical PDF object tables. The hard invariant is that
    # the bytes actually granted to the provider remain under the safety ceiling.
    if len(shard_bytes) > max_bytes:
        raise ProviderTransportShardError(
            "materialized provider shard exceeds transport safety maximum"
        )

    page_map = _provider_page_map(provider_input)
    selected = page_map[plan.provider_page_start : plan.provider_page_end + 1]
    if len(selected) != plan.provider_page_count:
        raise ProviderTransportShardError("provider shard page map is incomplete")

    local_map: list[dict[str, object]] = []
    shard_pages: list[dict[str, object]] = []
    manifest_pages = _manifest_page_map(provider_input)
    for local_index, original in enumerate(selected):
        original_page_number = int(original["original_page_number"])
        source_unit_id = str(original["source_unit_id"])
        local_map.append(
            {
                **dict(original),
                "provider_page_index": local_index,
                "original_page_index": local_index,
                "original_page_number": local_index + 1,
                "source_unit_id": source_unit_id,
            }
        )
        original_manifest = manifest_pages.get(original_page_number, {})
        shard_pages.append(
            {
                **_json_clone(original_manifest),
                "page_number": local_index + 1,
                "source_unit_id": source_unit_id,
                "ocr_route": "modal_paddle_ocr",
            }
        )

    shard_manifest = _json_clone(getattr(provider_input, "presentation_manifest", {}))
    shard_manifest.update(
        {
            "page_count": plan.provider_page_count,
            "provider_page_count": plan.provider_page_count,
            "presentation_page_count": 0,
            "native_text_page_count": 0,
            "local_result_page_count": 0,
            "pages": shard_pages,
            "provider_page_map": local_map,
            "provider_transport_shard": {
                "shard_index": plan.shard_index,
                "shard_count": shard_count,
                "full_provider_page_start": plan.provider_page_start,
                "full_provider_page_end": plan.provider_page_end,
                "full_provider_original_page_numbers": [
                    int(item["original_page_number"]) for item in selected
                ],
            },
        }
    )

    checksum = hashlib.sha256(shard_bytes).hexdigest()
    reference = _shard_reference(
        str(getattr(provider_input, "processing_attempt_id")),
        plan.shard_index,
        checksum,
    )
    filename = _shard_filename(
        str(getattr(provider_input, "provider_filename", "provider.pdf")),
        plan.shard_index,
        shard_count,
    )
    updates = {
        "provider_storage_reference": reference,
        "provider_checksum_sha256": checksum,
        "provider_byte_size": len(shard_bytes),
        "provider_filename": filename,
        "provider_page_count": plan.provider_page_count,
        "provider_page_map": tuple(local_map),
        "presentation_manifest": shard_manifest,
    }
    field_names = {item.name for item in fields(provider_input)}
    if "provider_pdf_bytes" in field_names:
        # Production presentation lifecycle deliberately defers storing the
        # provider subset until grant creation. Preserve that lifecycle here.
        updates["provider_pdf_bytes"] = shard_bytes
    else:
        storage.put(
            shard_bytes,
            reference,
            expected_size=len(shard_bytes),
            expected_sha256=checksum,
        )
    return replace(provider_input, **updates)


def merge_provider_shard_results(
    storage: Any,
    provider_input: Any,
    evidence: Sequence[ProviderShardEvidence],
    *,
    logical_provider_job_id: str,
    logical_provider_request_id: str | None,
    target_bytes: int = PROVIDER_TRANSPORT_SHARD_TARGET_BYTES,
    max_bytes: int = PROVIDER_TRANSPORT_SHARD_MAX_BYTES,
) -> RawProcessingResultEnvelope:
    """Merge shard evidence in provider order, then restore original pages once."""
    if not evidence:
        raise ProviderTransportShardError("provider shard evidence is empty")
    ordered = sorted(evidence, key=lambda item: item.plan.shard_index)
    if [item.plan.shard_index for item in ordered] != list(range(len(ordered))):
        raise ProviderTransportShardError("provider shard evidence indexes are not contiguous")

    first = ordered[0].envelope
    raw_pages: list[dict[str, object]] = []
    for item in ordered:
        envelope = item.envelope
        if (
            envelope.identity.document_id != first.identity.document_id
            or envelope.identity.source_file_id != first.identity.source_file_id
            or envelope.identity.atlas_attempt_id != first.identity.atlas_attempt_id
            or envelope.identity.provider_name != first.identity.provider_name
            or envelope.source != first.source
        ):
            raise ProviderTransportShardError(
                "provider shard evidence identity/provenance mismatch"
            )
        retained = storage.get(envelope.ingestion.storage_reference)
        payload = _decode_json_payload(envelope, retained)
        document = _matching_document(payload, first.identity.document_id)
        pages = document.get("raw_result")
        if not isinstance(pages, list) or len(pages) != item.plan.provider_page_count:
            raise ProviderTransportShardError(
                "provider shard raw result page count does not match its plan"
            )
        if not all(isinstance(page, Mapping) for page in pages):
            raise ProviderTransportShardError("provider shard raw result page is malformed")
        raw_pages.extend(dict(page) for page in pages)

    if len(raw_pages) != _provider_page_count(provider_input):
        raise ProviderTransportShardError(
            "merged provider shard page count does not cover the full provider input"
        )

    # Shard-local remapping deliberately preserves global source_unit_id values.
    # Concatenate in full provider-page order and invoke the existing full-document
    # remapper once, so presentation/native local pages are injected exactly once.
    from app.processing import pdf_page_presentation_bridge as presentation

    full_pages = presentation._remap_raw_pages(raw_pages, provider_input)
    page_numbers = [int(page["page_number"]) for page in full_pages]
    if page_numbers != list(range(1, len(full_pages) + 1)):
        raise ProviderTransportShardError(
            "merged provider shard result does not restore contiguous original pages"
        )

    build_tag = _consistent_provider_value(
        [item.envelope.provider.build_tag for item in ordered], "build_tag"
    )
    model_version = _consistent_provider_value(
        [item.envelope.provider.model_version for item in ordered], "model_version"
    )
    pipeline_version = _consistent_provider_value(
        [item.envelope.provider.pipeline_version for item in ordered],
        "pipeline_version",
    )
    configuration = _thaw(first.provider.configuration)
    configuration.update(
        {
            "provider_input_checksum_sha256": str(
                getattr(provider_input, "provider_checksum_sha256")
            ),
            "provider_input_size_bytes": _provider_byte_size(provider_input),
            "provider_input_page_count": _provider_page_count(provider_input),
            "provider_input_filename": str(
                getattr(provider_input, "provider_filename", "provider.pdf")
            ),
            "provider_transport_sharded": True,
            "provider_transport_shard_target_bytes": target_bytes,
            "provider_transport_shard_max_bytes": max_bytes,
            "provider_transport_shard_count": len(ordered),
            "provider_transport_shards": [
                {
                    "shard_index": item.plan.shard_index,
                    "provider_page_start": item.plan.provider_page_start,
                    "provider_page_end": item.plan.provider_page_end,
                    "provider_page_count": item.plan.provider_page_count,
                    "serialized_size_bytes": item.plan.serialized_size_bytes,
                    "provider_job_id": item.provider_job_id,
                    "provider_request_id": item.provider_request_id,
                }
                for item in ordered
            ],
        }
    )
    provider = RawResultProviderProvenance(
        build_tag=build_tag,
        model_version=model_version,
        pipeline_version=pipeline_version,
        configuration=configuration,
        capabilities=_thaw(first.provider.capabilities),
        timestamps={},
        warnings=tuple(
            warning
            for item in ordered
            for warning in item.envelope.provider.warnings
        ),
        errors=tuple(
            error for item in ordered for error in item.envelope.provider.errors
        ),
    )
    identity = RawResultIdentity(
        first.identity.atlas_attempt_id,
        logical_provider_request_id,
        first.identity.document_id,
        first.identity.source_file_id,
        first.identity.provider_name,
        logical_provider_job_id,
        logical_provider_request_id,
        first.identity.provider_result_profile,
        "completed",
    )
    payload = [{"document_id": first.identity.document_id, "raw_result": full_pages}]
    compressed = gzip.compress(canonicalize_inline_json(payload))
    checksum = hashlib.sha256(compressed).hexdigest()
    artifact = RawResultArtifactMetadata(
        artifact_id=f"{logical_provider_job_id}-merged-shards",
        media_type="json.gz",
        compression="gzip",
        size_bytes=len(compressed),
        checksum_sha256=checksum,
        provider_metadata={
            "provider_transport_sharded": True,
            "provider_transport_shard_count": len(ordered),
        },
    )
    page_summary = RawResultPageSummary(
        page_count_observed=len(full_pages),
        first_source_page=1 if full_pages else None,
        last_source_page=len(full_pages) if full_pages else None,
        missing_pages=(),
        duplicate_pages=(),
        mapping_valid=True,
        source_ranges_represented=tuple((number, number) for number in page_numbers),
    )
    return ingest_artifact_result(
        storage=storage,
        identity=identity,
        source=first.source,
        provider=provider,
        artifact_bytes=compressed,
        artifact_metadata=artifact,
        page_summary=page_summary,
    )


async def run_provider_transport_shards(
    *,
    storage: Any,
    client: Any,
    provider_input: Any,
    descriptor: RetainedSourceDescriptor,
    processing_attempt_id: str,
    logical_provider_job_id: str,
    logical_provider_request_id: str,
    result_profile: str,
    provider_job_options: dict[str, Any],
    public_origin: str | None,
    polling_policy: PollingPolicy,
    canonicalizer: Any,
    diagnostic: Diagnostic,
    target_bytes: int = PROVIDER_TRANSPORT_SHARD_TARGET_BYTES,
    max_bytes: int = PROVIDER_TRANSPORT_SHARD_MAX_BYTES,
) -> ProviderTransportShardRunResult:
    """Run transport shards sequentially so this fix adds no compute concurrency."""
    plans = plan_provider_input_shards(
        storage,
        provider_input,
        target_bytes=target_bytes,
        max_bytes=max_bytes,
    )
    if not plans:
        raise ProviderTransportShardError("provider transport sharding was not required")

    diagnostic(
        "PDF_PROVIDER_SHARD_PLAN_CREATED",
        processing_attempt_id=processing_attempt_id,
        provider_input_size_bytes=_provider_byte_size(provider_input),
        provider_input_page_count=_provider_page_count(provider_input),
        shard_count=len(plans),
        shard_target_bytes=target_bytes,
        shard_max_bytes=max_bytes,
    )

    cleanup_safe = True
    submission_started = False
    evidence: list[ProviderShardEvidence] = []
    from app.processing import pdf_geometry_integration as integration

    for plan in plans:
        shard_number = plan.shard_index + 1
        shard_input = materialize_provider_input_shard(
            storage,
            provider_input,
            plan,
            shard_count=len(plans),
            max_bytes=max_bytes,
        )
        actual_plan = replace(
            plan,
            serialized_size_bytes=_provider_byte_size(shard_input),
        )
        job_id = f"{logical_provider_job_id}-s{shard_number:03d}"
        request_id = f"{logical_provider_request_id}-s{shard_number:03d}"
        provider = integration.ProviderInputChecksumProvider(client, shard_input)
        orchestrator = integration.ProviderInputAwareProcessingOrchestrator(
            provider=provider,
            storage=storage,
            provider_input=shard_input,
        )
        grant_service = integration.ProviderInputGrantService(
            get_transport_grant_service(),
            shard_input,
        )
        service = EndToEndProcessingIntegrationService(
            grant_service=grant_service,
            orchestrator=orchestrator,
            canonicalizer=None,
            public_origin=public_origin,
            polling_policy=polling_policy,
        )
        request = ProcessingIntegrationRequest(
            processing_attempt_id=processing_attempt_id,
            correlation_id=request_id,
            retained_source=descriptor,
            provider_name="paddle-vl",
            provider_job_id=job_id,
            provider_request_id=request_id,
            result_profile=result_profile,
            provider_job_options=provider_job_options,
        )
        diagnostic(
            "PDF_PROVIDER_SHARD_REQUEST_STARTED",
            processing_attempt_id=processing_attempt_id,
            provider_job_id=job_id,
            shard_index=actual_plan.shard_index,
            shard_count=len(plans),
            provider_page_start=actual_plan.provider_page_start,
            provider_page_end=actual_plan.provider_page_end,
            provider_page_count=actual_plan.provider_page_count,
            shard_planned_size_bytes=plan.serialized_size_bytes,
            shard_size_bytes=actual_plan.serialized_size_bytes,
        )
        submission_started = True
        try:
            outcome = await service.process(request)
        except IntegrationError as exc:
            shard_cleanup_safe = _cleanup_safe_from_integration_error(exc)
            cleanup_safe = cleanup_safe and shard_cleanup_safe
            _delete_shard_provider_input_if_safe(
                storage,
                shard_input,
                cleanup_safe=shard_cleanup_safe,
                diagnostic=diagnostic,
                processing_attempt_id=processing_attempt_id,
                provider_job_id=job_id,
                shard_index=actual_plan.shard_index,
            )
            diagnostic(
                "PDF_PROVIDER_SHARD_FAILED",
                processing_attempt_id=processing_attempt_id,
                provider_job_id=job_id,
                shard_index=actual_plan.shard_index,
                error_category=exc.category.value,
                cleanup_safe=shard_cleanup_safe,
            )
            return ProviderTransportShardRunResult(
                None, None, exc, cleanup_safe, submission_started, len(plans)
            )
        except asyncio.CancelledError:
            # Cancellation can occur while provider submission is active. Keep the
            # shard source unless the integration service itself has finalized it.
            raise
        except Exception as exc:
            return ProviderTransportShardRunResult(
                None, None, exc, False, submission_started, len(plans)
            )

        shard_cleanup_safe = bool(
            outcome.revocation_succeeded
            or outcome.grant_final_state is TransportGrantState.REVOKED
        )
        cleanup_safe = cleanup_safe and shard_cleanup_safe
        _delete_shard_provider_input_if_safe(
            storage,
            shard_input,
            cleanup_safe=shard_cleanup_safe,
            diagnostic=diagnostic,
            processing_attempt_id=processing_attempt_id,
            provider_job_id=job_id,
            shard_index=actual_plan.shard_index,
        )
        diagnostic(
            "PDF_PROVIDER_SHARD_TERMINAL",
            processing_attempt_id=processing_attempt_id,
            provider_job_id=job_id,
            shard_index=actual_plan.shard_index,
            phase=outcome.integration_terminal_phase.value,
            provider_status=(
                outcome.provider_terminal_status.value
                if outcome.provider_terminal_status is not None
                else None
            ),
            error_category=(
                outcome.error.category.value if outcome.error is not None else None
            ),
            raw_result_retained=outcome.raw_result is not None,
            cleanup_safe=shard_cleanup_safe,
        )
        if outcome.error is not None:
            return ProviderTransportShardRunResult(
                None,
                outcome.raw_result,
                outcome.error,
                cleanup_safe,
                submission_started,
                len(plans),
            )
        if outcome.raw_result is None:
            return ProviderTransportShardRunResult(
                None,
                None,
                ProviderTransportShardError(
                    "provider shard completed without retained raw result"
                ),
                cleanup_safe,
                submission_started,
                len(plans),
            )
        evidence.append(
            ProviderShardEvidence(actual_plan, job_id, request_id, outcome.raw_result)
        )

    try:
        merged = merge_provider_shard_results(
            storage,
            provider_input,
            evidence,
            logical_provider_job_id=logical_provider_job_id,
            logical_provider_request_id=logical_provider_request_id,
            target_bytes=target_bytes,
            max_bytes=max_bytes,
        )
        diagnostic(
            "PDF_PROVIDER_SHARDS_MERGED",
            processing_attempt_id=processing_attempt_id,
            provider_job_id=logical_provider_job_id,
            shard_count=len(plans),
            payload_size_bytes=merged.ingestion.payload_size_bytes,
            page_count_observed=(
                merged.ingestion.page_summary.page_count_observed
                if merged.ingestion.page_summary is not None
                else None
            ),
        )
        canonical = await asyncio.to_thread(canonicalizer.canonicalize, merged)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return ProviderTransportShardRunResult(
            None, None, exc, cleanup_safe, submission_started, len(plans)
        )
    return ProviderTransportShardRunResult(
        canonical, merged, None, cleanup_safe, submission_started, len(plans)
    )


def _delete_shard_provider_input_if_safe(
    storage: Any,
    shard_input: Any,
    *,
    cleanup_safe: bool,
    diagnostic: Diagnostic,
    processing_attempt_id: str,
    provider_job_id: str,
    shard_index: int,
) -> None:
    """Delete a materialized shard only after its transport grant is revoked."""
    if not cleanup_safe:
        diagnostic(
            "PDF_PROVIDER_SHARD_INPUT_RETAINED",
            processing_attempt_id=processing_attempt_id,
            provider_job_id=provider_job_id,
            shard_index=shard_index,
            reason="provider_submission_may_still_be_active",
        )
        return
    reference = getattr(shard_input, "provider_storage_reference", None)
    if reference is None:
        return
    try:
        storage.delete(reference)
    except Exception:
        # Deletion can already have happened in deferred-subset grant failure
        # cleanup. Do not convert a successful provider result into a failure.
        diagnostic(
            "PDF_PROVIDER_SHARD_INPUT_DELETE_WARNING",
            processing_attempt_id=processing_attempt_id,
            provider_job_id=provider_job_id,
            shard_index=shard_index,
        )
    else:
        diagnostic(
            "PDF_PROVIDER_SHARD_INPUT_DELETED",
            processing_attempt_id=processing_attempt_id,
            provider_job_id=provider_job_id,
            shard_index=shard_index,
        )


def _largest_target_bounded_range(
    document: fitz.Document,
    start: int,
    *,
    target_bytes: int,
    max_bytes: int,
    candidate_page_cap: int,
) -> tuple[int, int]:
    low = start
    high = min(document.page_count - 1, start + max(1, candidate_page_cap) - 1)
    best_end: int | None = None
    best_size: int | None = None
    while low <= high:
        midpoint = (low + high) // 2
        payload = _serialize_page_range(document, start, midpoint)
        size = len(payload)
        if size <= target_bytes:
            best_end = midpoint
            best_size = size
            low = midpoint + 1
        else:
            high = midpoint - 1
    if best_end is not None and best_size is not None:
        return best_end, best_size

    single = _serialize_page_range(document, start, start)
    if len(single) > max_bytes:
        raise ProviderTransportShardError(
            "single provider PDF page exceeds transport shard safety maximum"
        )
    return start, len(single)


def _serialize_page_range(document: fitz.Document, start: int, end: int) -> bytes:
    output = fitz.open()
    try:
        if document.metadata:
            output.set_metadata(document.metadata)
        output.insert_pdf(document, from_page=start, to_page=end)
        return output.tobytes(garbage=4, deflate=True)
    finally:
        output.close()


def _provider_pdf_bytes(storage: Any, provider_input: Any) -> bytes:
    content = getattr(provider_input, "provider_pdf_bytes", None)
    if content is None:
        provider_reference = getattr(provider_input, "provider_storage_reference", None)
        render_reference = getattr(provider_input, "storage_reference", None)
        if provider_reference == render_reference:
            content = getattr(getattr(provider_input, "preprocessing", None), "pdf_bytes", None)
    if content is None:
        reference = getattr(provider_input, "provider_storage_reference", None)
        if reference is not None:
            content = storage.get(reference)
    if not isinstance(content, bytes) or not content.startswith(b"%PDF-"):
        raise ProviderTransportShardError("provider PDF bytes are unavailable")
    if len(content) != _provider_byte_size(provider_input):
        raise ProviderTransportShardError("provider PDF size does not match metadata")
    checksum = hashlib.sha256(content).hexdigest()
    if checksum.lower() != str(getattr(provider_input, "provider_checksum_sha256")).lower():
        raise ProviderTransportShardError("provider PDF checksum does not match metadata")
    return content


def _provider_page_count(provider_input: Any) -> int:
    value = getattr(provider_input, "provider_page_count", None)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProviderTransportShardError("provider page count is invalid")
    return value


def _provider_byte_size(provider_input: Any) -> int:
    value = getattr(provider_input, "provider_byte_size", None)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProviderTransportShardError("provider byte size is invalid")
    return value


def _provider_page_map(provider_input: Any) -> list[dict[str, object]]:
    value = getattr(provider_input, "provider_page_map", None)
    if not isinstance(value, (tuple, list)):
        raise ProviderTransportShardError("provider page map is unavailable")
    result: list[dict[str, object]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise ProviderTransportShardError("provider page map entry is malformed")
        if int(item.get("provider_page_index", -1)) != index:
            raise ProviderTransportShardError("provider page map indexes are not contiguous")
        if not isinstance(item.get("original_page_number"), int):
            raise ProviderTransportShardError("provider page map original page number is invalid")
        if not isinstance(item.get("original_page_index"), int):
            raise ProviderTransportShardError("provider page map original page index is invalid")
        if not isinstance(item.get("source_unit_id"), str) or not str(item["source_unit_id"]).strip():
            raise ProviderTransportShardError("provider page map source unit is invalid")
        result.append(dict(item))
    if len(result) != _provider_page_count(provider_input):
        raise ProviderTransportShardError("provider page map length does not match page count")
    return result


def _manifest_page_map(provider_input: Any) -> dict[int, dict[str, object]]:
    manifest = getattr(provider_input, "presentation_manifest", None)
    if not isinstance(manifest, Mapping):
        return {}
    pages = manifest.get("pages")
    if not isinstance(pages, list):
        return {}
    result: dict[int, dict[str, object]] = {}
    for page in pages:
        if isinstance(page, Mapping) and isinstance(page.get("page_number"), int):
            result[int(page["page_number"])] = dict(page)
    return result


def _shard_reference(
    processing_attempt_id: str,
    shard_index: int,
    checksum: str,
) -> StorageReference:
    digest = hashlib.sha256(
        (
            "atlas-pdf-provider-transport-shard-v1\x1f"
            f"{processing_attempt_id}\x1f{shard_index}\x1f{checksum}"
        ).encode("utf-8")
    ).hexdigest()[:32]
    return StorageReference.parse(f"src_{digest}")


def _shard_filename(filename: str, shard_index: int, shard_count: int) -> str:
    stem = Path(filename or "provider.pdf").stem or "provider"
    return f"{stem}.transport-{shard_index + 1:03d}-of-{shard_count:03d}.pdf"


def _consistent_provider_value(values: Sequence[str | None], name: str) -> str | None:
    distinct = {value for value in values if value is not None}
    if len(distinct) > 1:
        raise ProviderTransportShardError(
            f"provider shard {name} changed during one logical processing attempt"
        )
    return next(iter(distinct), None)


def _cleanup_safe_from_integration_error(exc: IntegrationError) -> bool:
    return bool(
        exc.revocation_succeeded
        or exc.grant_final_state is TransportGrantState.REVOKED
    )


def _validate_limits(target_bytes: int, max_bytes: int) -> None:
    if (
        not isinstance(target_bytes, int)
        or isinstance(target_bytes, bool)
        or target_bytes <= 0
        or not isinstance(max_bytes, int)
        or isinstance(max_bytes, bool)
        or max_bytes <= 0
        or target_bytes > max_bytes
    ):
        raise ValueError("provider transport shard byte limits are invalid")


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return tuple(_thaw(child) for child in value)
    if isinstance(value, frozenset):
        return set(_thaw(child) for child in value)
    return value


__all__ = [
    "PROVIDER_TRANSPORT_SHARD_MAX_BYTES",
    "PROVIDER_TRANSPORT_SHARD_TARGET_BYTES",
    "ProviderInputShardPlan",
    "ProviderShardEvidence",
    "ProviderTransportShardError",
    "ProviderTransportShardRunResult",
    "materialize_provider_input_shard",
    "merge_provider_shard_results",
    "plan_provider_input_shards",
    "provider_transport_sharding_required",
    "run_provider_transport_shards",
]
