from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.source_units import (
    DomAnchor,
    SourceUnit,
    SourceUnitDimensions,
    SourceUnitKind,
    SourceUnitRecoveryState,
    SpatialAnchor,
    TemporalAnchor,
    TextSpanAnchor,
    anchor_to_dict,
    source_unit_to_dict,
)


def test_pdf_physical_page_and_spatial_anchor_are_natural() -> None:
    page = SourceUnit(
        source_unit_id="page-0001",
        kind=SourceUnitKind.PHYSICAL_PAGE,
        source_order=0,
        source_ref="source-file-1",
        dimensions=SourceUnitDimensions(2480, 3508),
        rotation_degrees=0,
    )
    anchor = SpatialAnchor("page-0001", 0.1, 0.2, 0.8, 0.4)

    assert source_unit_to_dict(page)["kind"] == "physical_page"
    assert anchor_to_dict(anchor) == {
        "kind": "spatial",
        "source_unit_id": "page-0001",
        "normalized_bbox": [0.1, 0.2, 0.8, 0.4],
    }


def test_txt_text_flow_uses_text_span_without_fake_page_fields() -> None:
    span = TextSpanAnchor("text-flow-0001", 0, 50_000)
    unit = SourceUnit(
        source_unit_id="text-flow-0001",
        kind=SourceUnitKind.TEXT_FLOW,
        source_order=0,
        source_ref="source-file-txt",
        source_span=span,
    )

    payload = source_unit_to_dict(unit)
    assert payload == {
        "source_unit_id": "text-flow-0001",
        "kind": "text_flow",
        "source_order": 0,
        "source_ref": "source-file-txt",
        "recovery_state": "complete",
        "source_span": {
            "kind": "text_span",
            "source_unit_id": "text-flow-0001",
            "start": 0,
            "end": 50_000,
        },
    }
    assert "dimensions" not in payload
    assert "page_index" not in payload


def test_html_and_epub_dom_anchors_do_not_require_pages() -> None:
    html = SourceUnit(
        source_unit_id="html-section-main",
        kind=SourceUnitKind.HTML_SECTION,
        source_order=3,
        source_ref="web-source-1",
    )
    epub = SourceUnit(
        source_unit_id="epub-spine-7",
        kind=SourceUnitKind.EBOOK_SPINE_ITEM,
        source_order=7,
        source_ref="epub-source-1",
    )

    html_anchor = DomAnchor("html-section-main", "html/body/main/article[2]/p[3]", 4, 17)
    epub_anchor = DomAnchor("epub-spine-7", "body/section[1]/h2[1]")

    assert source_unit_to_dict(html)["source_order"] == 3
    assert source_unit_to_dict(epub)["source_order"] == 7
    assert anchor_to_dict(html_anchor)["text_start"] == 4
    assert "text_start" not in anchor_to_dict(epub_anchor)


def test_audio_and_video_use_temporal_source_identity() -> None:
    audio = SourceUnit(
        source_unit_id="audio-0042",
        kind=SourceUnitKind.AUDIO_SEGMENT,
        source_order=42,
        source_ref="audio-source-1",
        duration_ms=30_000,
    )
    video = SourceUnit(
        source_unit_id="video-0008",
        kind=SourceUnitKind.VIDEO_SEGMENT,
        source_order=8,
        source_ref="video-source-1",
        duration_ms=12_500,
        dimensions=SourceUnitDimensions(1920, 1080),
    )
    speech = TemporalAnchor("audio-0042", 1_000, 8_250)
    scene = TemporalAnchor("video-0008", 0, 12_500)
    frame_region = SpatialAnchor("video-0008", 0.05, 0.1, 0.95, 0.9)

    assert source_unit_to_dict(audio)["duration_ms"] == 30_000
    assert source_unit_to_dict(video)["dimensions"] == {"width": 1920, "height": 1080, "unit": "pixel"}
    assert anchor_to_dict(speech)["end_ms"] == 8_250
    assert anchor_to_dict(scene)["start_ms"] == 0
    assert anchor_to_dict(frame_region)["kind"] == "spatial"


def test_source_units_and_anchors_are_immutable() -> None:
    unit = SourceUnit(
        source_unit_id="page-1",
        kind=SourceUnitKind.PHYSICAL_PAGE,
        source_order=0,
        source_ref="source",
        dimensions=SourceUnitDimensions(100, 200),
    )
    anchor = SpatialAnchor("page-1", 0, 0, 1, 1)

    with pytest.raises(FrozenInstanceError):
        unit.source_order = 2  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        anchor.left = 0.5  # type: ignore[misc]


def test_serialization_is_stable_for_equal_values() -> None:
    first = SourceUnit(
        source_unit_id="text-1",
        kind=SourceUnitKind.TEXT_FLOW,
        source_order=1,
        source_ref="source",
        source_span=TextSpanAnchor("text-1", 100, 200),
        recovery_state=SourceUnitRecoveryState.DEGRADED,
    )
    second = SourceUnit(
        source_unit_id="text-1",
        kind=SourceUnitKind.TEXT_FLOW,
        source_order=1,
        source_ref="source",
        source_span=TextSpanAnchor("text-1", 100, 200),
        recovery_state=SourceUnitRecoveryState.DEGRADED,
    )

    assert source_unit_to_dict(first) == source_unit_to_dict(second)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: SpatialAnchor("p", -0.1, 0, 1, 1),
        lambda: SpatialAnchor("p", 0.5, 0, 0.5, 1),
        lambda: TextSpanAnchor("t", 10, 9),
        lambda: TemporalAnchor("a", 500, 499),
        lambda: DomAnchor("h", "", None, None),
        lambda: DomAnchor("h", "body/p", 1, None),
    ],
)
def test_invalid_anchor_ranges_are_rejected(factory) -> None:
    with pytest.raises(ValueError):
        factory()


def test_source_unit_kind_specific_invariants_are_enforced() -> None:
    with pytest.raises(ValueError, match="physical_page requires dimensions"):
        SourceUnit("p", SourceUnitKind.PHYSICAL_PAGE, 0, "source")

    with pytest.raises(ValueError, match="text_flow requires a source_span"):
        SourceUnit("t", SourceUnitKind.TEXT_FLOW, 0, "source")

    with pytest.raises(ValueError, match="audio_segment requires duration_ms"):
        SourceUnit("a", SourceUnitKind.AUDIO_SEGMENT, 0, "source")

    with pytest.raises(ValueError, match="source_span must reference"):
        SourceUnit(
            "t",
            SourceUnitKind.TEXT_FLOW,
            0,
            "source",
            source_span=TextSpanAnchor("different-unit", 0, 10),
        )

    with pytest.raises(ValueError, match="rotation_degrees is only valid"):
        SourceUnit(
            "t",
            SourceUnitKind.TEXT_FLOW,
            0,
            "source",
            source_span=TextSpanAnchor("t", 0, 10),
            rotation_degrees=90,
        )
