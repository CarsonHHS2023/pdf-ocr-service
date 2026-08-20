"""Install the stable-v4 Modal and pre-OCR presentation bridges."""
from __future__ import annotations

from pathlib import Path


_OLD_RETRY_POLICY = """def _whole_page_rejected(page_manifest: Mapping[str, object] | None) -> bool:
    \"\"\"Use both v4 gate decisions, not route alone, to authorize a crop retry.\"\"\"
    if not isinstance(page_manifest, Mapping):
        return False
    if page_manifest.get("route") != "quality_gate_original":
        return False
    if page_manifest.get("selected") != "original":
        return False
    geometry = page_manifest.get("geometry")
    background = page_manifest.get("background")
    if not isinstance(geometry, Mapping) or not isinstance(background, Mapping):
        return False
    return bool(
        geometry.get("accepted") is False
        and background.get("attempted") is True
        and background.get("accepted") is False
        and isinstance(geometry.get("gate"), Mapping)
        and isinstance(background.get("gate"), Mapping)
    )
"""

_NEW_RETRY_POLICY = """def _whole_page_rejected(page_manifest: Mapping[str, object] | None) -> bool:
    \"\"\"Authorize a crop retry whenever attempted page background cleanup was rejected.\"\"\"
    if not isinstance(page_manifest, Mapping):
        return False
    geometry = page_manifest.get("geometry")
    background = page_manifest.get("background")
    if not isinstance(geometry, Mapping) or not isinstance(background, Mapping):
        return False

    geometry_accepted = geometry.get("accepted")
    if geometry_accepted is True:
        page_state_is_consistent = (
            page_manifest.get("route") == "geometry_only"
            and page_manifest.get("selected") == "geometry"
        )
    elif geometry_accepted is False:
        page_state_is_consistent = (
            page_manifest.get("route") == "quality_gate_original"
            and page_manifest.get("selected") == "original"
        )
    else:
        return False

    return bool(
        page_state_is_consistent
        and background.get("attempted") is True
        and background.get("accepted") is False
        and isinstance(geometry.get("gate"), Mapping)
        and isinstance(background.get("gate"), Mapping)
    )
"""


def _patch_visual_retry_policy() -> None:
    path = Path("app/processing/pdf_opencv_modal_bridge.py")
    source = path.read_text(encoding="utf-8")
    if _NEW_RETRY_POLICY in source:
        return
    if source.count(_OLD_RETRY_POLICY) != 1:
        raise RuntimeError("Could not find the unique visual crop retry policy")
    path.write_text(
        source.replace(_OLD_RETRY_POLICY, _NEW_RETRY_POLICY, 1),
        encoding="utf-8",
    )


def _install_bridge_import() -> None:
    path = Path("app/processing/pdf_ingestion.py")
    source = path.read_text(encoding="utf-8")
    install = (
        "from app.processing.pdf_opencv_modal_bridge import install_opencv_v4_modal_bridge\n"
        "from app.processing.pdf_page_presentation_bridge import "
        "install_pre_ocr_presentation_bridge\n"
        "from app.processing.pdf_page_presentation_classifier_compat import "
        "install_classifier_audit_compat\n"
        "from app.processing.pdf_page_presentation_preprocess_compat import "
        "install_preprocess_order_compat\n"
        "from app.processing.pdf_page_presentation_lifecycle_compat import "
        "install_presentation_lifecycle_compat\n"
        "from app.processing.pdf_page_orientation_compat import "
        "install_discrete_orientation_compat\n"
        "from app.processing.pdf_page_orientation_dimensions_compat import "
        "install_orientation_dimensions_compat\n"
        "from app.processing.pdf_page_analysis_fail_open_compat import "
        "install_analysis_render_fail_open_compat\n"
        "\n"
        "install_opencv_v4_modal_bridge()\n"
        "install_pre_ocr_presentation_bridge()\n"
        "install_classifier_audit_compat()\n"
        "install_preprocess_order_compat()\n"
        "install_presentation_lifecycle_compat()\n"
        "install_discrete_orientation_compat()\n"
        "install_orientation_dimensions_compat()\n"
        "install_analysis_render_fail_open_compat()\n\n"
    )
    current_without_analysis = (
        "from app.processing.pdf_opencv_modal_bridge import install_opencv_v4_modal_bridge\n"
        "from app.processing.pdf_page_presentation_bridge import "
        "install_pre_ocr_presentation_bridge\n"
        "from app.processing.pdf_page_presentation_classifier_compat import "
        "install_classifier_audit_compat\n"
        "from app.processing.pdf_page_presentation_preprocess_compat import "
        "install_preprocess_order_compat\n"
        "from app.processing.pdf_page_presentation_lifecycle_compat import "
        "install_presentation_lifecycle_compat\n"
        "from app.processing.pdf_page_orientation_compat import "
        "install_discrete_orientation_compat\n"
        "from app.processing.pdf_page_orientation_dimensions_compat import "
        "install_orientation_dimensions_compat\n"
        "\n"
        "install_opencv_v4_modal_bridge()\n"
        "install_pre_ocr_presentation_bridge()\n"
        "install_classifier_audit_compat()\n"
        "install_preprocess_order_compat()\n"
        "install_presentation_lifecycle_compat()\n"
        "install_discrete_orientation_compat()\n"
        "install_orientation_dimensions_compat()\n\n"
    )
    previous_install = (
        "from app.processing.pdf_opencv_modal_bridge import install_opencv_v4_modal_bridge\n"
        "from app.processing.pdf_page_presentation_bridge import "
        "install_pre_ocr_presentation_bridge\n"
        "from app.processing.pdf_page_presentation_classifier_compat import "
        "install_classifier_audit_compat\n"
        "from app.processing.pdf_page_presentation_preprocess_compat import "
        "install_preprocess_order_compat\n"
        "from app.processing.pdf_page_orientation_compat import "
        "install_discrete_orientation_compat\n"
        "from app.processing.pdf_page_orientation_dimensions_compat import "
        "install_orientation_dimensions_compat\n"
        "\n"
        "install_opencv_v4_modal_bridge()\n"
        "install_pre_ocr_presentation_bridge()\n"
        "install_classifier_audit_compat()\n"
        "install_preprocess_order_compat()\n"
        "install_discrete_orientation_compat()\n"
        "install_orientation_dimensions_compat()\n\n"
    )
    older_install = (
        "from app.processing.pdf_opencv_modal_bridge import install_opencv_v4_modal_bridge\n"
        "from app.processing.pdf_page_presentation_bridge import "
        "install_pre_ocr_presentation_bridge\n"
        "from app.processing.pdf_page_presentation_classifier_compat import "
        "install_classifier_audit_compat\n"
        "from app.processing.pdf_page_presentation_preprocess_compat import "
        "install_preprocess_order_compat\n"
        "from app.processing.pdf_page_orientation_compat import "
        "install_discrete_orientation_compat\n"
        "\n"
        "install_opencv_v4_modal_bridge()\n"
        "install_pre_ocr_presentation_bridge()\n"
        "install_classifier_audit_compat()\n"
        "install_preprocess_order_compat()\n"
        "install_discrete_orientation_compat()\n\n"
    )
    old_install = (
        "from app.processing.pdf_opencv_modal_bridge import install_opencv_v4_modal_bridge\n"
        "from app.processing.pdf_page_presentation_bridge import "
        "install_pre_ocr_presentation_bridge\n"
        "from app.processing.pdf_page_presentation_classifier_compat import "
        "install_classifier_audit_compat\n"
        "from app.processing.pdf_page_presentation_preprocess_compat import "
        "install_preprocess_order_compat\n"
        "\n"
        "install_opencv_v4_modal_bridge()\n"
        "install_pre_ocr_presentation_bridge()\n"
        "install_classifier_audit_compat()\n"
        "install_preprocess_order_compat()\n\n"
    )
    oldest_install = (
        "from app.processing.pdf_opencv_modal_bridge import install_opencv_v4_modal_bridge\n"
        "from app.processing.pdf_page_presentation_bridge import "
        "install_pre_ocr_presentation_bridge\n"
        "from app.processing.pdf_page_presentation_classifier_compat import "
        "install_classifier_audit_compat\n"
        "\n"
        "install_opencv_v4_modal_bridge()\n"
        "install_pre_ocr_presentation_bridge()\n"
        "install_classifier_audit_compat()\n\n"
    )
    legacy_install = (
        "from app.processing.pdf_opencv_modal_bridge import install_opencv_v4_modal_bridge\n"
        "\n"
        "install_opencv_v4_modal_bridge()\n\n"
    )
    if install not in source:
        if current_without_analysis in source:
            source = source.replace(current_without_analysis, install, 1)
        elif previous_install in source:
            source = source.replace(previous_install, install, 1)
        elif older_install in source:
            source = source.replace(older_install, install, 1)
        elif old_install in source:
            source = source.replace(old_install, install, 1)
        elif oldest_install in source:
            source = source.replace(oldest_install, install, 1)
        elif legacy_install in source:
            source = source.replace(legacy_install, install, 1)
        else:
            anchor = "from app.config import settings\n"
            if source.count(anchor) != 1:
                raise RuntimeError("Could not find the unique pdf_ingestion bridge anchor")
            source = source.replace(anchor, anchor + install, 1)

    if "PDF_PROVIDER_SKIPPED" in source or "PDF_OPENCV_EXPERIMENT_SKIP_PROVIDER" in source:
        raise RuntimeError("Provider-skip patch is present; refusing to install Modal bridge")
    required = (
        "PaddleVLClient(",
        "ProviderInputChecksumProvider(",
        "EndToEndProcessingIntegrationService(",
    )
    missing = [value for value in required if value not in source]
    if missing:
        raise RuntimeError(f"Production Modal path is incomplete: {missing}")

    path.write_text(source, encoding="utf-8")


def main() -> None:
    _patch_visual_retry_policy()
    _install_bridge_import()


if __name__ == "__main__":
    main()
