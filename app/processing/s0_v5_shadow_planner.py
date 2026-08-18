"""Shadow-only S0 v5 inspection and treatment planning contracts.

The module is intentionally non-authoritative in Phase 0: it observes the same
120-DPI analysis image already produced by the current presentation path and
predicts which expensive treatment would be needed.  Current v4 remains the
only code that selects output pixels.  Shadow decisions are retained only for
profiling and false-negative analysis.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from statistics import median
from typing import Iterable, Mapping

import cv2
import fitz  # type: ignore[import]
import numpy as np


SHADOW_PLANNER_VERSION = "atlas_s0_v5_shadow_planner_v1"
PASSTHROUGH = "passthrough"
GEOMETRY_ONLY = "geometry_only"
BACKGROUND_ONLY = "background_only"
GEOMETRY_AND_BACKGROUND = "geometry_and_background"
HIGH_RES_CONFIRM = "high_res_confirm"

_NEAR_WHITE_THRESHOLD = 245
_BORDER_FRACTION = 0.05


@dataclass(frozen=True, slots=True)
class CheapPageObservation:
    page_number: int
    born_digital: bool
    embedded_image_count: int
    maximum_embedded_image_coverage: float
    single_full_page_raster: bool
    native_raster_width_pixels: int | None
    native_raster_height_pixels: int | None
    native_raster_xdpi: float | None
    native_raster_ydpi: float | None
    near_white_ratio: float
    border_near_white_ratio: float
    largest_border_connected_near_white_ratio: float
    background_std: float
    background_range: float
    dark_ratio: float
    high_saturation_ratio: float
    color_critical: bool
    estimated_skew_degrees: float
    estimated_skew_confidence: float
    perspective_coverage: float
    perspective_distortion: float
    clean_white: bool
    background_suspect: bool
    geometry_suspect: bool


@dataclass(frozen=True, slots=True)
class DocumentPreprocessProfile:
    version: str
    page_count: int
    profile_kind: str
    born_digital_ratio: float
    full_page_raster_ratio: float
    clean_white_ratio: float
    background_suspect_ratio: float
    geometry_suspect_ratio: float
    color_critical_ratio: float
    median_native_raster_xdpi: float | None
    median_native_raster_ydpi: float | None
    native_raster_dpi_consistent: bool


@dataclass(frozen=True, slots=True)
class ShadowTreatmentPlan:
    version: str
    page_number: int
    route: str
    requires_high_resolution: bool
    native_raster_candidate: bool
    reason_codes: tuple[str, ...]


def _round(value: float, digits: int = 6) -> float:
    return round(float(value), digits)


def _native_raster_observation(page: fitz.Page) -> dict[str, object]:
    try:
        images = page.get_images(full=True)
    except Exception:
        images = []
    embedded_image_count = len(images)
    maximum_coverage = 0.0
    best: tuple[int, int, float] | None = None
    page_area = max(1.0, float(page.rect.width * page.rect.height))
    for image in images:
        if not image:
            continue
        try:
            width = int(image[2])
            height = int(image[3])
        except Exception:
            width = 0
            height = 0
        try:
            rects = page.get_image_rects(int(image[0]))
        except Exception:
            rects = []
        local_coverage = 0.0
        for rect in rects:
            clipped = rect & page.rect
            if clipped.is_empty:
                continue
            coverage = max(0.0, float(clipped.width * clipped.height)) / page_area
            local_coverage = max(local_coverage, min(1.0, coverage))
            maximum_coverage = max(maximum_coverage, min(1.0, coverage))
        if best is None or local_coverage > best[2]:
            best = (width, height, local_coverage)

    full_page = bool(
        embedded_image_count == 1
        and best is not None
        and best[0] > 0
        and best[1] > 0
        and best[2] >= 0.98
    )
    width = best[0] if full_page and best is not None else None
    height = best[1] if full_page and best is not None else None
    xdpi = (
        float(width) / max(1e-9, float(page.rect.width) / 72.0)
        if width is not None
        else None
    )
    ydpi = (
        float(height) / max(1e-9, float(page.rect.height) / 72.0)
        if height is not None
        else None
    )
    return {
        "embedded_image_count": embedded_image_count,
        "maximum_embedded_image_coverage": _round(maximum_coverage),
        "single_full_page_raster": full_page,
        "native_raster_width_pixels": width,
        "native_raster_height_pixels": height,
        "native_raster_xdpi": _round(xdpi, 3) if xdpi is not None else None,
        "native_raster_ydpi": _round(ydpi, 3) if ydpi is not None else None,
    }


def _background_observation(image: np.ndarray) -> dict[str, float | bool]:
    if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("shadow planner requires a BGR analysis image")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    near_white = gray >= _NEAR_WHITE_THRESHOLD
    pixel_count = max(1, int(near_white.size))
    near_white_ratio = float(np.count_nonzero(near_white) / pixel_count)

    border_width = max(
        2,
        min(64, int(round(min(height, width) * _BORDER_FRACTION))),
    )
    border = np.zeros_like(near_white, dtype=bool)
    border[:border_width, :] = True
    border[-border_width:, :] = True
    border[:, :border_width] = True
    border[:, -border_width:] = True
    border_near_white_ratio = float(np.mean(near_white[border]))

    largest_border_component_ratio = 0.0
    near_white_count = int(np.count_nonzero(near_white))
    if near_white_count:
        component_count, labels, stats, _ = cv2.connectedComponentsWithStats(
            near_white.astype(np.uint8), connectivity=8
        )
        if component_count > 1:
            border_labels = {
                int(label)
                for label in np.unique(labels[border])
                if int(label) > 0
            }
            if border_labels:
                largest_border_component_ratio = float(
                    max(int(stats[label, cv2.CC_STAT_AREA]) for label in border_labels)
                    / pixel_count
                )

    scale = min(1.0, 480.0 / max(height, width))
    small = cv2.resize(
        gray,
        None,
        fx=scale,
        fy=scale,
        interpolation=cv2.INTER_AREA,
    )
    sigma = max(8.0, min(small.shape) / 16.0)
    low_frequency = cv2.GaussianBlur(
        small,
        (0, 0),
        sigmaX=sigma,
        sigmaY=sigma,
        borderType=cv2.BORDER_REPLICATE,
    )
    p05, p95 = np.percentile(low_frequency, (5, 95))
    background_std = float(np.std(low_frequency))
    background_range = float(p95 - p05)
    dark_ratio = float(np.mean(gray <= 48))

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    high_saturation = (saturation >= 70) & (value >= 35) & (value <= 250)
    high_saturation_ratio = float(np.mean(high_saturation))
    color_critical = bool(high_saturation_ratio >= 0.05)

    clean_white = bool(
        near_white_ratio >= 0.50
        and largest_border_component_ratio >= 0.45
        and border_near_white_ratio >= 0.80
    )
    background_suspect = bool(
        not clean_white
        and (
            near_white_ratio < 0.50
            or background_std >= 9.0
            or background_range >= 28.0
        )
    )
    return {
        "near_white_ratio": _round(near_white_ratio),
        "border_near_white_ratio": _round(border_near_white_ratio),
        "largest_border_connected_near_white_ratio": _round(
            largest_border_component_ratio
        ),
        "background_std": _round(background_std, 4),
        "background_range": _round(background_range, 4),
        "dark_ratio": _round(dark_ratio),
        "high_saturation_ratio": _round(high_saturation_ratio),
        "color_critical": color_critical,
        "clean_white": clean_white,
        "background_suspect": background_suspect,
    }


def _geometry_observation(image: np.ndarray) -> dict[str, float | bool]:
    # Phase 0 deliberately reuses the already-proven v4 detectors on the cheap
    # analysis raster.  A later S0 package can own these primitives directly.
    from app.processing import pdf_opencv_quality_pipeline as v4

    angle, confidence = v4._estimate_text_angle(image)
    quad, coverage = v4._detect_page_quad(image)
    height, width = image.shape[:2]
    distortion = 0.0
    if quad is not None:
        corners = np.array(
            [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
            dtype=np.float32,
        )
        diagonal = max(1.0, math.hypot(width, height))
        distortion = float(np.mean(np.linalg.norm(quad - corners, axis=1)) / diagonal)
    geometry_suspect = bool(
        (confidence >= 0.25 and abs(angle) >= 0.06)
        or (0.40 <= coverage <= 0.995 and distortion >= 0.005)
    )
    return {
        "estimated_skew_degrees": _round(angle, 4),
        "estimated_skew_confidence": _round(confidence, 4),
        "perspective_coverage": _round(coverage, 4),
        "perspective_distortion": _round(distortion, 6),
        "geometry_suspect": geometry_suspect,
    }


def observe_page(
    *,
    page: fitz.Page,
    analysis_image: np.ndarray,
    native_features: Mapping[str, object],
) -> CheapPageObservation:
    page_number = int(page.number) + 1
    raster = _native_raster_observation(page)
    background = _background_observation(analysis_image)
    geometry = _geometry_observation(analysis_image)
    native_text_chars = int(native_features.get("native_text_chars") or 0)
    maximum_coverage = float(
        native_features.get("maximum_embedded_image_coverage")
        or raster["maximum_embedded_image_coverage"]
        or 0.0
    )
    born_digital = bool(native_text_chars >= 80 and maximum_coverage < 0.55)
    if int(native_features.get("pdf_rotation_metadata") or 0) % 360:
        geometry["geometry_suspect"] = True
    return CheapPageObservation(
        page_number=page_number,
        born_digital=born_digital,
        embedded_image_count=int(raster["embedded_image_count"]),
        maximum_embedded_image_coverage=maximum_coverage,
        single_full_page_raster=bool(raster["single_full_page_raster"]),
        native_raster_width_pixels=raster["native_raster_width_pixels"],
        native_raster_height_pixels=raster["native_raster_height_pixels"],
        native_raster_xdpi=raster["native_raster_xdpi"],
        native_raster_ydpi=raster["native_raster_ydpi"],
        near_white_ratio=float(background["near_white_ratio"]),
        border_near_white_ratio=float(background["border_near_white_ratio"]),
        largest_border_connected_near_white_ratio=float(
            background["largest_border_connected_near_white_ratio"]
        ),
        background_std=float(background["background_std"]),
        background_range=float(background["background_range"]),
        dark_ratio=float(background["dark_ratio"]),
        high_saturation_ratio=float(background["high_saturation_ratio"]),
        color_critical=bool(background["color_critical"]),
        estimated_skew_degrees=float(geometry["estimated_skew_degrees"]),
        estimated_skew_confidence=float(geometry["estimated_skew_confidence"]),
        perspective_coverage=float(geometry["perspective_coverage"]),
        perspective_distortion=float(geometry["perspective_distortion"]),
        clean_white=bool(background["clean_white"]),
        background_suspect=bool(background["background_suspect"]),
        geometry_suspect=bool(geometry["geometry_suspect"]),
    )


def build_document_profile(
    observations: Iterable[CheapPageObservation],
) -> DocumentPreprocessProfile:
    items = tuple(observations)
    if not items:
        return DocumentPreprocessProfile(
            version=SHADOW_PLANNER_VERSION,
            page_count=0,
            profile_kind="empty",
            born_digital_ratio=0.0,
            full_page_raster_ratio=0.0,
            clean_white_ratio=0.0,
            background_suspect_ratio=0.0,
            geometry_suspect_ratio=0.0,
            color_critical_ratio=0.0,
            median_native_raster_xdpi=None,
            median_native_raster_ydpi=None,
            native_raster_dpi_consistent=False,
        )

    count = len(items)
    ratio = lambda predicate: sum(1 for item in items if predicate(item)) / count
    born_ratio = ratio(lambda item: item.born_digital)
    raster_ratio = ratio(lambda item: item.single_full_page_raster)
    clean_ratio = ratio(lambda item: item.clean_white)
    background_ratio = ratio(lambda item: item.background_suspect)
    geometry_ratio = ratio(lambda item: item.geometry_suspect)
    color_ratio = ratio(lambda item: item.color_critical)
    xdpis = [item.native_raster_xdpi for item in items if item.native_raster_xdpi]
    ydpis = [item.native_raster_ydpi for item in items if item.native_raster_ydpi]
    median_xdpi = float(median(xdpis)) if xdpis else None
    median_ydpi = float(median(ydpis)) if ydpis else None
    dpi_consistent = bool(
        raster_ratio >= 0.90
        and xdpis
        and ydpis
        and max(xdpis) - min(xdpis) <= 2.0
        and max(ydpis) - min(ydpis) <= 2.0
    )

    if born_ratio >= 0.90:
        kind = "born_digital"
    elif raster_ratio >= 0.90 and background_ratio >= 0.75:
        kind = "uniform_gray_scan"
    elif raster_ratio >= 0.90 and clean_ratio >= 0.75:
        kind = "uniform_clean_scan"
    elif color_ratio >= 0.25:
        kind = "photographic_or_color_mixed"
    else:
        kind = "mixed_document"

    return DocumentPreprocessProfile(
        version=SHADOW_PLANNER_VERSION,
        page_count=count,
        profile_kind=kind,
        born_digital_ratio=_round(born_ratio),
        full_page_raster_ratio=_round(raster_ratio),
        clean_white_ratio=_round(clean_ratio),
        background_suspect_ratio=_round(background_ratio),
        geometry_suspect_ratio=_round(geometry_ratio),
        color_critical_ratio=_round(color_ratio),
        median_native_raster_xdpi=_round(median_xdpi, 3) if median_xdpi else None,
        median_native_raster_ydpi=_round(median_ydpi, 3) if median_ydpi else None,
        native_raster_dpi_consistent=dpi_consistent,
    )


def plan_page(
    observation: CheapPageObservation,
    profile: DocumentPreprocessProfile,
) -> ShadowTreatmentPlan:
    reasons: list[str] = []
    if observation.born_digital:
        route = PASSTHROUGH
        reasons.append("born_digital")
    elif observation.clean_white and not observation.geometry_suspect and not observation.color_critical:
        route = PASSTHROUGH
        reasons.append("clean_white_no_geometry_signal")
    elif observation.color_critical:
        if observation.geometry_suspect:
            route = GEOMETRY_ONLY
            reasons.extend(("color_critical", "geometry_suspect"))
        else:
            route = HIGH_RES_CONFIRM
            reasons.extend(("color_critical", "confirm_before_passthrough"))
    elif observation.geometry_suspect and observation.background_suspect:
        route = GEOMETRY_AND_BACKGROUND
        reasons.extend(("geometry_suspect", "background_suspect"))
    elif observation.background_suspect:
        route = BACKGROUND_ONLY
        reasons.append("background_suspect")
    elif observation.geometry_suspect:
        route = GEOMETRY_ONLY
        reasons.append("geometry_suspect")
    else:
        route = HIGH_RES_CONFIRM
        reasons.append("uncertain_cheap_observation")

    native_raster_candidate = bool(
        observation.single_full_page_raster
        and observation.native_raster_xdpi is not None
        and observation.native_raster_ydpi is not None
        and profile.native_raster_dpi_consistent
    )
    if native_raster_candidate:
        reasons.append("native_full_page_raster_candidate")
    return ShadowTreatmentPlan(
        version=SHADOW_PLANNER_VERSION,
        page_number=observation.page_number,
        route=route,
        requires_high_resolution=route != PASSTHROUGH,
        native_raster_candidate=native_raster_candidate,
        reason_codes=tuple(reasons),
    )


def compare_plan_to_actual(
    plan: ShadowTreatmentPlan,
    page_manifest: Mapping[str, object] | None,
) -> dict[str, object]:
    if not isinstance(page_manifest, Mapping):
        return {
            "scope": "unavailable",
            "actual_requires_treatment": None,
            "route_miss": None,
            "false_negative_passthrough": None,
            "unnecessary_escalation": None,
        }
    route = str(page_manifest.get("route") or "")
    ocr_route = str(page_manifest.get("ocr_route") or "")
    if route.startswith("presentation_") or ocr_route == "skipped_presentation_image":
        return {
            "scope": "presentation_excluded",
            "actual_requires_treatment": None,
            "route_miss": None,
            "false_negative_passthrough": None,
            "unnecessary_escalation": None,
        }

    geometry = page_manifest.get("geometry")
    background = page_manifest.get("background")
    geometry_accepted = bool(
        isinstance(geometry, Mapping) and geometry.get("accepted") is True
    )
    background_accepted = bool(
        isinstance(background, Mapping) and background.get("accepted") is True
    )
    actual_requires = geometry_accepted or background_accepted

    capabilities = {
        PASSTHROUGH: frozenset(),
        GEOMETRY_ONLY: frozenset({"geometry"}),
        BACKGROUND_ONLY: frozenset({"background"}),
        GEOMETRY_AND_BACKGROUND: frozenset({"geometry", "background"}),
        HIGH_RES_CONFIRM: frozenset({"geometry", "background"}),
    }[plan.route]
    actual_components = set()
    if geometry_accepted:
        actual_components.add("geometry")
    if background_accepted:
        actual_components.add("background")
    route_miss = bool(actual_components - set(capabilities))
    return {
        "scope": "ordinary_v4",
        "actual_requires_treatment": actual_requires,
        "actual_geometry_accepted": geometry_accepted,
        "actual_background_accepted": background_accepted,
        "route_miss": route_miss,
        "false_negative_passthrough": bool(
            plan.route == PASSTHROUGH and actual_requires
        ),
        "unnecessary_escalation": bool(
            plan.route != PASSTHROUGH and not actual_requires
        ),
    }


def summarize_shadow_results(
    rows: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    items = tuple(rows)
    ordinary = [item for item in items if item.get("scope") == "ordinary_v4"]
    presentation = sum(
        1 for item in items if item.get("scope") == "presentation_excluded"
    )
    return {
        "page_count": len(items),
        "ordinary_compared_count": len(ordinary),
        "presentation_excluded_count": presentation,
        "false_negative_passthrough_count": sum(
            1 for item in ordinary if item.get("false_negative_passthrough") is True
        ),
        "route_miss_count": sum(
            1 for item in ordinary if item.get("route_miss") is True
        ),
        "unnecessary_escalation_count": sum(
            1 for item in ordinary if item.get("unnecessary_escalation") is True
        ),
    }


def observation_dict(value: CheapPageObservation) -> dict[str, object]:
    return asdict(value)


def profile_dict(value: DocumentPreprocessProfile) -> dict[str, object]:
    return asdict(value)


def plan_dict(value: ShadowTreatmentPlan) -> dict[str, object]:
    data = asdict(value)
    data["reason_codes"] = list(value.reason_codes)
    return data


__all__ = [
    "BACKGROUND_ONLY",
    "CheapPageObservation",
    "DocumentPreprocessProfile",
    "GEOMETRY_AND_BACKGROUND",
    "GEOMETRY_ONLY",
    "HIGH_RES_CONFIRM",
    "PASSTHROUGH",
    "SHADOW_PLANNER_VERSION",
    "ShadowTreatmentPlan",
    "build_document_profile",
    "compare_plan_to_actual",
    "observation_dict",
    "observe_page",
    "plan_dict",
    "plan_page",
    "profile_dict",
    "summarize_shadow_results",
]
