"""Public TXT structure-recovery API with deterministic compact-TOC recovery."""
from __future__ import annotations

from app.processing.txt import _structure_recovery_core as _core
from app.processing.txt.compact_toc import reclassify_compact_toc_window_results, split_compact_toc_nodes

DEFAULT_ANALYSIS_WINDOW_OVERLAP_LINES = _core.DEFAULT_ANALYSIS_WINDOW_OVERLAP_LINES
DEFAULT_MAX_LINES_PER_ANALYSIS_WINDOW = _core.DEFAULT_MAX_LINES_PER_ANALYSIS_WINDOW
DEFAULT_MAX_OUTLINE_CANDIDATES_PER_WINDOW = _core.DEFAULT_MAX_OUTLINE_CANDIDATES_PER_WINDOW
DEFAULT_OUTLINE_WINDOW_OVERLAP_CANDIDATES = _core.DEFAULT_OUTLINE_WINDOW_OVERLAP_CANDIDATES
TxtHeadingLevelAssignment = _core.TxtHeadingLevelAssignment
TxtLineStructureAssignment = _core.TxtLineStructureAssignment
TxtOutlineAnalysisWindow = _core.TxtOutlineAnalysisWindow
TxtOutlineCandidate = _core.TxtOutlineCandidate
TxtOutlineReconciler = _core.TxtOutlineReconciler
TxtOutlineWindowResult = _core.TxtOutlineWindowResult
TxtStructureAnalysisWindow = _core.TxtStructureAnalysisWindow
TxtStructureAnalyzer = _core.TxtStructureAnalyzer
TxtStructureKind = _core.TxtStructureKind
TxtStructureRecoveryError = _core.TxtStructureRecoveryError
TxtStructureWindowLine = _core.TxtStructureWindowLine
TxtStructureWindowResult = _core.TxtStructureWindowResult
apply_txt_outline_levels = _core.apply_txt_outline_levels
build_txt_outline_windows = _core.build_txt_outline_windows
build_txt_structure_windows = _core.build_txt_structure_windows
reconcile_txt_outline_levels = _core.reconcile_txt_outline_levels

def reconcile_txt_window_assignments(source, window_results, *, max_lines=DEFAULT_MAX_LINES_PER_ANALYSIS_WINDOW, overlap_lines=DEFAULT_ANALYSIS_WINDOW_OVERLAP_LINES):
    rewritten = reclassify_compact_toc_window_results(source, window_results)
    return _core.reconcile_txt_window_assignments(source, rewritten, max_lines=max_lines, overlap_lines=overlap_lines)

def recover_txt_structure_to_spr_v2(source, window_results, *, outline_results=None, max_lines=DEFAULT_MAX_LINES_PER_ANALYSIS_WINDOW, overlap_lines=DEFAULT_ANALYSIS_WINDOW_OVERLAP_LINES, max_outline_candidates=DEFAULT_MAX_OUTLINE_CANDIDATES_PER_WINDOW, outline_overlap_candidates=DEFAULT_OUTLINE_WINDOW_OVERLAP_CANDIDATES):
    rewritten = reclassify_compact_toc_window_results(source, window_results)
    spr = _core.recover_txt_structure_to_spr_v2(
        source,
        rewritten,
        outline_results=outline_results,
        max_lines=max_lines,
        overlap_lines=overlap_lines,
        max_outline_candidates=max_outline_candidates,
        outline_overlap_candidates=outline_overlap_candidates,
    )
    return split_compact_toc_nodes(source, spr)

__all__ = [
    "DEFAULT_ANALYSIS_WINDOW_OVERLAP_LINES",
    "DEFAULT_MAX_LINES_PER_ANALYSIS_WINDOW",
    "DEFAULT_MAX_OUTLINE_CANDIDATES_PER_WINDOW",
    "DEFAULT_OUTLINE_WINDOW_OVERLAP_CANDIDATES",
    "TxtHeadingLevelAssignment",
    "TxtLineStructureAssignment",
    "TxtOutlineAnalysisWindow",
    "TxtOutlineCandidate",
    "TxtOutlineReconciler",
    "TxtOutlineWindowResult",
    "TxtStructureAnalysisWindow",
    "TxtStructureAnalyzer",
    "TxtStructureKind",
    "TxtStructureRecoveryError",
    "TxtStructureWindowLine",
    "TxtStructureWindowResult",
    "apply_txt_outline_levels",
    "build_txt_outline_windows",
    "build_txt_structure_windows",
    "reconcile_txt_outline_levels",
    "reconcile_txt_window_assignments",
    "recover_txt_structure_to_spr_v2",
]
