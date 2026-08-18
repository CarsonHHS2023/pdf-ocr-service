"""Discrete 0/90/180/270 page orientation before OpenCV v4 deskew.

Native PDF text directions provide the authoritative signal when available. For
image-only pages a conservative OpenCV layout score is used; uncertain results
remain at 0 degrees so the pipeline fails safe instead of rotating content on a
weak guess.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

import cv2
import fitz  # type: ignore[import]
import numpy as np

from app.processing import pdf_page_presentation_bridge as bridge
from app.processing import pdf_page_presentation_preprocess_compat as preprocess

_INSTALLED = False


@dataclass(frozen=True, slots=True)
class DiscreteOrientation:
    correction_degrees: int
    confidence: float
    source: str
    native_text_chars: int
    image_score: float

    @property
    def applied(self) -> bool:
        return self.correction_degrees in {90, 180, 270}


def _rotate_clockwise(image: np.ndarray, degrees: int) -> np.ndarray:
    normalized = int(degrees) % 360
    if normalized == 0:
        return image
    if normalized == 90:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    if normalized == 180:
        return cv2.rotate(image, cv2.ROTATE_180)
    if normalized == 270:
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    raise ValueError("discrete orientation must be 0, 90, 180, or 270")


def _clockwise_vector(x: float, y: float, degrees: int) -> tuple[float, float]:
    normalized = int(degrees) % 360
    if normalized == 0:
        return x, y
    if normalized == 90:
        return -y, x
    if normalized == 180:
        return -x, -y
    if normalized == 270:
        return y, -x
    raise ValueError("rotation metadata must be discrete")


def _direction_correction(x: float, y: float) -> int:
    if abs(x) >= abs(y):
        return 0 if x >= 0 else 180
    return 90 if y < 0 else 270


def _native_text_orientation(page: fitz.Page) -> DiscreteOrientation | None:
    payload = page.get_text("dict") or {}
    blocks = payload.get("blocks") if isinstance(payload, Mapping) else None
    if not isinstance(blocks, list):
        return None
    weights = {0: 0, 90: 0, 180: 0, 270: 0}
    total = 0
    metadata_rotation = int(page.rotation or 0) % 360
    for block in blocks:
        if not isinstance(block, Mapping) or int(block.get("type", 0) or 0) != 0:
            continue
        lines = block.get("lines")
        if not isinstance(lines, list):
            continue
        for line in lines:
            if not isinstance(line, Mapping):
                continue
            direction = line.get("dir")
            spans = line.get("spans")
            if (
                not isinstance(direction, (list, tuple))
                or len(direction) != 2
                or not isinstance(spans, list)
            ):
                continue
            text = "".join(
                str(span.get("text") or "")
                for span in spans
                if isinstance(span, Mapping)
            ).strip()
            weight = len(text)
            if weight <= 0:
                continue
            try:
                x = float(direction[0])
                y = float(direction[1])
            except (TypeError, ValueError):
                continue
            # PyMuPDF text directions are expressed before page rotation, while
            # rendered classifier images include the page rotation metadata.
            x, y = _clockwise_vector(x, y, metadata_rotation)
            correction = _direction_correction(x, y)
            weights[correction] += weight
            total += weight
    if total < 8:
        return None
    correction, dominant = max(weights.items(), key=lambda item: item[1])
    confidence = dominant / total
    if confidence < 0.70:
        return None
    return DiscreteOrientation(
        correction_degrees=correction,
        confidence=round(confidence, 6),
        source="native_text_direction",
        native_text_chars=total,
        image_score=0.0,
    )


def _layout_metrics(image: np.ndarray) -> tuple[float, float]:
    if image.ndim != 3 or image.shape[2] != 3:
        return 0.0, 0.0
    height, width = image.shape[:2]
    scale = min(1.0, 1200.0 / max(height, width))
    if scale < 1:
        image = cv2.resize(
            image,
            (max(1, int(width * scale)), max(1, int(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, inverse = cv2.threshold(
        cv2.GaussianBlur(gray, (3, 3), 0),
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
    )
    page_area = float(inverse.size)
    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (max(10, image.shape[1] // 45), max(2, image.shape[0] // 500)),
    )
    connected = cv2.morphologyEx(inverse, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(
        connected,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    boxes = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w < image.shape[1] * 0.06:
            continue
        if h > image.shape[0] * 0.14:
            continue
        if w < h * 2.2:
            continue
        if w * h < page_area * 0.00008:
            continue
        boxes.append((x, y, w, h))
    if not boxes:
        return 0.0, 0.0
    horizontal = min(
        1.0,
        sum(w for _, _, w, _ in boxes)
        / max(1.0, image.shape[1] * max(4.0, len(boxes) * 0.7)),
    )
    left_margins = [x / image.shape[1] for x, _, _, _ in boxes]
    right_margins = [
        (image.shape[1] - (x + w)) / image.shape[1]
        for x, _, w, _ in boxes
    ]
    alignment = float(np.median(right_margins) - np.median(left_margins))
    alignment = max(-0.35, min(0.35, alignment))
    return horizontal, alignment


def _image_orientation(image: np.ndarray) -> DiscreteOrientation:
    scored: dict[int, tuple[float, float, float]] = {}
    for degrees in (0, 90, 180, 270):
        horizontal, alignment = _layout_metrics(
            _rotate_clockwise(image, degrees)
        )
        # Horizontal line evidence chooses the portrait axis. Margin asymmetry
        # resolves the 0/180 or 90/270 pair only when the signal is strong.
        score = horizontal + max(-0.08, min(0.08, alignment * 0.30))
        scored[degrees] = (score, horizontal, alignment)
    ordered = sorted(scored.items(), key=lambda item: item[1][0], reverse=True)
    best_degrees, (best_score, best_horizontal, best_alignment) = ordered[0]
    second_score = ordered[1][1][0]
    confidence = max(0.0, (best_score - second_score) / max(0.05, abs(best_score)))

    # A 90/270 decision needs stronger evidence because the two alternatives
    # have identical horizontal structure after a 180-degree flip.
    minimum_confidence = 0.14 if best_degrees in {90, 270} else 0.18
    if (
        best_degrees != 0
        and best_horizontal >= 0.12
        and abs(best_alignment) >= 0.035
        and confidence >= minimum_confidence
    ):
        return DiscreteOrientation(
            correction_degrees=best_degrees,
            confidence=round(min(1.0, confidence), 6),
            source="opencv_layout",
            native_text_chars=0,
            image_score=round(best_score, 6),
        )
    return DiscreteOrientation(
        correction_degrees=0,
        confidence=round(min(1.0, max(0.0, confidence)), 6),
        source="opencv_layout_uncertain",
        native_text_chars=0,
        image_score=round(best_score, 6),
    )


def detect_discrete_orientation(
    page: fitz.Page,
    analysis_image: np.ndarray,
) -> DiscreteOrientation:
    native = _native_text_orientation(page)
    if native is not None:
        return native
    return _image_orientation(analysis_image)


def _oriented_geometry(
    page: fitz.Page,
    orientation: DiscreteOrientation,
) -> tuple[np.ndarray | None, dict[str, object], np.ndarray | None]:
    from app.processing import pdf_opencv_quality_pipeline as v4

    source_bgr = v4._render_page_bgr(page, dpi=v4._RENDER_DPI)
    oriented_source = _rotate_clockwise(
        source_bgr,
        orientation.correction_degrees,
    )
    geometry_candidate, geometry_diag = v4._build_geometry_candidate(
        oriented_source
    )
    v4_accepted, reason, gate = v4._gate_geometry_candidate(
        oriented_source,
        geometry_candidate,
        geometry_diag,
    )
    overall_accepted = bool(v4_accepted or orientation.applied)
    selected = (
        geometry_candidate
        if v4_accepted
        else oriented_source
        if orientation.applied
        else None
    )
    applied_steps: list[str] = []
    if orientation.applied:
        applied_steps.append(
            f"discrete_orientation_{orientation.correction_degrees}"
        )
    if v4_accepted and geometry_diag.perspective_applied:
        applied_steps.append("opencv_perspective")
    if v4_accepted and geometry_diag.deskew_applied:
        applied_steps.append("opencv_deskew")
    geometry = {
        "accepted": overall_accepted,
        "v4_geometry_accepted": bool(v4_accepted),
        "reason": (
            "accepted"
            if v4_accepted
            else "discrete_orientation_corrected"
            if orientation.applied
            else reason
        ),
        "gate": {
            **gate,
            "orientation_confidence": orientation.confidence,
            "orientation_source": orientation.source,
        },
        "perspective_applied": geometry_diag.perspective_applied,
        "perspective_confidence": geometry_diag.perspective_confidence,
        "perspective_distortion": geometry_diag.perspective_distortion,
        "deskew_applied": geometry_diag.deskew_applied,
        "deskew_angle_degrees": geometry_diag.deskew_angle_degrees,
        "deskew_confidence": geometry_diag.deskew_confidence,
        "residual_angle_degrees": geometry_diag.residual_angle_degrees,
        "residual_confidence": geometry_diag.residual_confidence,
        "applied_steps": applied_steps,
        "orientation": {
            "detected_degrees": orientation.correction_degrees,
            "applied": orientation.applied,
            "confidence": orientation.confidence,
            "source": orientation.source,
            "native_text_chars": orientation.native_text_chars,
            "image_score": orientation.image_score,
            "pdf_rotation_metadata": int(page.rotation or 0) % 360,
        },
    }
    return selected, geometry, oriented_source if orientation.applied else None


def _classify_source_pages_oriented(
    source: fitz.Document,
) -> list[dict[str, object]]:
    from app.processing import pdf_opencv_quality_pipeline as v4

    decisions: list[dict[str, object]] = []
    page_count = source.page_count
    for page_index in range(page_count):
        page_number = page_index + 1
        source_unit_id = bridge._source_unit_id(page_number)
        page = source[page_index]
        raw_analysis = bridge._analysis_image(page)
        orientation = detect_discrete_orientation(page, raw_analysis)
        oriented_analysis = _rotate_clockwise(
            raw_analysis,
            orientation.correction_degrees,
        )
        features = {
            **bridge._native_page_features(page),
            **bridge._image_features(oriented_analysis),
        }
        features["likely_discrete_orientation"] = orientation.correction_degrees
        features["discrete_orientation_confidence"] = orientation.confidence
        features["discrete_orientation_source"] = orientation.source
        candidate, candidate_reasons = bridge._is_candidate(
            features,
            first_page=page_index == 0,
            last_page=page_index == page_count - 1,
        )
        bridge._diagnostic(
            "PDF_PAGE_CLASSIFICATION_CANDIDATE",
            source_unit_id=source_unit_id,
            candidate=candidate,
            reason_count=len(candidate_reasons),
            orientation=orientation.correction_degrees,
            orientation_confidence=orientation.confidence,
        )

        classification = bridge._fallback_classification(
            source_unit_id,
            "not_selected_for_multimodal_review",
        )
        geometry_image = None
        orientation_image = None
        geometry: dict[str, object] = {}
        if candidate:
            geometry_image, geometry, orientation_image = _oriented_geometry(
                page,
                orientation,
            )
            classification_image = (
                geometry_image
                if geometry_image is not None
                else oriented_analysis
            )
            try:
                classification = bridge._classify(
                    bridge._encode_png(classification_image),
                    features,
                    {
                        "source_unit_id": source_unit_id,
                        "page_number": page_number,
                        "page_index": page_index,
                        "page_count": page_count,
                        "is_first_physical_page": page_index == 0,
                        "is_last_physical_page": page_index == page_count - 1,
                        "page_width_points": float(page.rect.width),
                        "page_height_points": float(page.rect.height),
                        "candidate_reasons": list(candidate_reasons),
                        "discrete_orientation": orientation.correction_degrees,
                        "discrete_orientation_confidence": orientation.confidence,
                    },
                )
            except Exception as exc:
                classification = bridge._fallback_classification(
                    source_unit_id,
                    f"classification_failed:{type(exc).__name__}",
                )
                bridge._diagnostic(
                    "PDF_PAGE_CLASSIFICATION_FALLBACK_TO_OCR",
                    source_unit_id=source_unit_id,
                    reason=type(exc).__name__,
                )
            skip_ocr, decision_reason = bridge._skip_ocr_decision(
                classification,
                features,
            )
        else:
            skip_ocr = False
            decision_reason = "not_a_local_candidate"
            if orientation.applied:
                # Orientation itself makes the page a candidate, but retain this
                # defensive branch for custom test feature overrides.
                _, geometry, orientation_image = _oriented_geometry(
                    page,
                    orientation,
                )

        classification = {
            **classification,
            "candidate_features": bridge._json_clone(features),
            "candidate_reasons": list(candidate_reasons),
            "skip_ocr": skip_ocr,
            "decision_reason": decision_reason,
        }
        bridge._diagnostic(
            "PDF_PAGE_CLASSIFICATION_RESULT",
            source_unit_id=source_unit_id,
            page_role=classification["page_role"],
            confidence=classification["confidence"],
            skip_ocr=skip_ocr,
            image_detail=classification["image_detail"],
            cache_hit=classification["cache_hit"],
            input_tokens=classification["input_tokens"],
            output_tokens=classification["output_tokens"],
        )
        if candidate and not skip_ocr and classification["page_role"] in bridge.PRESENTATION_PAGE_ROLES:
            bridge._diagnostic(
                "PDF_PAGE_CLASSIFICATION_FALLBACK_TO_OCR",
                source_unit_id=source_unit_id,
                reason=decision_reason,
            )
        decisions.append(
            {
                "page_index": page_index,
                "page_number": page_number,
                "source_unit_id": source_unit_id,
                "features": features,
                "candidate": candidate,
                "candidate_reasons": candidate_reasons,
                "classification": classification,
                "skip_ocr": skip_ocr,
                "decision_reason": decision_reason,
                "geometry_image": geometry_image,
                "orientation_image": orientation_image,
                "geometry": geometry,
                "page_width_points": float(page.rect.width),
                "page_height_points": float(page.rect.height),
            }
        )
    return decisions


def _build_ordinary_source_oriented(
    source: fitz.Document,
    decisions: list[dict[str, object]],
) -> tuple[bytes | None, list[dict[str, object]]]:
    from app.processing import pdf_opencv_quality_pipeline as v4

    ordinary = fitz.open()
    provider_map: list[dict[str, object]] = []
    try:
        if source.metadata:
            ordinary.set_metadata(source.metadata)
        for decision in decisions:
            if decision["skip_ocr"]:
                continue
            page_index = int(decision["page_index"])
            provider_page_index = ordinary.page_count
            orientation_image = decision.get("orientation_image")
            if isinstance(orientation_image, np.ndarray):
                v4._insert_raster_page(
                    ordinary,
                    source[page_index].rect,
                    orientation_image,
                )
            else:
                ordinary.insert_pdf(
                    source,
                    from_page=page_index,
                    to_page=page_index,
                )
            provider_map.append(
                {
                    "provider_page_index": provider_page_index,
                    "original_page_index": page_index,
                    "original_page_number": int(decision["page_number"]),
                    "source_unit_id": str(decision["source_unit_id"]),
                }
            )
        if ordinary.page_count == 0:
            return None, provider_map
        return ordinary.tobytes(garbage=4, deflate=True), provider_map
    finally:
        ordinary.close()


def install_discrete_orientation_compat() -> None:
    """Install orientation correction before the classify-first V4 subset pass."""

    global _INSTALLED
    if _INSTALLED:
        return
    preprocess._classify_source_pages = _classify_source_pages_oriented
    preprocess._build_ordinary_source = _build_ordinary_source_oriented
    _INSTALLED = True


__all__ = [
    "DiscreteOrientation",
    "detect_discrete_orientation",
    "install_discrete_orientation_compat",
]
