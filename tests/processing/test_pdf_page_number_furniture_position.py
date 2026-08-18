from __future__ import annotations

from app.processing.pdf_page_presentation_recovery import (
    _presentation_kind,
    _presentation_position_metadata,
)
from app.processing.structured_result_v2.model import ProcessingNodeKind
from app.source_units import SpatialAnchor


def _anchor(top: float, bottom: float) -> SpatialAnchor:
    return SpatialAnchor("pdf-page:000001", 0.12, top, 0.16, bottom)


def test_top_page_number_is_header_from_spatial_furniture_position() -> None:
    anchors = (_anchor(0.05875370919881306, 0.06943620178041543),)

    kind = _presentation_kind("number", anchors)

    assert kind is ProcessingNodeKind.HEADER
    metadata = _presentation_position_metadata("number", kind, anchors)
    assert metadata["presentation_position_role"] == "header"
    assert metadata["presentation_number_position_rule"] == "bounded_page_furniture_band_v1"
    assert 0.05 < metadata["presentation_number_vertical_center"] < 0.08


def test_bottom_page_number_is_footer_from_spatial_furniture_position() -> None:
    anchors = (_anchor(0.93, 0.95),)

    kind = _presentation_kind("page_number", anchors)

    assert kind is ProcessingNodeKind.FOOTER
    metadata = _presentation_position_metadata("page_number", kind, anchors)
    assert metadata["presentation_position_role"] == "footer"
    assert metadata["presentation_number_position_rule"] == "bounded_page_furniture_band_v1"


def test_middle_page_number_does_not_get_aggressively_promoted_to_header() -> None:
    anchors = (_anchor(0.44, 0.46),)

    kind = _presentation_kind("number", anchors)

    assert kind is ProcessingNodeKind.FOOTER
    metadata = _presentation_position_metadata("number", kind, anchors)
    assert metadata["presentation_position_role"] == "footer"
    assert metadata["presentation_number_position_rule"] == "ambiguous_middle_footer_fallback_v1"


def test_bounded_header_and_footer_thresholds_are_inclusive() -> None:
    assert _presentation_kind("number", (_anchor(0.19, 0.21),)) is ProcessingNodeKind.HEADER
    assert _presentation_kind("number", (_anchor(0.79, 0.81),)) is ProcessingNodeKind.FOOTER


def test_explicit_header_and_footer_roles_are_not_reclassified_by_position() -> None:
    assert _presentation_kind("header", (_anchor(0.92, 0.94),)) is ProcessingNodeKind.HEADER
    assert _presentation_kind("footer", (_anchor(0.05, 0.07),)) is ProcessingNodeKind.FOOTER


def test_page_number_without_spatial_geometry_preserves_legacy_footer_fallback() -> None:
    kind = _presentation_kind("number", ())

    assert kind is ProcessingNodeKind.FOOTER
    metadata = _presentation_position_metadata("number", kind, ())
    assert metadata["presentation_position_role"] == "footer"
    assert metadata["presentation_number_position_rule"] == "legacy_footer_fallback_no_spatial_anchor"
    assert metadata["presentation_number_vertical_center"] is None
