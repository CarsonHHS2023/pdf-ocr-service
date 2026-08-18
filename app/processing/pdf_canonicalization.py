"""Retained PDF raw-result -> Structured Content v2 canonicalization runtime."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import gzip
import hashlib
import json
from typing import Any, Callable

from sqlalchemy import select

from app.models import Document, ProcessingRun, SourceFile
from app.processing.llm_structure_refinement import StructureRefiner
from app.processing.paddle_vl.normalization import normalize_paddle_pdf_raw_result
from app.processing.pdf_recovery import recover_pdf_observations_to_spr_v2
from app.processing.pdf_structure_refinement_images import (
    openai_pdf_structure_refinement_is_configured,
    openai_pdf_structure_refiner_from_env,
)
from app.processing.pdf_visual_assets import (
    candidate_needs_pdf_assets,
    enrich_candidate_with_pdf_visual_assets,
)
from app.processing.raw_result import RawProcessingResultEnvelope, RawResultEvidenceSource
from app.processing.structured_result_v2.model import normalize_spr_v2
from app.storage.base import StorageProvider
from app.storage.models import StorageReference
from app.structured_content_v2.repository import StructuredContentCandidateV2Repository
from app.structured_content_v2.selection import (
    StructuredContentV2Selection,
    StructuredContentV2SelectionNotFound,
    StructuredContentV2SelectionRepository,
)
from app.structured_content_v2.transformation import (
    TransformationContextV2,
    transform_spr_v2_to_candidate,
)


class PdfCanonicalizationError(RuntimeError):
    """Safe failure raised after retained raw evidence could not become canonical content."""


class PdfSelectionDisposition(str, Enum):
    """How canonicalization reconciled the produced candidate with explicit selection."""

    CREATED = "created"
    UNCHANGED = "unchanged"
    PROMOTED = "promoted"
    PRESERVED = "preserved"


SYSTEM_PDF_SELECTION_ACTORS = frozenset(
    {
        "atlas.pdf-ingestion-v2",
        "atlas.pdf-reprocessing-v2",
    }
)


@dataclass(frozen=True, slots=True)
class PdfCanonicalizationOutcome:
    document_ref: str
    source_file_ref: str
    processing_run_ref: str
    raw_result_ref: str
    structured_processing_result_ref: str
    candidate_id: str
    selected_candidate_id: str
    selection_version: int
    selection_disposition: PdfSelectionDisposition
    initial_selection_created: bool


SessionFactory = Callable[[], Any]
StructureRefinerFactory = Callable[[bytes], StructureRefiner | None]


class PdfCanonicalizationService:
    def __init__(
        self,
        *,
        storage: StorageProvider,
        session_factory: SessionFactory,
        candidates: StructuredContentCandidateV2Repository | None = None,
        selections: StructuredContentV2SelectionRepository | None = None,
        structure_refiner_factory: StructureRefinerFactory | None = openai_pdf_structure_refiner_from_env,
        refinement_fail_closed: bool = False,
        render_pdf_storage_reference: StorageReference | str | None = None,
        render_pdf_checksum_sha256: str | None = None,
        render_pdf_source_kind: str = "retained_source_pdf",
    ) -> None:
        self.storage = storage
        self.session_factory = session_factory
        self.candidates = candidates or StructuredContentCandidateV2Repository()
        self.selections = selections or StructuredContentV2SelectionRepository(self.candidates)
        self.structure_refiner_factory = structure_refiner_factory
        self.refinement_fail_closed = refinement_fail_closed
        if isinstance(render_pdf_storage_reference, str):
            render_pdf_storage_reference = StorageReference.parse(render_pdf_storage_reference)
        self.render_pdf_storage_reference = render_pdf_storage_reference
        self.render_pdf_checksum_sha256 = render_pdf_checksum_sha256
        if not isinstance(render_pdf_source_kind, str) or not render_pdf_source_kind.strip():
            raise ValueError("render_pdf_source_kind must be non-empty")
        self.render_pdf_source_kind = render_pdf_source_kind.strip()

    def canonicalize(self, envelope: RawProcessingResultEnvelope) -> PdfCanonicalizationOutcome:
        if not isinstance(envelope, RawProcessingResultEnvelope):
            raise TypeError("envelope must be a RawProcessingResultEnvelope")
        try:
            retained = self.storage.get(envelope.ingestion.storage_reference)
            _verify_retained_bytes(envelope, retained)
            document_payload = _matching_document(
                _decode_json_payload(envelope, retained),
                envelope.identity.document_id,
            )
            raw_pages = document_payload.get("raw_result")
            if not isinstance(raw_pages, list):
                raise PdfCanonicalizationError("retained document raw_result is missing or malformed")

            raw_ref = str(envelope.ingestion.storage_reference)
            processing_run_ref = envelope.identity.atlas_attempt_id
            bundle = normalize_paddle_pdf_raw_result(
                raw_pages,
                document_ref=envelope.identity.document_id,
                source_ref=envelope.identity.source_file_id,
                processing_run_ref=processing_run_ref,
                raw_result_ref=raw_ref,
                provider_ref=envelope.identity.provider_name,
            )

            pdf_bytes: bytes | None = None
            structure_refiner: StructureRefiner | None = None
            refiner_enabled = self.structure_refiner_factory is not None
            if self.structure_refiner_factory is openai_pdf_structure_refiner_from_env:
                refiner_enabled = openai_pdf_structure_refinement_is_configured()
            if refiner_enabled:
                source_session = self.session_factory()
                try:
                    source = _validate_document_and_source(source_session, envelope)
                    pdf_bytes = self._render_pdf_bytes(source)
                finally:
                    source_session.close()
                assert self.structure_refiner_factory is not None
                structure_refiner = self.structure_refiner_factory(pdf_bytes)

            spr = recover_pdf_observations_to_spr_v2(
                bundle,
                structure_refiner=structure_refiner,
                refinement_fail_closed=self.refinement_fail_closed,
            )
            spr_bytes = _canonical_spr_bytes(spr)
            spr_put = self.storage.put(
                spr_bytes,
                _deterministic_spr_reference(spr_bytes),
                expected_size=len(spr_bytes),
                expected_sha256=hashlib.sha256(spr_bytes).hexdigest(),
            )
            spr_ref = str(spr_put.reference)
            candidate_id, lineage_key = _candidate_identity(envelope, spr_put.checksum_sha256)

            prepared_candidate = None
            prepared_candidate_needs_assets = False
            preparation_session = self.session_factory()
            try:
                source = _validate_document_and_source(preparation_session, envelope)
                if not self.candidates.candidate_exists(preparation_session, candidate_id):
                    prepared_candidate = transform_spr_v2_to_candidate(
                        spr,
                        context=TransformationContextV2(
                            document_ref=envelope.identity.document_id,
                            candidate_id=candidate_id,
                            lineage_key=lineage_key,
                            structured_processing_result_ref=spr_ref,
                        ),
                    )
                    prepared_candidate_needs_assets = candidate_needs_pdf_assets(prepared_candidate)
                    if prepared_candidate_needs_assets and pdf_bytes is None:
                        pdf_bytes = self._render_pdf_bytes(source)
            finally:
                preparation_session.close()

            if prepared_candidate_needs_assets:
                assert prepared_candidate is not None
                assert pdf_bytes is not None
                prepared_candidate = enrich_candidate_with_pdf_visual_assets(
                    prepared_candidate,
                    pdf_bytes=pdf_bytes,
                    storage=self.storage,
                    source_kind=self.render_pdf_source_kind,
                )

            session = self.session_factory()
            try:
                now = datetime.utcnow()
                with session.begin():
                    _validate_document_and_source(session, envelope)
                    run = _ensure_processing_run(session, envelope, raw_ref, now)
                    run.structured_processing_result_ref = spr_ref
                    run.raw_result_ref = raw_ref
                    run.status = "running"
                    run.safe_error_code = None
                    run.safe_error_summary = None
                    run.failed_at = None

                    if self.candidates.candidate_exists(session, candidate_id):
                        persisted = self.candidates.get_candidate(session, candidate_id)
                        _validate_replayed_candidate_identity(
                            persisted,
                            envelope=envelope,
                            candidate_id=candidate_id,
                            lineage_key=lineage_key,
                            structured_processing_result_ref=spr_ref,
                        )
                    else:
                        if prepared_candidate is None:
                            raise PdfCanonicalizationError("prepared PDF candidate is unavailable")
                        persisted = self.candidates.create_candidate(session, prepared_candidate)

                    selection, selection_disposition = _select_canonical_candidate(
                        self.selections,
                        session,
                        document_ref=envelope.identity.document_id,
                        candidate_id=persisted.candidate_id,
                    )

                    run.status = "succeeded"
                    run.completed_at = now

                return PdfCanonicalizationOutcome(
                    document_ref=envelope.identity.document_id,
                    source_file_ref=envelope.identity.source_file_id,
                    processing_run_ref=processing_run_ref,
                    raw_result_ref=raw_ref,
                    structured_processing_result_ref=spr_ref,
                    candidate_id=persisted.candidate_id,
                    selected_candidate_id=selection.candidate_id,
                    selection_version=selection.selection_version,
                    selection_disposition=selection_disposition,
                    initial_selection_created=(selection_disposition is PdfSelectionDisposition.CREATED),
                )
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()
        except PdfCanonicalizationError:
            self._record_failure(envelope, "pdf_canonicalization_failed", "retained PDF canonicalization failed")
            raise
        except Exception as exc:
            self._record_failure(envelope, "pdf_canonicalization_failed", "retained PDF canonicalization failed")
            raise PdfCanonicalizationError("retained PDF canonicalization failed") from exc

    def _render_pdf_bytes(self, source: SourceFile) -> bytes:
        if self.render_pdf_storage_reference is None:
            return _retained_source_pdf(self.storage, source)
        data = self.storage.get(self.render_pdf_storage_reference)
        if not isinstance(data, bytes) or not data.startswith(b"%PDF-"):
            raise PdfCanonicalizationError("provider-input PDF is missing or malformed")
        if self.render_pdf_checksum_sha256 is not None:
            checksum = hashlib.sha256(data).hexdigest()
            if checksum.lower() != self.render_pdf_checksum_sha256.lower():
                raise PdfCanonicalizationError("provider-input PDF checksum does not match preprocessing metadata")
        return data

    def _record_failure(self, envelope: RawProcessingResultEnvelope, code: str, summary: str) -> None:
        try:
            session = self.session_factory()
            try:
                now = datetime.utcnow()
                with session.begin():
                    document = session.get(Document, envelope.identity.document_id)
                    source = session.get(SourceFile, envelope.identity.source_file_id)
                    if document is None or source is None or source.document_id != envelope.identity.document_id:
                        return
                    run = session.execute(
                        select(ProcessingRun).where(
                            ProcessingRun.processing_run_id == envelope.identity.atlas_attempt_id
                        )
                    ).scalar_one_or_none()
                    if run is None:
                        session.add(
                            ProcessingRun(
                                processing_run_id=envelope.identity.atlas_attempt_id,
                                document_id=envelope.identity.document_id,
                                source_file_id=envelope.identity.source_file_id,
                                status="failed",
                                provider_ref=envelope.identity.provider_name,
                                raw_result_ref=str(envelope.ingestion.storage_reference),
                                started_at=envelope.ingestion.ingested_at.replace(tzinfo=None),
                                failed_at=now,
                                safe_error_code=code,
                                safe_error_summary=summary,
                            )
                        )
                    elif run.document_id == envelope.identity.document_id and run.source_file_id == envelope.identity.source_file_id:
                        run.status = "failed"
                        run.raw_result_ref = str(envelope.ingestion.storage_reference)
                        run.failed_at = now
                        run.safe_error_code = code
                        run.safe_error_summary = summary
            finally:
                session.close()
        except Exception:
            return


def _select_canonical_candidate(
    selections: StructuredContentV2SelectionRepository,
    session,
    *,
    document_ref: str,
    candidate_id: str,
) -> tuple[StructuredContentV2Selection, PdfSelectionDisposition]:
    try:
        existing = selections.get_selection(session, document_ref)
    except StructuredContentV2SelectionNotFound:
        selection = selections.set_selection(
            session,
            document_ref=document_ref,
            candidate_id=candidate_id,
            expected_version=0,
            selection_actor_ref="atlas.pdf-ingestion-v2",
            reason="initial canonical PDF ingestion",
        )
        return selection, PdfSelectionDisposition.CREATED

    if existing.candidate_id == candidate_id:
        return existing, PdfSelectionDisposition.UNCHANGED

    if existing.selection_actor_ref in SYSTEM_PDF_SELECTION_ACTORS:
        selection = selections.set_selection(
            session,
            document_ref=document_ref,
            candidate_id=candidate_id,
            expected_version=existing.selection_version,
            selection_actor_ref="atlas.pdf-reprocessing-v2",
            reason="promote successfully reprocessed canonical PDF candidate",
        )
        return selection, PdfSelectionDisposition.PROMOTED

    return existing, PdfSelectionDisposition.PRESERVED


def _validate_replayed_candidate_identity(
    candidate,
    *,
    envelope: RawProcessingResultEnvelope,
    candidate_id: str,
    lineage_key: str,
    structured_processing_result_ref: str,
) -> None:
    mismatches: list[str] = []
    if candidate.candidate_id != candidate_id:
        mismatches.append("candidate_id")
    if candidate.document_ref != envelope.identity.document_id:
        mismatches.append("document_ref")
    if candidate.lineage_key != lineage_key:
        mismatches.append("lineage_key")
    if candidate.processing_run_ref != envelope.identity.atlas_attempt_id:
        mismatches.append("processing_run_ref")
    if candidate.structured_processing_result_ref != structured_processing_result_ref:
        mismatches.append("structured_processing_result_ref")
    if mismatches:
        raise PdfCanonicalizationError("persisted PDF candidate identity does not match replay provenance")


def _retained_source_pdf(storage: StorageProvider, source: SourceFile) -> bytes:
    if not source.storage_reference:
        raise PdfCanonicalizationError("retained source PDF storage reference is missing")
    data = storage.get(source.storage_reference)
    if not isinstance(data, bytes) or not data:
        raise PdfCanonicalizationError("retained source PDF is missing or empty")
    if source.byte_size is not None and len(data) != source.byte_size:
        raise PdfCanonicalizationError("retained source PDF size does not match source metadata")
    checksum = hashlib.sha256(data).hexdigest()
    if source.checksum_sha256 is not None and checksum.lower() != source.checksum_sha256.lower():
        raise PdfCanonicalizationError("retained source PDF checksum does not match source metadata")
    return data


def _verify_retained_bytes(envelope: RawProcessingResultEnvelope, retained: bytes) -> None:
    if not isinstance(retained, bytes):
        raise PdfCanonicalizationError("retained raw result must be bytes")
    if len(retained) != envelope.ingestion.payload_size_bytes:
        raise PdfCanonicalizationError("retained raw result size does not match envelope")
    if hashlib.sha256(retained).hexdigest() != envelope.ingestion.payload_sha256:
        raise PdfCanonicalizationError("retained raw result checksum does not match envelope")


def _decode_json_payload(envelope: RawProcessingResultEnvelope, retained: bytes) -> Any:
    data = retained
    compression = envelope.ingestion.payload_compression
    if envelope.ingestion.evidence_source is RawResultEvidenceSource.ARTIFACT_BYTES:
        artifact = envelope.ingestion.artifact_metadata
        compression = artifact.compression if artifact and artifact.compression is not None else compression
    if compression in (None, "", "identity"):
        pass
    elif str(compression).lower() in {"gzip", "gz"}:
        try:
            data = gzip.decompress(data)
        except Exception as exc:
            raise PdfCanonicalizationError("retained gzip raw result could not be decompressed") from exc
    else:
        raise PdfCanonicalizationError("retained raw result compression is unsupported")

    media_type = envelope.ingestion.payload_media_type
    if envelope.ingestion.evidence_source is RawResultEvidenceSource.ARTIFACT_BYTES:
        artifact = envelope.ingestion.artifact_metadata
        if artifact and artifact.media_type:
            media_type = artifact.media_type
    allowed = {"application/json", "application/json; charset=utf-8", "text/json"}
    if envelope.ingestion.evidence_source is RawResultEvidenceSource.ARTIFACT_BYTES:
        allowed.update({"json.gz", "application/gzip", "application/octet-stream"})
    if media_type not in allowed:
        raise PdfCanonicalizationError("retained raw result is not JSON")
    try:
        payload = json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise PdfCanonicalizationError("retained raw result JSON is malformed") from exc
    if not isinstance(payload, (dict, list)):
        raise PdfCanonicalizationError("retained raw result JSON root must be an object or document artifact list")
    return payload


def _matching_document(payload: Any, document_ref: str) -> dict[str, Any]:
    documents = payload if isinstance(payload, list) else payload.get("documents")
    if not isinstance(documents, list):
        raise PdfCanonicalizationError("retained raw result documents are missing or malformed")
    matches = [item for item in documents if isinstance(item, dict) and item.get("document_id") == document_ref]
    if len(matches) != 1:
        raise PdfCanonicalizationError("retained raw result must contain exactly one matching document")
    return matches[0]


def _canonical_spr_bytes(spr) -> bytes:
    return json.dumps(
        normalize_spr_v2(spr),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _deterministic_spr_reference(spr_bytes: bytes) -> StorageReference:
    digest = hashlib.sha256(b"atlas-spr-v2\0" + spr_bytes).hexdigest()[:32]
    return StorageReference.parse(f"src_{digest}")


def _candidate_identity(envelope: RawProcessingResultEnvelope, spr_sha256: str) -> tuple[str, str]:
    candidate_seed = "\x1f".join(
        (
            envelope.identity.document_id,
            envelope.identity.source_file_id,
            envelope.source.source_checksum_sha256,
            envelope.ingestion.payload_sha256,
            spr_sha256,
            envelope.identity.atlas_attempt_id,
        )
    )
    lineage_seed = "\x1f".join(
        (
            envelope.identity.document_id,
            envelope.identity.source_file_id,
            envelope.source.source_checksum_sha256,
        )
    )
    return (
        f"scv2_pdf_{hashlib.sha256(candidate_seed.encode()).hexdigest()[:24]}",
        f"scv2_pdf_lineage_{hashlib.sha256(lineage_seed.encode()).hexdigest()[:24]}",
    )


def _validate_document_and_source(session, envelope: RawProcessingResultEnvelope) -> SourceFile:
    document = session.get(Document, envelope.identity.document_id)
    if document is None:
        raise PdfCanonicalizationError("document for retained raw result does not exist")
    source = session.get(SourceFile, envelope.identity.source_file_id)
    if source is None or source.document_id != document.id:
        raise PdfCanonicalizationError("source file for retained raw result does not match document")
    if source.checksum_sha256 is not None and source.checksum_sha256.lower() != envelope.source.source_checksum_sha256.lower():
        raise PdfCanonicalizationError("source file checksum does not match retained raw-result provenance")
    if source.mime_type is not None and source.mime_type != "application/pdf":
        raise PdfCanonicalizationError("source file is not a PDF")
    return source


def _ensure_processing_run(session, envelope: RawProcessingResultEnvelope, raw_ref: str, now: datetime) -> ProcessingRun:
    run = session.execute(
        select(ProcessingRun).where(ProcessingRun.processing_run_id == envelope.identity.atlas_attempt_id)
    ).scalar_one_or_none()
    if run is None:
        run = ProcessingRun(
            processing_run_id=envelope.identity.atlas_attempt_id,
            document_id=envelope.identity.document_id,
            source_file_id=envelope.identity.source_file_id,
            status="running",
            provider_ref=envelope.identity.provider_name,
            raw_result_ref=raw_ref,
            started_at=envelope.ingestion.ingested_at.replace(tzinfo=None),
        )
        session.add(run)
        return run
    if run.document_id != envelope.identity.document_id or run.source_file_id != envelope.identity.source_file_id:
        raise PdfCanonicalizationError("processing run identity does not match retained raw-result provenance")
    return run


__all__ = [
    "PdfCanonicalizationError",
    "PdfCanonicalizationOutcome",
    "PdfCanonicalizationService",
    "PdfSelectionDisposition",
]
