"""Retained TXT source -> analyzed SPR v2 -> Structured Content v2 runtime."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Any, Callable

from sqlalchemy import select

from app.models import Document, ProcessingRun, SourceFile
from app.processing.structured_result_v2.model import normalize_spr_v2
from app.processing.txt.normalization import normalize_txt_bytes
from app.processing.txt.structure_recovery import (
    DEFAULT_ANALYSIS_WINDOW_OVERLAP_LINES,
    DEFAULT_MAX_LINES_PER_ANALYSIS_WINDOW,
    DEFAULT_MAX_OUTLINE_CANDIDATES_PER_WINDOW,
    DEFAULT_OUTLINE_WINDOW_OVERLAP_CANDIDATES,
    TxtStructureAnalyzer,
    TxtStructureKind,
    build_txt_outline_windows,
    build_txt_structure_windows,
    reconcile_txt_window_assignments,
    recover_txt_structure_to_spr_v2,
)
from app.storage.base import StorageProvider
from app.storage.models import StorageReference
from app.structured_content_v2.repository import StructuredContentCandidateV2Repository
from app.structured_content_v2.selection import (
    StructuredContentV2SelectionNotFound,
    StructuredContentV2SelectionRepository,
)
from app.structured_content_v2.transformation import TransformationContextV2, transform_spr_v2_to_candidate


class TxtCanonicalizationError(RuntimeError):
    """Safe canonical TXT failure tagged with a bounded processing stage."""

    def __init__(self, message: str, *, stage: str = "canonicalization") -> None:
        super().__init__(message)
        self.stage = stage


@dataclass(frozen=True, slots=True)
class RetainedTxtCanonicalizationRequest:
    document_ref: str
    source_file_ref: str
    processing_run_ref: str


@dataclass(frozen=True, slots=True)
class TxtCanonicalizationOutcome:
    document_ref: str
    source_file_ref: str
    processing_run_ref: str
    structured_processing_result_ref: str
    candidate_id: str
    selected_candidate_id: str
    selection_version: int
    initial_selection_created: bool


@dataclass(frozen=True, slots=True)
class _RetainedTxtSourceSnapshot:
    document_ref: str
    source_file_ref: str
    file_type: str
    retained: bool
    storage_reference: str
    byte_size: int | None
    checksum_sha256: str | None


SessionFactory = Callable[[], Any]


def _enforce_document_title_level_one(outline_windows, outline_results) -> None:
    """Keep the title invariant provider-neutral at the production composition boundary."""
    kind_by_line = {
        candidate.line_id: candidate.kind
        for window in outline_windows
        for candidate in window.candidates
    }
    for result in outline_results:
        for assignment in result.assignments:
            if (
                kind_by_line.get(assignment.line_id) is TxtStructureKind.TITLE
                and assignment.heading_level != 1
            ):
                raise TxtCanonicalizationError(
                    "TXT outline reconciliation cannot demote the document title"
                )


def _snapshot_source(source: SourceFile, document_ref: str) -> _RetainedTxtSourceSnapshot:
    return _RetainedTxtSourceSnapshot(
        document_ref=document_ref,
        source_file_ref=source.id,
        file_type=source.file_type,
        retained=bool(source.retained),
        storage_reference=source.storage_reference,
        byte_size=source.byte_size,
        checksum_sha256=source.checksum_sha256,
    )


def _source_matches_snapshot(source: SourceFile, snapshot: _RetainedTxtSourceSnapshot) -> bool:
    return (
        source.id == snapshot.source_file_ref
        and source.document_id == snapshot.document_ref
        and source.file_type == snapshot.file_type
        and bool(source.retained) == snapshot.retained
        and source.storage_reference == snapshot.storage_reference
        and source.byte_size == snapshot.byte_size
        and (source.checksum_sha256 or "").lower() == (snapshot.checksum_sha256 or "").lower()
    )


class TxtCanonicalizationService:
    def __init__(
        self,
        *,
        storage: StorageProvider,
        session_factory: SessionFactory,
        analyzer: TxtStructureAnalyzer,
        candidates: StructuredContentCandidateV2Repository | None = None,
        selections: StructuredContentV2SelectionRepository | None = None,
        max_analysis_lines: int = DEFAULT_MAX_LINES_PER_ANALYSIS_WINDOW,
        analysis_overlap_lines: int = DEFAULT_ANALYSIS_WINDOW_OVERLAP_LINES,
        max_outline_candidates: int = DEFAULT_MAX_OUTLINE_CANDIDATES_PER_WINDOW,
        outline_overlap_candidates: int = DEFAULT_OUTLINE_WINDOW_OVERLAP_CANDIDATES,
    ) -> None:
        self.storage = storage
        self.session_factory = session_factory
        self.analyzer = analyzer
        self.candidates = candidates or StructuredContentCandidateV2Repository()
        self.selections = selections or StructuredContentV2SelectionRepository(self.candidates)
        self.max_analysis_lines = max_analysis_lines
        self.analysis_overlap_lines = analysis_overlap_lines
        self.max_outline_candidates = max_outline_candidates
        self.outline_overlap_candidates = outline_overlap_candidates

    def canonicalize(self, request: RetainedTxtCanonicalizationRequest) -> TxtCanonicalizationOutcome:
        for value, name in (
            (request.document_ref, "document_ref"),
            (request.source_file_ref, "source_file_ref"),
            (request.processing_run_ref, "processing_run_ref"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise TxtCanonicalizationError(
                    f"{name} is required",
                    stage="request_validation",
                )

        session = None
        stage = "session_open"
        try:
            # Keep the retained-source database read short. Large TXT analysis can
            # spend minutes in bounded network calls; no SQLAlchemy/SQLite session
            # should stay open across that provider work.
            try:
                session = self.session_factory()
                stage = "source_lookup"
                source = session.get(SourceFile, request.source_file_ref)
                document = session.get(Document, request.document_ref)

                stage = "source_validation"
                if document is None or source is None or source.document_id != request.document_ref:
                    raise TxtCanonicalizationError("retained TXT source does not match document")
                if source.file_type.lower() != "txt":
                    raise TxtCanonicalizationError("source file is not TXT")
                if not source.retained or not source.storage_reference:
                    raise TxtCanonicalizationError("TXT source is not durably retained")
                source_snapshot = _snapshot_source(source, request.document_ref)
            finally:
                if session is not None:
                    session.close()
                    session = None

            stage = "source_read"
            storage_ref = StorageReference.parse(source_snapshot.storage_reference)
            retained = self.storage.get(storage_ref)

            stage = "source_validation"
            _verify_source_bytes(source_snapshot, retained)

            stage = "normalization"
            normalized = normalize_txt_bytes(
                retained,
                document_ref=request.document_ref,
                source_ref=request.source_file_ref,
                processing_run_ref=request.processing_run_ref,
            )
            windows = build_txt_structure_windows(
                normalized,
                max_lines=self.max_analysis_lines,
                overlap_lines=self.analysis_overlap_lines,
            )

            stage = "local_analysis"
            window_results = tuple(self.analyzer.analyze(window) for window in windows)

            # Local windows classify source lines and paragraph continuation. A second,
            # much smaller pass sees only the title/heading outline and may reconcile
            # levels across window boundaries. It still cannot return text or parent IDs.
            outline_results = None
            reconcile_outline = getattr(self.analyzer, "reconcile_outline", None)
            if callable(reconcile_outline):
                stage = "local_reconciliation"
                consensus = reconcile_txt_window_assignments(
                    normalized,
                    window_results,
                    max_lines=self.max_analysis_lines,
                    overlap_lines=self.analysis_overlap_lines,
                )

                stage = "outline_planning"
                outline_windows = build_txt_outline_windows(
                    normalized,
                    consensus,
                    max_candidates=self.max_outline_candidates,
                    overlap_candidates=self.outline_overlap_candidates,
                )

                stage = "outline_analysis"
                outline_results = tuple(reconcile_outline(window) for window in outline_windows)

                stage = "outline_validation"
                _enforce_document_title_level_one(outline_windows, outline_results)

            stage = "spr_recovery"
            spr = recover_txt_structure_to_spr_v2(
                normalized,
                window_results,
                outline_results=outline_results,
                max_lines=self.max_analysis_lines,
                overlap_lines=self.analysis_overlap_lines,
                max_outline_candidates=self.max_outline_candidates,
                outline_overlap_candidates=self.outline_overlap_candidates,
            )

            stage = "spr_serialization"
            spr_bytes = _canonical_spr_bytes(spr)
            spr_reference = _deterministic_spr_reference(spr_bytes)

            stage = "spr_storage"
            spr_put = self.storage.put(
                spr_bytes,
                spr_reference,
                expected_size=len(spr_bytes),
                expected_sha256=hashlib.sha256(spr_bytes).hexdigest(),
            )
            spr_ref = str(spr_put.reference)
            candidate_id, lineage_key = _candidate_identity(
                request,
                source_snapshot.checksum_sha256 or "",
                spr_put.checksum_sha256,
            )

            stage = "candidate_transform"
            candidate = transform_spr_v2_to_candidate(
                spr,
                context=TransformationContextV2(
                    document_ref=request.document_ref,
                    candidate_id=candidate_id,
                    lineage_key=lineage_key,
                    structured_processing_result_ref=spr_ref,
                ),
            )

            # Open a fresh short-lived write session only after all provider work,
            # deterministic reconciliation, SPR storage, and candidate transformation
            # are complete. Revalidate the retained-source identity before writing.
            stage = "write_session_open"
            session = self.session_factory()

            stage = "write_identity_validation"
            write_document = session.get(Document, request.document_ref)
            write_source = session.get(SourceFile, request.source_file_ref)
            if (
                write_document is None
                or write_source is None
                or not _source_matches_snapshot(write_source, source_snapshot)
            ):
                raise TxtCanonicalizationError("TXT retained source changed during structure analysis")

            stage = "processing_run_persistence"
            now = datetime.utcnow()
            run = session.execute(
                select(ProcessingRun).where(ProcessingRun.processing_run_id == request.processing_run_ref)
            ).scalar_one_or_none()
            if run is None:
                run = ProcessingRun(
                    processing_run_id=request.processing_run_ref,
                    document_id=request.document_ref,
                    source_file_id=request.source_file_ref,
                    status="running",
                    provider_ref="txt-structure-analyzer",
                    structured_processing_result_ref=spr_ref,
                    started_at=now,
                )
                session.add(run)
                session.flush()
            elif run.document_id != request.document_ref or run.source_file_id != request.source_file_ref:
                raise TxtCanonicalizationError("processing run identity was reused for another source")
            else:
                run.status = "running"
                run.structured_processing_result_ref = spr_ref
                run.safe_error_code = None
                run.safe_error_summary = None
                run.failed_at = None

            stage = "candidate_persistence"
            persisted = self.candidates.create_candidate(session, candidate)

            stage = "selection"
            initial_created = False
            try:
                selection = self.selections.get_selection(session, request.document_ref)
            except StructuredContentV2SelectionNotFound:
                selection = self.selections.set_selection(
                    session,
                    document_ref=request.document_ref,
                    candidate_id=persisted.candidate_id,
                    expected_version=0,
                    selection_actor_ref="atlas.txt-ingestion-v2",
                    reason="initial canonical TXT ingestion",
                )
                initial_created = True

            stage = "commit"
            run.status = "succeeded"
            run.completed_at = now
            session.commit()

            return TxtCanonicalizationOutcome(
                document_ref=request.document_ref,
                source_file_ref=request.source_file_ref,
                processing_run_ref=request.processing_run_ref,
                structured_processing_result_ref=spr_ref,
                candidate_id=persisted.candidate_id,
                selected_candidate_id=selection.candidate_id,
                selection_version=selection.selection_version,
                initial_selection_created=initial_created,
            )
        except TxtCanonicalizationError as exc:
            if session is not None:
                session.rollback()
            if exc.stage == "canonicalization" and stage != "canonicalization":
                raise TxtCanonicalizationError(str(exc), stage=stage) from exc
            raise
        except Exception as exc:
            if session is not None:
                session.rollback()
            raise TxtCanonicalizationError(
                "retained TXT canonicalization failed",
                stage=stage,
            ) from exc
        finally:
            if session is not None:
                session.close()


def _verify_source_bytes(source: _RetainedTxtSourceSnapshot, retained: bytes) -> None:
    if not isinstance(retained, bytes):
        raise TxtCanonicalizationError("retained TXT source must be bytes")
    if source.byte_size is not None and len(retained) != source.byte_size:
        raise TxtCanonicalizationError("retained TXT byte size does not match source metadata")
    if source.checksum_sha256:
        actual = hashlib.sha256(retained).hexdigest()
        if actual.lower() != source.checksum_sha256.lower():
            raise TxtCanonicalizationError("retained TXT checksum does not match source metadata")


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


def _candidate_identity(
    request: RetainedTxtCanonicalizationRequest,
    source_sha256: str,
    spr_sha256: str,
) -> tuple[str, str]:
    candidate_seed = "\x1f".join(
        (
            request.document_ref,
            request.source_file_ref,
            source_sha256,
            spr_sha256,
            request.processing_run_ref,
        )
    )
    lineage_seed = "\x1f".join((request.document_ref, request.source_file_ref, source_sha256))
    candidate_digest = hashlib.sha256(candidate_seed.encode("utf-8")).hexdigest()[:24]
    lineage_digest = hashlib.sha256(lineage_seed.encode("utf-8")).hexdigest()[:24]
    return f"scv2_txt_{candidate_digest}", f"scv2_txt_lineage_{lineage_digest}"


__all__ = [
    "RetainedTxtCanonicalizationRequest",
    "TxtCanonicalizationError",
    "TxtCanonicalizationOutcome",
    "TxtCanonicalizationService",
]
