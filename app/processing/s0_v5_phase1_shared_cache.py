"""Run-local low-level evidence cache for S0 v5 Phase 1.

The cache deliberately sits below the already-composed presentation/native/
orientation/fail-open classifier pipeline.  It never replaces that pipeline.
Phase 0 wrappers are installed first and captured as delegates, so a cache hit
skips the Phase 0-timed expensive call while a miss is measured normally.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import json
import logging
from pathlib import Path
import tempfile
from typing import Any, Callable, Iterator, Mapping

import fitz  # type: ignore[import]
import numpy as np


_logger = logging.getLogger("uvicorn.error")
_ACTIVE: ContextVar[dict[str, object] | None] = ContextVar(
    "atlas_s0_v5_phase1_shared_analysis", default=None
)
_CHUNK_OFFSET: ContextVar[int] = ContextVar(
    "atlas_s0_v5_phase1_chunk_offset", default=0
)
_GEOMETRY_CAPTURE: ContextVar[tuple[int, tuple[int, int]] | None] = ContextVar(
    "atlas_s0_v5_phase1_geometry_capture", default=None
)

_ANALYSIS_DELEGATE: Callable[..., np.ndarray] | None = None
_GEOMETRY_DELEGATE: Callable[..., Any] | None = None
_ORIENTED_GEOMETRY_DELEGATE: Callable[..., Any] | None = None
_ORIENTATION_IMAGE_DELEGATE: Callable[..., Any] | None = None
_RENDER_DELEGATE: Callable[..., np.ndarray] | None = None
_GATE_DELEGATE: Callable[..., Any] | None = None
_BUILD_ORDINARY_DELEGATE: Callable[..., Any] | None = None
_PAGE_OFFSET_DELEGATE: Callable[..., Any] | None = None


def configure(
    *,
    analysis_delegate: Callable[..., np.ndarray],
    geometry_delegate: Callable[..., Any],
    oriented_geometry_delegate: Callable[..., Any],
    orientation_image_delegate: Callable[..., Any],
    render_delegate: Callable[..., np.ndarray],
    gate_delegate: Callable[..., Any],
    build_ordinary_delegate: Callable[..., Any],
    page_offset_delegate: Callable[..., Any],
) -> None:
    global _ANALYSIS_DELEGATE
    global _GEOMETRY_DELEGATE
    global _ORIENTED_GEOMETRY_DELEGATE
    global _ORIENTATION_IMAGE_DELEGATE
    global _RENDER_DELEGATE
    global _GATE_DELEGATE
    global _BUILD_ORDINARY_DELEGATE
    global _PAGE_OFFSET_DELEGATE
    _ANALYSIS_DELEGATE = analysis_delegate
    _GEOMETRY_DELEGATE = geometry_delegate
    _ORIENTED_GEOMETRY_DELEGATE = oriented_geometry_delegate
    _ORIENTATION_IMAGE_DELEGATE = orientation_image_delegate
    _RENDER_DELEGATE = render_delegate
    _GATE_DELEGATE = gate_delegate
    _BUILD_ORDINARY_DELEGATE = build_ordinary_delegate
    _PAGE_OFFSET_DELEGATE = page_offset_delegate


def active_state() -> dict[str, object] | None:
    value = _ACTIVE.get()
    return value if isinstance(value, dict) else None


def page_cache(page_number: int, *, create: bool = False) -> dict[str, object] | None:
    state = active_state()
    if state is None:
        return None
    pages = state.get("pages")
    if not isinstance(pages, dict):
        return None
    cached = pages.get(int(page_number))
    if isinstance(cached, dict):
        return cached
    if not create:
        return None
    cached = {}
    pages[int(page_number)] = cached
    return cached


def metric(name: str, increment: int = 1) -> None:
    state = active_state()
    if state is None:
        return
    metrics = state.get("metrics")
    if isinstance(metrics, dict):
        metrics[name] = int(metrics.get(name) or 0) + int(increment)


def diagnostic(event: str, **fields: object) -> None:
    payload = " ".join(f"{key}={value}" for key, value in sorted(fields.items()))
    _logger.info("%s %s", event, payload)


def _page_identity(page: object) -> tuple[int, int]:
    parent = getattr(page, "parent", None)
    number = int(getattr(page, "number", -1))
    return id(parent), number


def _page_number(page: object) -> int:
    return int(getattr(page, "number", -1)) + 1


def _scratch_path(page_number: int, suffix: str) -> Path | None:
    state = active_state()
    if state is None:
        return None
    root = state.get("scratch_root")
    if not isinstance(root, Path):
        return None
    return root / f"page-{page_number:06d}-{suffix}.npy"


def _save_image(page_number: int, suffix: str, image: np.ndarray) -> str | None:
    path = _scratch_path(page_number, suffix)
    if path is None:
        return None
    try:
        np.save(path, np.ascontiguousarray(image), allow_pickle=False)
        metric("scratch_write_files")
        metric("scratch_write_bytes", path.stat().st_size)
        return str(path)
    except Exception as exc:
        diagnostic(
            "PDF_S0_V5_PHASE1_SCRATCH_WRITE_FAILED",
            page_number=page_number,
            suffix=suffix,
            error_type=type(exc).__name__,
        )
        return None


def _load_path(path: object) -> np.ndarray | None:
    if not isinstance(path, str) or not path:
        return None
    try:
        scratch_path = Path(path)
        byte_size = scratch_path.stat().st_size
        image = np.load(scratch_path, allow_pickle=False)
        metric("scratch_read_files")
        metric("scratch_read_bytes", byte_size)
    except Exception as exc:
        diagnostic(
            "PDF_S0_V5_PHASE1_SCRATCH_READ_FAILED",
            error_type=type(exc).__name__,
        )
        return None
    if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] != 3:
        return None
    return np.ascontiguousarray(image)


def analysis_image(page: fitz.Page) -> np.ndarray:
    """Call the authoritative analysis delegate once and retain reusable evidence."""
    delegate = _ANALYSIS_DELEGATE
    if delegate is None:
        raise RuntimeError("Phase 1 analysis delegate is unavailable")
    image = delegate(page)
    state = active_state()
    if state is None:
        return image

    page_number = _page_number(page)
    identity = _page_identity(page)
    # These transient rasters are intentionally page-scoped.  Replacing them at
    # the next analysis page keeps RSS bounded while allowing same-page rerenders
    # (including high-resolution orientation confirmation) to hit the cache.
    state["current_analysis"] = (identity, page_number, image)
    state.pop("current_source_300", None)

    cached = page_cache(page_number, create=True)
    assert cached is not None
    from app.processing import pdf_opencv_quality_pipeline as v4

    try:
        cached["structure"] = v4._inspect_page_structure(page)
        metric("analysis_structure_computed")
    except Exception as exc:
        # Structure/color are optimization evidence only at this point.  They
        # must never make the authoritative presentation classifier fail.
        diagnostic(
            "PDF_S0_V5_PHASE1_STRUCTURE_EVIDENCE_FAILED",
            page_number=page_number,
            error_type=type(exc).__name__,
        )
    try:
        cached["color"] = v4._color_features(image)
        metric("analysis_color_computed")
    except Exception as exc:
        diagnostic(
            "PDF_S0_V5_PHASE1_COLOR_EVIDENCE_FAILED",
            page_number=page_number,
            error_type=type(exc).__name__,
        )
    metric("analysis_pages")
    return image


def _transient_match(
    value: object,
    *,
    identity: tuple[int, int],
) -> np.ndarray | None:
    if (
        isinstance(value, tuple)
        and len(value) == 3
        and value[0] == identity
        and isinstance(value[2], np.ndarray)
    ):
        return value[2]
    return None


def _capture_geometry_source(
    state: dict[str, object],
    *,
    page: object,
    image: np.ndarray,
) -> None:
    capture = _GEOMETRY_CAPTURE.get()
    if capture is None:
        return
    page_number, identity = capture
    if identity != _page_identity(page):
        return
    state["geometry_source_capture"] = (identity, page_number, image)


def render_page_bgr(*args: object, **kwargs: object) -> np.ndarray:
    """Return same-page 120/300 rasters from cache; delegate only on real work."""
    delegate = _RENDER_DELEGATE
    if delegate is None:
        raise RuntimeError("Phase 1 render delegate is unavailable")

    state = active_state()
    page = args[0] if args else kwargs.get("page")
    dpi = kwargs.get("dpi")
    if dpi is None and len(args) > 1:
        dpi = args[1]
    identity = _page_identity(page) if page is not None else None

    if state is not None and identity is not None and dpi == 120:
        image = _transient_match(state.get("current_analysis"), identity=identity)
        if image is not None:
            metric("analysis_render_cache_hits")
            return image

    if state is not None and identity is not None and dpi == 300:
        image = _transient_match(state.get("current_source_300"), identity=identity)
        if image is not None:
            metric("source_300_render_cache_hits")
            _capture_geometry_source(state, page=page, image=image)
            return image

    image = delegate(*args, **kwargs)
    if state is not None and identity is not None and dpi == 300:
        current_analysis = state.get("current_analysis")
        if (
            isinstance(current_analysis, tuple)
            and len(current_analysis) == 3
            and current_analysis[0] == identity
        ):
            state["current_source_300"] = (
                identity,
                int(current_analysis[1]),
                image,
            )
        _capture_geometry_source(state, page=page, image=image)
    return image


def gate_geometry_candidate(*args: object, **kwargs: object):
    """Capture the authoritative V4 gate tuple while preserving exact return value."""
    delegate = _GATE_DELEGATE
    if delegate is None:
        raise RuntimeError("Phase 1 geometry gate delegate is unavailable")
    result = delegate(*args, **kwargs)
    state = active_state()
    capture = _GEOMETRY_CAPTURE.get()
    if (
        state is not None
        and capture is not None
        and isinstance(result, tuple)
        and len(result) == 3
    ):
        accepted, reason, gate = result
        state["geometry_gate_capture"] = (
            bool(accepted),
            str(reason),
            json.loads(json.dumps(gate)) if isinstance(gate, Mapping) else {},
        )
    return result


def _geometry_diag(v4: object, geometry: Mapping[str, object]) -> object:
    return v4._GeometryDiagnostic(
        perspective_applied=bool(geometry.get("perspective_applied")),
        perspective_confidence=float(geometry.get("perspective_confidence") or 0.0),
        perspective_distortion=float(geometry.get("perspective_distortion") or 0.0),
        deskew_applied=bool(geometry.get("deskew_applied")),
        deskew_angle_degrees=float(geometry.get("deskew_angle_degrees") or 0.0),
        deskew_confidence=float(geometry.get("deskew_confidence") or 0.0),
        residual_angle_degrees=float(geometry.get("residual_angle_degrees") or 0.0),
        residual_confidence=float(geometry.get("residual_confidence") or 0.0),
    )


@contextmanager
def _geometry_capture(page: fitz.Page) -> Iterator[dict[str, object] | None]:
    state = active_state()
    if state is None:
        yield None
        return
    page_number = _page_number(page)
    identity = _page_identity(page)
    state.pop("geometry_source_capture", None)
    state.pop("geometry_gate_capture", None)
    token = _GEOMETRY_CAPTURE.set((page_number, identity))
    try:
        yield state
    finally:
        _GEOMETRY_CAPTURE.reset(token)


def _cache_geometry_result(
    *,
    page: fitz.Page,
    variant: str,
    selected: np.ndarray | None,
    geometry_raw: object,
    oriented_source: np.ndarray | None = None,
    orientation_degrees: int | None = None,
) -> dict[str, object]:
    state = active_state()
    geometry = (
        json.loads(json.dumps(geometry_raw))
        if isinstance(geometry_raw, Mapping)
        else {}
    )
    if state is None:
        return geometry

    page_number = _page_number(page)
    cached = page_cache(page_number, create=True)
    assert cached is not None
    captured = state.pop("geometry_source_capture", None)
    source_image = (
        captured[2]
        if isinstance(captured, tuple)
        and len(captured) == 3
        and captured[0] == _page_identity(page)
        and isinstance(captured[2], np.ndarray)
        else None
    )
    if source_image is None:
        source_image = _transient_match(
            state.get("current_source_300"),
            identity=_page_identity(page),
        )

    ordinary_image = (
        selected
        if isinstance(selected, np.ndarray)
        else oriented_source
        if isinstance(oriented_source, np.ndarray)
        else source_image
    )
    ordinary_path = (
        _save_image(page_number, "geometry-selected", ordinary_image)
        if isinstance(ordinary_image, np.ndarray)
        else None
    )
    presentation_path = None
    if isinstance(selected, np.ndarray):
        presentation_path = (
            ordinary_path
            if selected is ordinary_image
            else _save_image(page_number, "presentation-selected", selected)
        )

    orientation_path = None
    if isinstance(oriented_source, np.ndarray):
        orientation_path = (
            ordinary_path
            if oriented_source is ordinary_image
            else _save_image(page_number, "orientation-source", oriented_source)
        )

    gate_capture = state.pop("geometry_gate_capture", None)
    if isinstance(gate_capture, tuple) and len(gate_capture) == 3:
        ordinary_accepted = bool(gate_capture[0])
        ordinary_reason = str(gate_capture[1])
        ordinary_gate = gate_capture[2]
    else:
        ordinary_accepted = bool(
            geometry.get("v4_geometry_accepted", geometry.get("accepted"))
        )
        ordinary_reason = str(geometry.get("reason") or "")
        gate = geometry.get("gate")
        ordinary_gate = (
            json.loads(json.dumps(gate)) if isinstance(gate, Mapping) else {}
        )

    from app.processing import pdf_opencv_quality_pipeline as v4

    try:
        diag = _geometry_diag(v4, geometry)
    except Exception as exc:
        diagnostic(
            "PDF_S0_V5_PHASE1_GEOMETRY_CACHE_METADATA_FAILED",
            page_number=page_number,
            error_type=type(exc).__name__,
        )
        diag = None

    cached.update(
        {
            "geometry_completed": True,
            "geometry_variant": variant,
            "geometry": geometry,
            "geometry_diag": diag,
            "ordinary_geometry_accepted": ordinary_accepted,
            "ordinary_geometry_reason": ordinary_reason,
            "ordinary_geometry_gate": ordinary_gate,
            "ordinary_geometry_path": ordinary_path,
            "presentation_geometry_path": presentation_path,
            "orientation_source_path": orientation_path,
            "orientation_degrees": orientation_degrees,
        }
    )
    metric("geometry_computed")
    return geometry


def geometry_only_page(page: fitz.Page) -> tuple[np.ndarray | None, dict[str, object]]:
    """Cache the authoritative non-oriented presentation geometry result."""
    delegate = _GEOMETRY_DELEGATE
    if delegate is None:
        raise RuntimeError("Phase 1 geometry delegate is unavailable")
    state = active_state()
    if state is None:
        return delegate(page)

    cached = page_cache(_page_number(page), create=True)
    assert cached is not None
    geometry = cached.get("geometry")
    if (
        cached.get("geometry_completed") is True
        and cached.get("geometry_variant") == "base"
        and isinstance(geometry, dict)
    ):
        if not bool(geometry.get("accepted")):
            metric("presentation_geometry_cache_hits")
            return None, json.loads(json.dumps(geometry))
        image = _load_path(cached.get("presentation_geometry_path"))
        if image is not None:
            metric("presentation_geometry_cache_hits")
            return image, json.loads(json.dumps(geometry))

    with _geometry_capture(page):
        selected, raw_geometry = delegate(page)
    geometry = _cache_geometry_result(
        page=page,
        variant="base",
        selected=selected if isinstance(selected, np.ndarray) else None,
        geometry_raw=raw_geometry,
    )
    return selected, geometry


def oriented_geometry(page: fitz.Page, orientation: object):
    """Cache the already-composed orientation + V4 geometry delegate."""
    delegate = _ORIENTED_GEOMETRY_DELEGATE
    if delegate is None:
        raise RuntimeError("Phase 1 oriented geometry delegate is unavailable")
    state = active_state()
    if state is None:
        return delegate(page, orientation)

    degrees = int(getattr(orientation, "correction_degrees", 0) or 0) % 360
    cached = page_cache(_page_number(page), create=True)
    assert cached is not None
    geometry = cached.get("geometry")
    if (
        cached.get("geometry_completed") is True
        and cached.get("geometry_variant") == "oriented"
        and int(cached.get("orientation_degrees") or 0) % 360 == degrees
        and isinstance(geometry, dict)
    ):
        if bool(geometry.get("accepted")):
            selected = _load_path(cached.get("presentation_geometry_path"))
            if selected is None:
                # Missing scratch is an optimization miss: recompute below.
                pass
            else:
                oriented_source = _load_path(cached.get("orientation_source_path"))
                metric("presentation_geometry_cache_hits")
                return selected, json.loads(json.dumps(geometry)), oriented_source
        else:
            metric("presentation_geometry_cache_hits")
            return None, json.loads(json.dumps(geometry)), None

    with _geometry_capture(page):
        selected, raw_geometry, oriented_source = delegate(page, orientation)
    geometry = _cache_geometry_result(
        page=page,
        variant="oriented",
        selected=selected if isinstance(selected, np.ndarray) else None,
        geometry_raw=raw_geometry,
        oriented_source=(
            oriented_source if isinstance(oriented_source, np.ndarray) else None
        ),
        orientation_degrees=degrees,
    )
    return selected, geometry, oriented_source


def orientation_image_from_decision(
    page: fitz.Page,
    decision: Mapping[str, object],
) -> np.ndarray | None:
    """Reuse the oriented provider raster created by authoritative classification."""
    delegate = _ORIENTATION_IMAGE_DELEGATE
    if delegate is None:
        raise RuntimeError("Phase 1 orientation image delegate is unavailable")
    state = active_state()
    if state is None:
        return delegate(page, decision)
    if decision.get("decision_reason") in {
        "pre_ocr_geometry_failed",
        "pre_ocr_analysis_failed",
    }:
        return delegate(page, decision)

    cached = page_cache(_page_number(page))
    if isinstance(cached, dict) and cached.get("geometry_variant") == "oriented":
        image = _load_path(cached.get("orientation_source_path"))
        if image is not None:
            metric("orientation_source_cache_hits")
            return image
    return delegate(page, decision)


def _clear_transient_rasters(state: dict[str, object]) -> None:
    state.pop("current_analysis", None)
    state.pop("current_source_300", None)
    state.pop("geometry_source_capture", None)
    state.pop("geometry_gate_capture", None)


def build_ordinary_source(
    source: fitz.Document,
    decisions: list[dict[str, object]],
) -> tuple[bytes | None, list[dict[str, object]]]:
    delegate = _BUILD_ORDINARY_DELEGATE
    if delegate is None:
        raise RuntimeError("Phase 1 ordinary-source delegate is unavailable")
    state = active_state()
    if state is not None:
        _clear_transient_rasters(state)
    result = delegate(source, decisions)
    if state is not None:
        state["provider_map"] = [
            dict(item) for item in result[1] if isinstance(item, Mapping)
        ]
    return result


@contextmanager
def page_offset(offset: int) -> Iterator[None]:
    delegate = _PAGE_OFFSET_DELEGATE
    token = _CHUNK_OFFSET.set(max(0, int(offset)))
    try:
        if delegate is None:
            yield
        else:
            with delegate(offset):
                yield
    finally:
        _CHUNK_OFFSET.reset(token)


def provider_item(page: fitz.Page) -> dict[str, object] | None:
    state = active_state()
    if state is None:
        return None
    provider_map = state.get("provider_map")
    if not isinstance(provider_map, list):
        return None
    index = _CHUNK_OFFSET.get() + int(page.number)
    if index < 0 or index >= len(provider_map):
        return None
    item = provider_map[index]
    return dict(item) if isinstance(item, Mapping) else None


def original_page_number(page: fitz.Page) -> int | None:
    item = provider_item(page)
    if item is None:
        return None
    value = item.get("original_page_number")
    return int(value) if isinstance(value, int) and value > 0 else None


def cached_geometry_for_ordinary(
    page_number: int | None,
    *,
    provider_input_mode: str,
) -> tuple[np.ndarray, object, bool, str, dict[str, object]] | None:
    if page_number is None:
        return None
    # Native-text fallback rasterization changes the provider page contract in a
    # way that should be re-evaluated by authoritative V4 rather than assumed.
    if provider_input_mode not in {"pdf_page", "orientation_corrected_raster"}:
        return None
    cached = page_cache(page_number)
    if cached is None or cached.get("geometry_completed") is not True:
        return None
    image = _load_path(cached.get("ordinary_geometry_path"))
    diag = cached.get("geometry_diag")
    gate = cached.get("ordinary_geometry_gate")
    if image is None or diag is None or not isinstance(gate, dict):
        return None
    metric("ordinary_geometry_cache_hits")
    return (
        image,
        diag,
        bool(cached.get("ordinary_geometry_accepted")),
        str(cached.get("ordinary_geometry_reason") or ""),
        json.loads(json.dumps(gate)),
    )


def wrap_top_level(delegate: Callable[..., Any]) -> Callable[..., Any]:
    if getattr(delegate, "__atlas_s0_v5_phase1_shared__", False):
        return delegate

    def wrapped(*args: object, **kwargs: object):
        if active_state() is not None:
            return delegate(*args, **kwargs)
        from app.processing import pdf_s0_bounded_v4_output_compat as bounded

        with tempfile.TemporaryDirectory(
            prefix="atlas-s0-v5-phase1-",
            dir=bounded._temporary_root(),
        ) as temp_dir:
            state: dict[str, object] = {
                "scratch_root": Path(temp_dir),
                "pages": {},
                "provider_map": [],
                "metrics": {},
            }
            token = _ACTIVE.set(state)
            diagnostic("PDF_S0_V5_PHASE1_SHARED_ANALYSIS_STARTED")
            try:
                result = delegate(*args, **kwargs)
                diagnostic(
                    "PDF_S0_V5_PHASE1_SHARED_ANALYSIS_COMPLETE",
                    cached_page_count=len(state["pages"]),
                    metrics=json.dumps(
                        state["metrics"], sort_keys=True, separators=(",", ":")
                    ),
                )
                return result
            finally:
                _clear_transient_rasters(state)
                _ACTIVE.reset(token)

    setattr(wrapped, "__atlas_s0_v5_phase1_shared__", True)
    setattr(wrapped, "__atlas_s0_v5_phase1_delegate__", delegate)
    return wrapped
