"""Static and pure-function validation for the stable-v4 Modal bridge overlay."""
from __future__ import annotations

import ast
from pathlib import Path

from app.processing.pdf_opencv_modal_bridge import (
    _merge_manifest_into_raw_pages,
    _whole_page_rejected,
)


def main() -> None:
    ingestion = Path("app/processing/pdf_ingestion.py").read_text(encoding="utf-8")
    ast.parse(ingestion)
    assert "install_opencv_v4_modal_bridge()" in ingestion
    assert "PDF_PROVIDER_SKIPPED" not in ingestion
    assert "PDF_OPENCV_EXPERIMENT_SKIP_PROVIDER" not in ingestion
    assert "outcome = await service.process(request)" in ingestion

    rejected_page = {
        "page_number": 9,
        "route": "quality_gate_original",
        "selected": "original",
        "geometry": {"accepted": False, "gate": {"long_lines_safe": False}},
        "background": {
            "attempted": True,
            "accepted": False,
            "gate": {"edge_retention": 0.67},
        },
    }
    geometry_only_page = {
        **rejected_page,
        "route": "geometry_only",
        "selected": "geometry",
        "geometry": {"accepted": True, "gate": {"deskew_improved": True}},
    }

    assert _whole_page_rejected(rejected_page)
    assert _whole_page_rejected(geometry_only_page)
    assert not _whole_page_rejected({**geometry_only_page, "selected": "original"})
    assert not _whole_page_rejected({**geometry_only_page, "route": "quality_gate_original"})
    assert not _whole_page_rejected(
        {
            **geometry_only_page,
            "background": {
                "attempted": True,
                "accepted": True,
                "gate": {"edge_retention": 0.90},
            },
        }
    )
    assert not _whole_page_rejected(
        {
            **geometry_only_page,
            "background": {
                "attempted": False,
                "accepted": False,
                "gate": {},
            },
        }
    )

    merged = _merge_manifest_into_raw_pages(
        [
            {
                "page_number": 9,
                "width": 100,
                "height": 100,
                "metadata": {"provider": "paddle"},
            }
        ],
        {"pages": [rejected_page]},
    )
    assert merged[0]["metadata"]["provider"] == "paddle"
    assert merged[0]["metadata"]["opencv_preprocessing"]["page_number"] == 9
    print("opencv v4 Modal bridge validation passed")


if __name__ == "__main__":
    main()
