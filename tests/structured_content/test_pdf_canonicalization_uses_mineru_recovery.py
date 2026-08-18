from __future__ import annotations

import ast
from pathlib import Path

from app.processing import pdf_recovery
from app.processing.pdf_page_presentation_recovery import (
    recover_pdf_observations_for_page_presentation,
)


def test_canonical_pdf_recovery_entrypoint_uses_page_presentation_layer() -> None:
    assert (
        pdf_recovery.recover_pdf_observations_to_spr_v2
        is recover_pdf_observations_for_page_presentation
    )


def test_page_presentation_layer_delegates_body_recovery_to_mineru_popo() -> None:
    path = Path("app/processing/pdf_page_presentation_recovery.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "app.processing.mineru_popo_pdf_recovery"
        for alias in node.names
    }
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "recover_pdf_observations_via_mineru_popo" in imported_names
    assert "recover_pdf_observations_via_mineru_popo" in called_names
