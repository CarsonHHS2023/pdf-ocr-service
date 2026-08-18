"""Run-local scratch and evidence cache for S0 v5 Phase 1."""
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
_GEOMETRY_CAPTURE_PAGE: ContextVar[int | None] = ContextVar(
    "atlas_s0_v5_phase1_geometry_capture_page", default=None
)

_GEOMETRY_DELEGATE: Callable[..., Any] | None = None
_RENDER_DELEGATE: Callable[..., np.ndarray] | None = None
_BUILD_ORDINARY_DELEGATE: Callable[..., Any] | None = None
_PAGE_OFFSET_DELEGATE: Callable[..., Any] | None = None


def configure(
    *,
    geometry_delegate: Callable[..., Any],
    render_delegate: Callable[..., np.ndarray],
    build_ordinary_delegate: Callable[..., Any],
    page_offset_delegate: Callable[..., Any],
) -> None:
    global _GEOMETRY_DELEGATE
    global _RENDER_DELEGATE
    global _BUILD_ORDINARY_DELEGATE
    global _PAGE_OFFSET_DELEGATE
    _GEOMETRY_DELEGATE = geometry_delegate
    _RENDER_DELEGATE = render_delegate
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


def store_analysis(page_number: int, *, structure: object, color: object) -> None:
    cached = page_cache(page_number, create=True)
    if cached is None:
        return
    cached["structure"] = structure
    cached["color"] = color
    metric("analysis_computed")


def _scratch_path(page_number: int) -> Path | None:
    state = active_state()
    if state is None:
        return None
    root = state.get("scratch_root")
    if not isinstance(root, Path):
        return None
    return root / f"page-{page_number:06d}-geometry-selected.npy"


def _save_geometry(page_number: int, image: np.ndarray) -> str | None:
    path = _scratch_path(page_number)
    if path is None:
        return None
    try:
        np.save(path, np.ascontiguousarray(image), allow_pickle=False)
        return str(path)
    except Exception as exc:
        diagnostic(
            "PDF_S0_V5_PHASE1_SCRATCH_WRITE_FAILED",
            page_number=page_number,
            error_type=type(exc).__name__,
        )
        return None


def _load_geometry(cached: Mapping[str, object]) -> np.ndarray | None:
    path = cached.get("geometry_path")
    if not isinstance(path, str) or not path:
        return None
    try:
        image = np.load(path, allow_pickle=False)
    except Exception as exc:
        diagnostic(
            "PDF_S0_V5_PHASE1_SCRATCH_READ_FAILED",
            error_type=type(exc).__name__,
        )
        return None
    if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] != 3:
        return None
    return np.ascontiguousarray(image)


def render_page_bgr(*args: object, **kwargs: object) -> np.ndarray:
    """Preserve the installed renderer and capture its first geometry 300-DPI raster."""
    delegate = _RENDER_DELEGATE
    if delegate is None:
        raise RuntimeError("Phase 1 render delegate is unavailable")
    image = delegate(*args, **kwargs)
    state = active_state()
    page_number = _GEOMETRY_CAPTURE_PAGE.get()
    if state is None or page_number is None:
        return image
    dpi = kwargs.get("dpi")
    if dpi is None and len(args) > 1:
        dpi = args[1]
    if dpi == 300 and "geometry_source_capture" not in state:
        state["geometry_source_capture"] = (int(page_number), image)
    return image


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


def geometry_only_page(page: fitz.Page) -> tuple[np.ndarray | None, dict[str, object]]:
    """Run the current presentation geometry delegate once and cache its selected raster."""
    delegate = _GEOMETRY_DELEGATE
    state = active_state()
    if state is None:
        if delegate is None:
            raise RuntimeError("Phase 1 geometry delegate is unavailable")
        return delegate(page)

    from app.processing import pdf_opencv_quality_pipeline as v4

    page_number = int(page.number) + 1
    cached = page_cache(page_number, create=True)
    assert cached is not None
    geometry = cached.get("geometry")
    if isinstance(geometry, dict) and cached.get("geometry_completed") is True:
        if not bool(geometry.get("accepted")):
            metric("presentation_geometry_cache_hits")
            return None, json.loads(json.dumps(geometry))
        image = _load_geometry(cached)
        if image is not None:
            metric("presentation_geometry_cache_hits")
            return image, json.loads(json.dumps(geometry))

    if delegate is None:
        raise RuntimeError("Phase 1 geometry delegate is unavailable")

    state.pop("geometry_source_capture", None)
    token = _GEOMETRY_CAPTURE_PAGE.set(page_number)
    try:
        geometry_image, raw_geometry = delegate(page)
    except BaseException:
        state.pop("geometry_source_capture", None)
        raise
    finally:
        _GEOMETRY_CAPTURE_PAGE.reset(token)

    geometry = (
        json.loads(json.dumps(raw_geometry))
        if isinstance(raw_geometry, Mapping)
        else {}
    )
    captured = state.pop("geometry_source_capture", None)
    source_image = (
        captured[1]
        if isinstance(captured, tuple)
        and len(captured) == 2
        and captured[0] == page_number
        and isinstance(captured[1], np.ndarray)
        else None
    )
    selected = geometry_image if isinstance(geometry_image, np.ndarray) else source_image
    path = _save_geometry(page_number, selected) if isinstance(selected, np.ndarray) else None
    try:
        diag = _geometry_diag(v4, geometry)
    except Exception as exc:
        diagnostic(
            "PDF_S0_V5_PHASE1_GEOMETRY_CACHE_METADATA_FAILED",
            page_number=page_number,
            error_type=type(exc).__name__,
        )
        diag = None
    gate = geometry.get("gate")
    gate = json.loads(json.dumps(gate)) if isinstance(gate, Mapping) else {}
    cached.update(
        {
            "geometry_completed": True,
            "geometry": geometry,
            "geometry_diag": diag,
            "geometry_accepted": bool(geometry.get("accepted")),
            "geometry_reason": str(geometry.get("reason") or ""),
            "geometry_gate": gate,
            "geometry_path": path,
        }
    )
    metric("geometry_computed")
    return geometry_image, geometry


def build_ordinary_source(
    source: fitz.Document,
    decisions: list[dict[str, object]],
) -> tuple[bytes | None, list[dict[str, object]]]:
    delegate = _BUILD_ORDINARY_DELEGATE
    if delegate is None:
        raise RuntimeError("Phase 1 ordinary-source delegate is unavailable")
    result = delegate(source, decisions)
    state = active_state()
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


def original_page_number(page: fitz.Page) -> int | None:
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
    if not isinstance(item, Mapping):
        return None
    value = item.get("original_page_number")
    return int(value) if isinstance(value, int) and value > 0 else None


def cached_geometry_for_ordinary(
    page_number: int | None,
) -> tuple[np.ndarray, object, bool, str, dict[str, object]] | None:
    if page_number is None:
        return None
    cached = page_cache(page_number)
    if cached is None or cached.get("geometry_completed") is not True:
        return None
    image = _load_geometry(cached)
    diag = cached.get("geometry_diag")
    gate = cached.get("geometry_gate")
    if image is None or diag is None or not isinstance(gate, dict):
        return None
    metric("ordinary_geometry_cache_hits")
    return (
        image,
        diag,
        bool(cached.get("geometry_accepted")),
        str(cached.get("geometry_reason") or ""),
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
                _ACTIVE.reset(token)

    setattr(wrapped, "__atlas_s0_v5_phase1_shared__", True)
    setattr(wrapped, "__atlas_s0_v5_phase1_delegate__", delegate)
    return wrapped
