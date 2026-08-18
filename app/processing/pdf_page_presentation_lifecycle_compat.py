"""Preserve presentation lifecycle, provenance, and boundary-review safety."""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
from typing import Any, Mapping

from app.processing import pdf_page_presentation_bridge as bridge
from app.processing import pdf_page_presentation_preprocess_compat as preprocess
from app.storage.models import PutResult, StorageReference

_INSTALLED = False
_BasePresentationProviderInput = bridge.PresentationProviderInput
_OriginalPrepare = preprocess.prepare_presentation_provider_input_v2


@dataclass(frozen=True, slots=True)
class DeferredPresentationProviderInput(_BasePresentationProviderInput):
    """Provider input that keeps a mixed-page subset in memory until grant creation."""

    provider_pdf_bytes: bytes | None = None


class _DeferredProviderStorage:
    """Delegate all storage writes except the mixed-page provider subset."""

    def __init__(self, delegate: Any, processing_attempt_id: str) -> None:
        self._delegate = delegate
        self._processing_attempt_id = processing_attempt_id
        self.provider_pdf_bytes: bytes | None = None
        self.provider_reference: StorageReference | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def put(
        self,
        content: bytes,
        reference: StorageReference,
        *,
        expected_size: int,
        expected_sha256: str,
    ) -> PutResult:
        expected_provider_reference = bridge._provider_reference(
            self._processing_attempt_id,
            expected_sha256,
        )
        if reference != expected_provider_reference:
            return self._delegate.put(
                content,
                reference,
                expected_size=expected_size,
                expected_sha256=expected_sha256,
            )

        if not isinstance(content, bytes):
            raise TypeError("provider subset content must be bytes")
        if len(content) != int(expected_size):
            raise ValueError("provider subset size does not match metadata")
        checksum = hashlib.sha256(content).hexdigest()
        if checksum.lower() != str(expected_sha256).lower():
            raise ValueError("provider subset checksum does not match metadata")
        self.provider_pdf_bytes = content
        self.provider_reference = reference
        return PutResult(
            reference=reference,
            byte_size=len(content),
            checksum_sha256=checksum,
        )


def prepare_presentation_provider_input_deferred(
    *,
    storage: Any,
    source_pdf_bytes: bytes,
    original_filename: str | None,
    processing_attempt_id: str,
    expected_page_count: int | None = None,
) -> DeferredPresentationProviderInput:
    """Build the mixed-page subset without retaining it before grant creation."""

    proxy = _DeferredProviderStorage(storage, processing_attempt_id)
    result = _OriginalPrepare(
        storage=proxy,
        source_pdf_bytes=source_pdf_bytes,
        original_filename=original_filename,
        processing_attempt_id=processing_attempt_id,
        expected_page_count=expected_page_count,
    )
    if not isinstance(result, DeferredPresentationProviderInput):
        raise TypeError("presentation provider input compatibility was not installed")
    if proxy.provider_pdf_bytes is None:
        return result
    if proxy.provider_reference != result.provider_storage_reference:
        raise RuntimeError("deferred provider subset reference mismatch")
    if result.provider_storage_reference == result.storage_reference:
        raise RuntimeError("deferred provider subset must use a distinct reference")
    return replace(result, provider_pdf_bytes=proxy.provider_pdf_bytes)


def _store_deferred_subset(provider_input: Any) -> Any | None:
    content = getattr(provider_input, "provider_pdf_bytes", None)
    if content is None:
        return None
    if provider_input.provider_storage_reference == provider_input.storage_reference:
        raise RuntimeError("provider subset reference must differ from render reference")

    from app.storage.dependencies import get_storage_provider

    storage = get_storage_provider()
    put = storage.put(
        content,
        provider_input.provider_storage_reference,
        expected_size=provider_input.provider_byte_size,
        expected_sha256=provider_input.provider_checksum_sha256,
    )
    if put.reference != provider_input.provider_storage_reference:
        raise RuntimeError("stored provider subset reference mismatch")
    if put.byte_size != provider_input.provider_byte_size:
        raise RuntimeError("stored provider subset size mismatch")
    if put.checksum_sha256.lower() != provider_input.provider_checksum_sha256.lower():
        raise RuntimeError("stored provider subset checksum mismatch")
    return storage


def _presentation_provenance_configuration(
    configuration: Any,
    provider_input: Any,
) -> dict[str, Any]:
    """Record the bytes Paddle received separately from the retained render PDF."""

    from app.processing import pdf_geometry_integration as integration

    result = integration._thaw_metadata(configuration)
    result.update(
        {
            "presentation_render_kind": "presentation_full_render_pdf",
            "presentation_render_checksum_sha256": provider_input.checksum_sha256,
            "presentation_render_size_bytes": provider_input.byte_size,
            "presentation_render_media_type": provider_input.media_type,
            "presentation_render_filename": provider_input.filename,
        }
    )
    if int(provider_input.provider_page_count) > 0:
        subset_is_distinct = bool(
            provider_input.provider_storage_reference
            != provider_input.storage_reference
            or provider_input.provider_checksum_sha256
            != provider_input.checksum_sha256
        )
        result.update(
            {
                "provider_input_kind": (
                    "presentation_ordinary_page_subset_pdf"
                    if subset_is_distinct
                    else "presentation_render_pdf"
                ),
                "provider_input_checksum_sha256": (
                    provider_input.provider_checksum_sha256
                ),
                "provider_input_size_bytes": provider_input.provider_byte_size,
                "provider_input_media_type": provider_input.media_type,
                "provider_input_filename": provider_input.provider_filename,
                "provider_input_page_count": provider_input.provider_page_count,
                "provider_submission_status": "submitted",
                "provider_submission_skip_reason": None,
            }
        )
    else:
        result.update(
            {
                "provider_input_kind": "provider_skipped_presentation_only",
                "provider_input_checksum_sha256": None,
                "provider_input_size_bytes": 0,
                "provider_input_media_type": None,
                "provider_input_filename": None,
                "provider_input_page_count": 0,
                "provider_submission_status": "skipped",
                "provider_submission_skip_reason": (
                    "all_pages_classified_as_presentation"
                ),
            }
        )
    return result


def _usable_pre_ocr_boundary_review(page: Mapping[str, object]) -> bool:
    """Return true only when pre-OCR review can replace OCR-aware role review."""

    classification = page.get("page_classification")
    if not isinstance(classification, Mapping):
        return False
    provider = str(classification.get("provider") or "").strip().lower()
    if not provider or provider == "none":
        return False

    role = classification.get("page_role")
    confidence = classification.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or float(confidence) < bridge._validated_min_confidence()
    ):
        return False

    if role == "body":
        return True
    if role not in bridge.PRESENTATION_PAGE_ROLES:
        return False

    return bool(
        classification.get("skip_ocr") is True
        or page.get("ocr_route") == "skipped_presentation_image"
    )


def _pre_reviewed_source_units_confident(
    manifest: Mapping[str, object] | None,
) -> frozenset[str]:
    """Select only boundary pages with a confident, usable pre-OCR decision."""

    if not isinstance(manifest, Mapping):
        return frozenset()
    pages = manifest.get("pages")
    if not isinstance(pages, list):
        return frozenset()
    return frozenset(
        str(page.get("source_unit_id"))
        for page in pages
        if isinstance(page, Mapping)
        and isinstance(page.get("source_unit_id"), str)
        and str(page.get("source_unit_id")).strip()
        and _usable_pre_ocr_boundary_review(page)
    )


def install_presentation_lifecycle_compat() -> None:
    """Install lifecycle cleanup, exact provenance, and safe boundary review."""

    global _INSTALLED
    if _INSTALLED:
        return

    from app.processing import pdf_geometry_integration as integration

    grant_class = integration.ProviderInputGrantService
    original_create_grant = grant_class.create_grant

    def create_grant_with_deferred_subset(self, **kwargs):
        storage = _store_deferred_subset(self._provider_input)
        try:
            return original_create_grant(self, **kwargs)
        except BaseException:
            if storage is not None:
                try:
                    storage.delete(
                        self._provider_input.provider_storage_reference
                    )
                except Exception:
                    bridge._logger.exception(
                        "Could not delete deferred presentation provider subset "
                        "after grant creation failure"
                    )
            raise

    orchestrator_class = integration.ProviderInputAwareProcessingOrchestrator
    original_ingest = orchestrator_class._ingest

    async def ingest_with_presentation_provenance(
        self,
        request,
        result,
        page_summary,
    ):
        envelope = await original_ingest(self, request, result, page_summary)
        provider_input = getattr(self, "provider_input", None)
        required = (
            "checksum_sha256",
            "byte_size",
            "provider_checksum_sha256",
            "provider_byte_size",
            "provider_page_count",
        )
        if provider_input is None or any(
            not hasattr(provider_input, name) for name in required
        ):
            return envelope
        configuration = _presentation_provenance_configuration(
            envelope.provider.configuration,
            provider_input,
        )
        return replace(
            envelope,
            provider=replace(
                envelope.provider,
                configuration=configuration,
            ),
        )

    bridge.PresentationProviderInput = DeferredPresentationProviderInput
    bridge._pre_reviewed_source_units = _pre_reviewed_source_units_confident
    integration.GeometryProviderInput = DeferredPresentationProviderInput
    preprocess.prepare_presentation_provider_input_v2 = (
        prepare_presentation_provider_input_deferred
    )
    bridge.prepare_presentation_provider_input = (
        prepare_presentation_provider_input_deferred
    )
    integration.prepare_geometry_provider_input = (
        prepare_presentation_provider_input_deferred
    )
    grant_class.create_grant = create_grant_with_deferred_subset
    orchestrator_class._ingest = ingest_with_presentation_provenance
    _INSTALLED = True


__all__ = [
    "DeferredPresentationProviderInput",
    "install_presentation_lifecycle_compat",
    "prepare_presentation_provider_input_deferred",
]
