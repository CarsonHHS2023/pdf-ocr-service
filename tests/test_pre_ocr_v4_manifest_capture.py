from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import fitz

from app.processing import pdf_geometry_integration as integration
from app.processing import pdf_opencv_quality_pipeline as v4
from app.processing import pdf_page_analysis_fail_open_compat as compat
from app.processing import pdf_page_presentation_bridge as bridge
from app.processing import pdf_page_presentation_preprocess_compat as preprocess
from app.processing.pdf_geometry_preprocessing import (
    GeometryPageResult,
    GeometryPreprocessedPdf,
)


def _single_page_pdf() -> bytes:
    document = fitz.open()
    try:
        page = document.new_page(width=300, height=400)
        page.insert_text((40, 80), "ordinary body page")
        return document.tobytes(garbage=4, deflate=True)
    finally:
        document.close()


class _Storage:
    def put(
        self,
        content: bytes,
        reference,
        *,
        expected_size: int,
        expected_sha256: str,
    ):
        assert len(content) == expected_size
        assert hashlib.sha256(content).hexdigest() == expected_sha256
        return SimpleNamespace(
            reference=reference,
            checksum_sha256=expected_sha256,
            byte_size=expected_size,
        )


def test_prepare_captures_v4_page_manifest_before_diagnostic_retention(
    monkeypatch,
):
    pdf_bytes = _single_page_pdf()
    checksum = hashlib.sha256(pdf_bytes).hexdigest()
    geometry_gate = {"edge_alignment_gain": 0.27}
    background_gate = {"content_loss_ratio": 0.04}
    full_manifest = {
        "version": v4.GEOMETRY_PREPROCESSING_VERSION,
        "output_sha256": checksum,
        "output_size_bytes": len(pdf_bytes),
        "changed_page_count": 0,
        "pages": [
            {
                "page_number": 1,
                "route": "quality_gate_original",
                "selected": "original",
                "structure": {"born_digital": False},
                "geometry": {
                    "accepted": False,
                    "reason": "deskew_not_improved",
                    "gate": geometry_gate,
                },
                "background": {
                    "attempted": True,
                    "accepted": False,
                    "reason": "content_guard_rejected",
                    "gate": background_gate,
                },
                "applied_steps": [],
            }
        ],
    }
    processed = GeometryPreprocessedPdf(
        pdf_bytes=pdf_bytes,
        checksum_sha256=checksum,
        byte_size=len(pdf_bytes),
        page_count=1,
        changed_page_count=0,
        pages=(
            GeometryPageResult(
                page_index=0,
                applied_steps=(),
                deskew_angle_degrees=0.0,
                deskew_confidence=0.0,
                perspective_confidence=0.0,
                perspective_distortion=0.0,
                input_size=(300, 400),
                output_size=(300, 400),
                fallback_used=False,
                safe_reason="geometry:deskew_not_improved",
                route="quality_gate_original",
                source_kind="pdf_page",
            ),
        ),
        version=v4.GEOMETRY_PREPROCESSING_VERSION,
    )

    decision = {
        "page_index": 0,
        "page_number": 1,
        "source_unit_id": "pdf-page:000001",
        "features": {},
        "candidate": False,
        "candidate_reasons": (),
        "classification": {
            "source_unit_id": "pdf-page:000001",
            "page_role": "unknown",
            "confidence": 0.0,
            "provider": "none",
            "skip_ocr": False,
            "decision_reason": "not_a_local_candidate",
        },
        "skip_ocr": False,
        "decision_reason": "not_a_local_candidate",
        "geometry_image": None,
        "geometry": {},
        "page_width_points": 300.0,
        "page_height_points": 400.0,
    }

    def fake_v4_preprocess(*_args, **_kwargs):
        with v4._DIAGNOSTIC_LOCK:
            v4._DIAGNOSTIC_MANIFESTS[checksum] = bridge._json_clone(full_manifest)
        return processed

    def consuming_retain(**_kwargs):
        with v4._DIAGNOSTIC_LOCK:
            retained = v4._DIAGNOSTIC_MANIFESTS.pop(checksum)
        assert retained["pages"][0]["geometry"]["gate"] == geometry_gate
        return Path("/tmp/opencv-diagnostics/test-attempt")

    monkeypatch.setattr(preprocess, "_classify_source_pages", lambda _source: [decision])
    monkeypatch.setattr(
        preprocess,
        "_build_ordinary_source",
        lambda _source, _decisions: (
            pdf_bytes,
            [
                {
                    "provider_page_index": 0,
                    "original_page_index": 0,
                    "original_page_number": 1,
                    "source_unit_id": "pdf-page:000001",
                }
            ],
        ),
    )
    monkeypatch.setattr(v4, "preprocess_pdf_geometry_opencv", fake_v4_preprocess)
    monkeypatch.setattr(compat, "_OriginalRetainDiagnostics", consuming_retain)
    monkeypatch.setattr(
        compat,
        "_OriginalV4Manifest",
        lambda _processed: {"version": "fallback", "pages": []},
    )
    monkeypatch.setattr(
        integration,
        "retain_opencv_diagnostics",
        compat._retain_diagnostics_with_manifest_capture,
    )
    monkeypatch.setattr(bridge, "_v4_manifest", compat._v4_manifest_after_retention)
    compat._CAPTURED_V4_MANIFEST.set(None)

    provider_input = preprocess.prepare_presentation_provider_input_v2(
        storage=_Storage(),
        source_pdf_bytes=pdf_bytes,
        original_filename="ordinary.pdf",
        processing_attempt_id="test-attempt",
        expected_page_count=1,
    )

    page_manifest = provider_input.presentation_manifest["pages"][0]
    assert page_manifest["route"] == "quality_gate_original"
    assert page_manifest["geometry"]["gate"] == geometry_gate
    assert page_manifest["background"]["gate"] == background_gate
    assert page_manifest["route"] != "v4_manifest_unavailable"
    ordinary_manifest = provider_input.presentation_manifest[
        "ordinary_v4_manifest"
    ]
    assert ordinary_manifest["pages"][0]["geometry"]["gate"] == geometry_gate
    assert ordinary_manifest["pages"][0]["background"]["gate"] == background_gate
    assert compat._CAPTURED_V4_MANIFEST.get() is None
