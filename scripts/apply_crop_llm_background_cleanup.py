"""Install the test-only OpenCV semantic crop quality gate.

This deployment patch deliberately does not install the former rejected-crop GPT
Image, Foreground Lock, Coherent Background, registration, affine, or Semantic V2
fallback chain. Those source files remain in the branch history, but the active
test runtime is OpenCV raw candidate -> retained raw diagnostic -> dark foreground
anchor restoration -> catastrophic precheck -> GPT-5.6 semantic quality gate with
bounded adverse-result consensus -> restored OpenCV or original, with a
conservative clean-white need-to-clean precheck before page/crop background
normalization and best-effort human-readable crop diagnostics.
"""
from __future__ import annotations

from pathlib import Path


_GATE_IMPORT = (
    "from app.processing.pdf_crop_opencv_semantic_gate_compat import "
    "install_pdf_crop_opencv_semantic_gate_compat\n"
)
_GATE_HARDENING_IMPORT = (
    "from app.processing.pdf_crop_opencv_semantic_gate_hardening_compat import "
    "install_pdf_crop_opencv_semantic_gate_hardening_compat\n"
)
_GATE_REQUEST_IMPORT = (
    "from app.processing.pdf_crop_opencv_semantic_gate_request_compat import "
    "install_pdf_crop_opencv_semantic_gate_request_compat\n"
)
_GATE_CONSENSUS_IMPORT = (
    "from app.processing.pdf_crop_opencv_semantic_consensus_compat import "
    "install_pdf_crop_opencv_semantic_consensus_compat\n"
)
_WHITE_SKIP_IMPORT = (
    "from app.processing.pdf_clean_white_background_skip_compat import "
    "install_pdf_clean_white_background_skip_compat\n"
)
_PERSISTENCE_IMPORT = (
    "from app.processing.pdf_crop_opencv_candidate_persistence_compat import "
    "install_pdf_crop_opencv_candidate_persistence_compat\n"
)
_PERSISTENCE_HARDENING_IMPORT = (
    "from app.processing.pdf_crop_opencv_candidate_persistence_hardening_compat import "
    "install_pdf_crop_opencv_candidate_persistence_hardening_compat\n"
)
_ANCHOR_IMPORT = (
    "from app.processing.pdf_crop_dark_foreground_anchor_compat import "
    "install_pdf_crop_dark_foreground_anchor_compat\n"
)
_PEAK_DIAGNOSTICS_IMPORT = (
    "from app.processing.pdf_crop_dark_foreground_anchor_peak_diagnostics_compat import "
    "install_pdf_crop_dark_foreground_anchor_peak_diagnostics_compat\n"
)
_READABLE_DIAGNOSTICS_IMPORT = (
    "from app.processing.pdf_crop_opencv_readable_diagnostics_compat import "
    "install_pdf_crop_opencv_readable_diagnostics_compat\n"
)
_LIFECYCLE_IMPORT = (
    "from app.processing.pdf_visual_crop_lifecycle_compat import "
    "install_pdf_visual_crop_lifecycle_compat\n"
)
_GATE_INSTALL = "install_pdf_crop_opencv_semantic_gate_compat()\n"
_GATE_HARDENING_INSTALL = "install_pdf_crop_opencv_semantic_gate_hardening_compat()\n"
_GATE_REQUEST_INSTALL = "install_pdf_crop_opencv_semantic_gate_request_compat()\n"
_GATE_CONSENSUS_INSTALL = "install_pdf_crop_opencv_semantic_consensus_compat()\n"
_WHITE_SKIP_INSTALL = "install_pdf_clean_white_background_skip_compat()\n"
_PERSISTENCE_INSTALL = "install_pdf_crop_opencv_candidate_persistence_compat()\n"
_PERSISTENCE_HARDENING_INSTALL = (
    "install_pdf_crop_opencv_candidate_persistence_hardening_compat()\n"
)
_ANCHOR_INSTALL = "install_pdf_crop_dark_foreground_anchor_compat()\n"
_PEAK_DIAGNOSTICS_INSTALL = (
    "install_pdf_crop_dark_foreground_anchor_peak_diagnostics_compat()\n"
)
_READABLE_DIAGNOSTICS_INSTALL = "install_pdf_crop_opencv_readable_diagnostics_compat()\n"
_LIFECYCLE_INSTALL = "install_pdf_visual_crop_lifecycle_compat()\n"

_LEGACY_INSTALL_TOKENS = (
    "install_pdf_crop_llm_background_cleanup_compat()",
    "install_pdf_crop_llm_background_cleanup_safety_compat()",
    "install_pdf_crop_llm_background_cleanup_final_safety_compat()",
    "install_pdf_crop_llm_background_cleanup_output_integrity_compat()",
    "install_pdf_crop_llm_semantic_v2_compat()",
    "install_pdf_crop_llm_semantic_v2_foreground_lock_compat()",
    "install_pdf_crop_llm_semantic_v2_coherent_background_compat()",
)

_TEST_ENV = {
    "PDF_CROP_LLM_BACKGROUND_CLEANUP_ENABLED": "0",
    "PDF_CROP_LLM_SEMANTIC_V2_ENABLED": "0",
    "PDF_CROP_LLM_SEMANTIC_V2_RETAIN_DIAGNOSTICS": "0",
    "PDF_CROP_OPENCV_SEMANTIC_GATE_ENABLED": "1",
    # Preserve the previous independent semantic Judge acceptance threshold.
    "PDF_CROP_OPENCV_SEMANTIC_GATE_MIN_CONFIDENCE": "0.90",
    # Preserve the previous per-document Judge-call ceiling. Consensus consumes
    # this same budget; it does not create an independent call allowance.
    "PDF_CROP_OPENCV_SEMANTIC_GATE_MAX_JUDGE_CALLS": "6",
}


def _patch_pdf_ingestion() -> None:
    path = Path("app/processing/pdf_ingestion.py")
    source = path.read_text(encoding="utf-8")

    opencv_import = (
        "from app.processing.pdf_opencv_modal_bridge import "
        "install_opencv_v4_modal_bridge\n"
    )
    if source.count(opencv_import) != 1:
        raise RuntimeError("Could not find the unique OpenCV bridge import")

    imports = (
        _GATE_IMPORT
        + _GATE_HARDENING_IMPORT
        + _GATE_REQUEST_IMPORT
        + _GATE_CONSENSUS_IMPORT
        + _WHITE_SKIP_IMPORT
        + _PERSISTENCE_IMPORT
        + _PERSISTENCE_HARDENING_IMPORT
        + _ANCHOR_IMPORT
        + _PEAK_DIAGNOSTICS_IMPORT
        + _READABLE_DIAGNOSTICS_IMPORT
        + _LIFECYCLE_IMPORT
    )
    if _GATE_IMPORT not in source:
        source = source.replace(opencv_import, opencv_import + imports, 1)
    else:
        if _GATE_HARDENING_IMPORT not in source:
            source = source.replace(
                _GATE_IMPORT,
                _GATE_IMPORT + _GATE_HARDENING_IMPORT,
                1,
            )
        if _GATE_REQUEST_IMPORT not in source:
            source = source.replace(
                _GATE_HARDENING_IMPORT,
                _GATE_HARDENING_IMPORT + _GATE_REQUEST_IMPORT,
                1,
            )
        if _GATE_CONSENSUS_IMPORT not in source:
            source = source.replace(
                _GATE_REQUEST_IMPORT,
                _GATE_REQUEST_IMPORT + _GATE_CONSENSUS_IMPORT,
                1,
            )
        if _WHITE_SKIP_IMPORT not in source:
            source = source.replace(
                _GATE_CONSENSUS_IMPORT,
                _GATE_CONSENSUS_IMPORT + _WHITE_SKIP_IMPORT,
                1,
            )
        if _PERSISTENCE_IMPORT not in source:
            source = source.replace(
                _WHITE_SKIP_IMPORT,
                _WHITE_SKIP_IMPORT + _PERSISTENCE_IMPORT,
                1,
            )
        if _PERSISTENCE_HARDENING_IMPORT not in source:
            source = source.replace(
                _PERSISTENCE_IMPORT,
                _PERSISTENCE_IMPORT + _PERSISTENCE_HARDENING_IMPORT,
                1,
            )
        if _ANCHOR_IMPORT not in source:
            source = source.replace(
                _PERSISTENCE_HARDENING_IMPORT,
                _PERSISTENCE_HARDENING_IMPORT + _ANCHOR_IMPORT,
                1,
            )
        if _PEAK_DIAGNOSTICS_IMPORT not in source:
            source = source.replace(
                _ANCHOR_IMPORT,
                _ANCHOR_IMPORT + _PEAK_DIAGNOSTICS_IMPORT,
                1,
            )
        if _READABLE_DIAGNOSTICS_IMPORT not in source:
            source = source.replace(
                _PEAK_DIAGNOSTICS_IMPORT,
                _PEAK_DIAGNOSTICS_IMPORT + _READABLE_DIAGNOSTICS_IMPORT,
                1,
            )
        if _LIFECYCLE_IMPORT not in source:
            source = source.replace(
                _READABLE_DIAGNOSTICS_IMPORT,
                _READABLE_DIAGNOSTICS_IMPORT + _LIFECYCLE_IMPORT,
                1,
            )

    opencv_install = "install_opencv_v4_modal_bridge()\n"
    if source.count(opencv_install) != 1:
        raise RuntimeError("Could not find the unique OpenCV bridge install call")

    installs = (
        _GATE_INSTALL
        + _GATE_HARDENING_INSTALL
        + _GATE_REQUEST_INSTALL
        + _GATE_CONSENSUS_INSTALL
        + _WHITE_SKIP_INSTALL
        + _PERSISTENCE_INSTALL
        + _PERSISTENCE_HARDENING_INSTALL
        + _ANCHOR_INSTALL
        + _PEAK_DIAGNOSTICS_INSTALL
        + _READABLE_DIAGNOSTICS_INSTALL
        + _LIFECYCLE_INSTALL
    )
    if _GATE_INSTALL not in source:
        source = source.replace(opencv_install, opencv_install + installs, 1)
    else:
        if _GATE_HARDENING_INSTALL not in source:
            source = source.replace(
                _GATE_INSTALL,
                _GATE_INSTALL + _GATE_HARDENING_INSTALL,
                1,
            )
        if _GATE_REQUEST_INSTALL not in source:
            source = source.replace(
                _GATE_HARDENING_INSTALL,
                _GATE_HARDENING_INSTALL + _GATE_REQUEST_INSTALL,
                1,
            )
        if _GATE_CONSENSUS_INSTALL not in source:
            source = source.replace(
                _GATE_REQUEST_INSTALL,
                _GATE_REQUEST_INSTALL + _GATE_CONSENSUS_INSTALL,
                1,
            )
        if _WHITE_SKIP_INSTALL not in source:
            source = source.replace(
                _GATE_CONSENSUS_INSTALL,
                _GATE_CONSENSUS_INSTALL + _WHITE_SKIP_INSTALL,
                1,
            )
        if _PERSISTENCE_INSTALL not in source:
            source = source.replace(
                _WHITE_SKIP_INSTALL,
                _WHITE_SKIP_INSTALL + _PERSISTENCE_INSTALL,
                1,
            )
        if _PERSISTENCE_HARDENING_INSTALL not in source:
            source = source.replace(
                _PERSISTENCE_INSTALL,
                _PERSISTENCE_INSTALL + _PERSISTENCE_HARDENING_INSTALL,
                1,
            )
        if _ANCHOR_INSTALL not in source:
            source = source.replace(
                _PERSISTENCE_HARDENING_INSTALL,
                _PERSISTENCE_HARDENING_INSTALL + _ANCHOR_INSTALL,
                1,
            )
        if _PEAK_DIAGNOSTICS_INSTALL not in source:
            source = source.replace(
                _ANCHOR_INSTALL,
                _ANCHOR_INSTALL + _PEAK_DIAGNOSTICS_INSTALL,
                1,
            )
        if _READABLE_DIAGNOSTICS_INSTALL not in source:
            source = source.replace(
                _PEAK_DIAGNOSTICS_INSTALL,
                _PEAK_DIAGNOSTICS_INSTALL + _READABLE_DIAGNOSTICS_INSTALL,
                1,
            )
        if _LIFECYCLE_INSTALL not in source:
            source = source.replace(
                _READABLE_DIAGNOSTICS_INSTALL,
                _READABLE_DIAGNOSTICS_INSTALL + _LIFECYCLE_INSTALL,
                1,
            )

    opencv_index = source.index(opencv_install)
    gate_index = source.index(_GATE_INSTALL)
    gate_hardening_index = source.index(_GATE_HARDENING_INSTALL)
    gate_request_index = source.index(_GATE_REQUEST_INSTALL)
    gate_consensus_index = source.index(_GATE_CONSENSUS_INSTALL)
    white_skip_index = source.index(_WHITE_SKIP_INSTALL)
    persistence_index = source.index(_PERSISTENCE_INSTALL)
    persistence_hardening_index = source.index(_PERSISTENCE_HARDENING_INSTALL)
    anchor_index = source.index(_ANCHOR_INSTALL)
    peak_diagnostics_index = source.index(_PEAK_DIAGNOSTICS_INSTALL)
    readable_diagnostics_index = source.index(_READABLE_DIAGNOSTICS_INSTALL)
    lifecycle_index = source.index(_LIFECYCLE_INSTALL)
    if not (
        opencv_index
        < gate_index
        < gate_hardening_index
        < gate_request_index
        < gate_consensus_index
        < white_skip_index
        < persistence_index
        < persistence_hardening_index
        < anchor_index
        < peak_diagnostics_index
        < readable_diagnostics_index
        < lifecycle_index
    ):
        raise RuntimeError(
            "Crop runtime must install OpenCV -> semantic gate -> semantic hardening -> "
            "request hardening -> bounded consensus -> clean-white skip -> raw candidate "
            "retention -> persistence hardening -> dark foreground anchor -> local-peak "
            "diagnostics -> readable crop diagnostics -> lifecycle diagnostics"
        )

    legacy_present = [token for token in _LEGACY_INSTALL_TOKENS if token in source]
    if legacy_present:
        raise RuntimeError(
            "Legacy GPT Image/Foreground Lock crop installers are still active: "
            + ", ".join(legacy_present)
        )

    path.write_text(source, encoding="utf-8")


def _set_env_assignment(source: str, key: str, value: str, *, anchor: str) -> str:
    desired = f'    os.environ["{key}"] = "{value}"\n'
    prefix = f'    os.environ["{key}"] = '
    lines = source.splitlines(keepends=True)
    matches = [index for index, line in enumerate(lines) if line.startswith(prefix)]
    if len(matches) > 1:
        raise RuntimeError(f"Multiple test Space assignments found for {key}")
    if matches:
        lines[matches[0]] = desired
        return "".join(lines)
    if source.count(anchor) != 1:
        raise RuntimeError(f"Could not find insertion anchor for {key}")
    return source.replace(anchor, anchor + desired, 1)


def _patch_test_space_entrypoint() -> None:
    path = Path("app.py")
    source = path.read_text(encoding="utf-8")
    anchor = '    os.environ["PDF_VISUAL_ASSET_ENHANCEMENT_ENABLED"] = "0"\n'
    if source.count(anchor) != 1:
        raise RuntimeError("Could not find the test Space visual-enhancement guard")

    insertion_anchor = anchor
    for key, value in _TEST_ENV.items():
        source = _set_env_assignment(source, key, value, anchor=insertion_anchor)
        insertion_anchor = f'    os.environ["{key}"] = "{value}"\n'

    path.write_text(source, encoding="utf-8")


def main() -> None:
    _patch_pdf_ingestion()
    _patch_test_space_entrypoint()


if __name__ == "__main__":
    main()
