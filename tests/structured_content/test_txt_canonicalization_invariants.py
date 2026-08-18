from __future__ import annotations

import pytest

from app.processing.txt.canonicalization import (
    TxtCanonicalizationError,
    _enforce_document_title_level_one,
)
from app.processing.txt.structure_recovery import (
    TxtHeadingLevelAssignment,
    TxtOutlineAnalysisWindow,
    TxtOutlineCandidate,
    TxtOutlineWindowResult,
    TxtStructureKind,
)


def test_any_outline_provider_must_keep_document_title_at_level_one() -> None:
    window = TxtOutlineAnalysisWindow(
        "txt-outline-window:000001",
        0,
        (
            TxtOutlineCandidate("L000001", "Book", TxtStructureKind.TITLE, 1),
            TxtOutlineCandidate("L000002", "Chapter", TxtStructureKind.HEADING, 1),
        ),
    )
    result = TxtOutlineWindowResult(
        window.window_id,
        (
            TxtHeadingLevelAssignment("L000001", 2),
            TxtHeadingLevelAssignment("L000002", 1),
        ),
    )

    with pytest.raises(TxtCanonicalizationError, match="cannot demote the document title"):
        _enforce_document_title_level_one((window,), (result,))


def test_heading_levels_remain_reconcilable_when_title_stays_level_one() -> None:
    window = TxtOutlineAnalysisWindow(
        "txt-outline-window:000001",
        0,
        (
            TxtOutlineCandidate("L000001", "Book", TxtStructureKind.TITLE, 1),
            TxtOutlineCandidate("L000002", "Detail", TxtStructureKind.HEADING, 1),
        ),
    )
    result = TxtOutlineWindowResult(
        window.window_id,
        (
            TxtHeadingLevelAssignment("L000001", 1),
            TxtHeadingLevelAssignment("L000002", 2),
        ),
    )

    assert _enforce_document_title_level_one((window,), (result,)) is None
