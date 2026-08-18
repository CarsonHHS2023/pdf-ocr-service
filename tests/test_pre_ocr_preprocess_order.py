from __future__ import annotations

import hashlib

import fitz

from app.processing import pdf_page_presentation_bridge as bridge
from app.processing import pdf_page_presentation_preprocess_compat as compat
from app.processing.pdf_geometry_preprocessing import (
    GeometryPageResult,
    GeometryPreprocessedPdf,
)
from app.storage.models import PutResult


def _pdf(page_count: int = 2) -> bytes:
    document = fitz.open()
    try:
        for page_number in range(1, page_count + 1):
            page = document.new_page(width=300, height=400)
            page.insert_text((40, 80), f"Page {page_number}")
        return document.tobytes(garbage=4, deflate=True)
    finally:
        document.close()


def _classification(page_number: int, role: str, skip_ocr: bool):
    source_unit_id = bridge._source_unit_id(page_number)
    return {
        "page_index": page_number - 1,
        "page_number": page_number,
        "source_unit_id": source_unit_id,
        "features": {
            "native_text_chars": 12,
            "maximum_embedded_image_coverage": 0.0,
        },
        "candidate": True,
        "candidate_reasons": ("test",),
        "classification": {
            "source_unit_id": source_unit_id,
            "page_role": role,
            "confidence": 0.99,
            "reason_codes": ["test"],
            "provider": "test",
            "model_id": "test-model",
            "prompt_version": "test-prompt",
            "image_detail": "low",
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_hit": False,
            "candidate_features": {},
            "candidate_reasons": ["test"],
            "skip_ocr": skip_ocr,
            "decision_reason": (
                "presentation_page_confirmed"
                if skip_ocr
                else "role_not_presentation"
            ),
        },
        "skip_ocr": skip_ocr,
        "decision_reason": (
            "presentation_page_confirmed"
            if skip_ocr
            else "role_not_presentation"
        ),
        "geometry_image": None,
        "geometry": {
            "accepted": False,
            "reason": "no_geometry_change",
            "gate": {},
            "applied_steps": [],
        },
        "page_width_points": 300.0,
        "page_height_points": 400.0,
    }


class _Storage:
    def __init__(self):
        self.objects = {}

    def put(
        self,
        content,
        reference,
        *,
        expected_size=None,
        expected_sha256=None,
    ):
        checksum = hashlib.sha256(content).hexdigest()
        assert expected_size in {None, len(content)}
        assert expected_sha256 in {None, checksum}
        self.objects[str(reference)] = bytes(content)
        return PutResult(reference, len(content), checksum)


def _fake_v4_result(pdf_bytes: bytes) -> GeometryPreprocessedPdf:
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        page_count = document.page_count
    finally:
        document.close()
    checksum = hashlib.sha256(pdf_bytes).hexdigest()
    pages = tuple(
        GeometryPageResult(
            page_index=index,
            applied_steps=(),
            deskew_angle_degrees=0.0,
            deskew_confidence=0.0,
            perspective_confidence=0.0,
            perspective_distortion=0.0,
            input_size=(300, 400),
            output_size=(300, 400),
            route="born_digital_no_op",
            source_kind="pdf_page",
        )
        for index in range(page_count)
    )
    return GeometryPreprocessedPdf(
        pdf_bytes=pdf_bytes,
        checksum_sha256=checksum,
        byte_size=len(pdf_bytes),
        page_count=page_count,
        changed_page_count=0,
        pages=pages,
        version="opencv_unified_quality_gate_experiment_v4",
    )


def test_classification_happens_before_v4_and_v4_receives_only_ordinary_pages(
    monkeypatch,
):
    from app.processing import pdf_geometry_integration as integration
    from app.processing import pdf_opencv_quality_pipeline as v4

    events = []

    def classify(source):
        events.append(f"classify:{source.page_count}")
        return [
            _classification(1, "cover", True),
            _classification(2, "body", False),
        ]

    def preprocess(pdf_bytes, *, expected_page_count=None, **_kwargs):
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            actual = document.page_count
        finally:
            document.close()
        events.append(f"v4:{actual}")
        assert expected_page_count == 1
        assert actual == 1
        return _fake_v4_result(pdf_bytes)

    monkeypatch.setattr(compat, "_classify_source_pages", classify)
    monkeypatch.setattr(v4, "preprocess_pdf_geometry_opencv", preprocess)
    monkeypatch.setattr(integration, "retain_opencv_diagnostics", lambda **_: None)
    monkeypatch.setattr(
        bridge,
        "_v4_manifest",
        lambda _processed: {
            "version": "opencv_unified_quality_gate_experiment_v4",
            "pages": [
                {
                    "page_number": 1,
                    "route": "born_digital_no_op",
                    "selected": "original",
                    "background": {"attempted": False},
                }
            ],
        },
    )

    result = compat.prepare_presentation_provider_input_v2(
        storage=_Storage(),
        source_pdf_bytes=_pdf(2),
        original_filename="mixed.pdf",
        processing_attempt_id="attempt-mixed",
        expected_page_count=2,
    )

    assert events == ["classify:2", "v4:1"]
    assert result.provider_page_count == 1
    assert result.provider_page_map == (
        {
            "provider_page_index": 0,
            "original_page_index": 1,
            "original_page_number": 2,
            "source_unit_id": "pdf-page:000002",
        },
    )
    pages = result.presentation_manifest["pages"]
    assert pages[0]["ocr_route"] == "skipped_presentation_image"
    assert pages[0]["background"] == {
        "attempted": False,
        "accepted": False,
        "reason": "presentation_page_background_skipped",
        "gate": {},
    }
    assert pages[1]["ocr_route"] == "modal_paddle_ocr"


def test_all_presentation_pages_never_call_v4(monkeypatch):
    from app.processing import pdf_opencv_quality_pipeline as v4

    monkeypatch.setattr(
        compat,
        "_classify_source_pages",
        lambda _source: [
            _classification(1, "cover", True),
            _classification(2, "back_cover", True),
        ],
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("V4 must not run when every page is presentation-only")

    monkeypatch.setattr(v4, "preprocess_pdf_geometry_opencv", forbidden)

    result = compat.prepare_presentation_provider_input_v2(
        storage=_Storage(),
        source_pdf_bytes=_pdf(2),
        original_filename="presentation-only.pdf",
        processing_attempt_id="attempt-all-special",
        expected_page_count=2,
    )

    assert result.provider_page_count == 0
    assert result.presentation_manifest["presentation_page_count"] == 2
    assert all(
        page["background"]["attempted"] is False
        for page in result.presentation_manifest["pages"]
    )


def test_install_replaces_integration_entrypoint():
    from app.processing import pdf_geometry_integration as integration

    compat.install_preprocess_order_compat()

    assert (
        integration.prepare_geometry_provider_input
        is compat.prepare_presentation_provider_input_v2
    )
