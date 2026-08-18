"""Provider-agnostic TXT structure-analysis contracts and deterministic reconciliation.

The structure analyzer may classify stable source lines, but it never owns text.
Recovered SPR node text is copied from Phase 7A's decoded retained TXT source.
A second bounded outline pass may reconcile title/heading levels across local
analysis windows; it still returns source identities and structure only.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from app.processing.structured_result_v2.model import (
    ProcessingNode,
    ProcessingNodeKind,
    StructuredProcessingResultV2,
)
from app.processing.structured_result_v2.validation import validate_spr_v2
from app.processing.txt.normalization import NormalizedTxtSource, TxtSourceLine


DEFAULT_MAX_LINES_PER_ANALYSIS_WINDOW = 80
DEFAULT_ANALYSIS_WINDOW_OVERLAP_LINES = 12
DEFAULT_MAX_OUTLINE_CANDIDATES_PER_WINDOW = 120
DEFAULT_OUTLINE_WINDOW_OVERLAP_CANDIDATES = 20
_REPEATED_RUNNING_HEADER_MIN_OCCURRENCES = 3
_REPEATED_RUNNING_HEADER_MAX_CHARS = 160
_REPEATED_RUNNING_HEADER_ELIGIBLE_KINDS = frozenset(
    {
        "title",
        "heading",
        "paragraph",
        "header",
        "unknown",
    }
)


class TxtStructureRecoveryError(ValueError):
    """Raised when TXT structure-analysis output cannot be reconciled safely."""


class TxtStructureKind(str, Enum):
    TITLE = "title"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    LIST_ITEM = "list_item"
    CAPTION = "caption"
    FORMULA = "formula"
    HEADER = "header"
    FOOTER = "footer"
    FOOTNOTE = "footnote"
    TABLE = "table"
    FIGURE = "figure"
    QUOTE = "quote"
    CODE = "code"
    REFERENCE = "reference"
    TOC = "toc"
    UNKNOWN = "unknown"


_KIND_MAP: dict[TxtStructureKind, ProcessingNodeKind] = {
    TxtStructureKind.TITLE: ProcessingNodeKind.TITLE,
    TxtStructureKind.HEADING: ProcessingNodeKind.HEADING,
    TxtStructureKind.PARAGRAPH: ProcessingNodeKind.PARAGRAPH,
    TxtStructureKind.LIST: ProcessingNodeKind.LIST,
    TxtStructureKind.LIST_ITEM: ProcessingNodeKind.LIST_ITEM,
    TxtStructureKind.CAPTION: ProcessingNodeKind.CAPTION,
    TxtStructureKind.FORMULA: ProcessingNodeKind.FORMULA,
    TxtStructureKind.HEADER: ProcessingNodeKind.HEADER,
    TxtStructureKind.FOOTER: ProcessingNodeKind.FOOTER,
    TxtStructureKind.FOOTNOTE: ProcessingNodeKind.FOOTNOTE,
    TxtStructureKind.TABLE: ProcessingNodeKind.TABLE,
    TxtStructureKind.FIGURE: ProcessingNodeKind.FIGURE,
    TxtStructureKind.QUOTE: ProcessingNodeKind.QUOTE,
    TxtStructureKind.CODE: ProcessingNodeKind.CODE,
    TxtStructureKind.REFERENCE: ProcessingNodeKind.REFERENCE,
    TxtStructureKind.TOC: ProcessingNodeKind.REFERENCE,
    TxtStructureKind.UNKNOWN: ProcessingNodeKind.UNKNOWN,
}


@dataclass(frozen=True, slots=True)
class TxtStructureWindowLine:
    line_id: str
    text: str
    is_empty: bool


@dataclass(frozen=True, slots=True)
class TxtStructureAnalysisWindow:
    window_id: str
    window_order: int
    lines: tuple[TxtStructureWindowLine, ...]


@dataclass(frozen=True, slots=True)
class TxtLineStructureAssignment:
    line_id: str
    kind: TxtStructureKind
    starts_new_node: bool
    heading_level: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.line_id, str) or not self.line_id.strip():
            raise TxtStructureRecoveryError("line_id must be a non-empty string")
        if not isinstance(self.kind, TxtStructureKind):
            raise TxtStructureRecoveryError("kind must be a TxtStructureKind")
        if not isinstance(self.starts_new_node, bool):
            raise TxtStructureRecoveryError("starts_new_node must be boolean")
        if self.kind is TxtStructureKind.HEADING:
            if (
                not isinstance(self.heading_level, int)
                or isinstance(self.heading_level, bool)
                or not 1 <= self.heading_level <= 6
            ):
                raise TxtStructureRecoveryError(
                    "heading assignments require a positive heading_level from 1 through 6"
                )
        elif self.kind is TxtStructureKind.TITLE:
            if self.heading_level is not None and (
                not isinstance(self.heading_level, int)
                or isinstance(self.heading_level, bool)
                or not 1 <= self.heading_level <= 6
            ):
                raise TxtStructureRecoveryError(
                    "title heading_level must be a positive integer from 1 through 6 when supplied"
                )
        elif self.heading_level is not None:
            raise TxtStructureRecoveryError("heading_level is only valid for title/heading assignments")
        if self.kind in {TxtStructureKind.TITLE, TxtStructureKind.HEADING} and not self.starts_new_node:
            raise TxtStructureRecoveryError("title/heading assignments must start a new node")


@dataclass(frozen=True, slots=True)
class TxtStructureWindowResult:
    window_id: str
    assignments: tuple[TxtLineStructureAssignment, ...]


@dataclass(frozen=True, slots=True)
class TxtOutlineCandidate:
    line_id: str
    text: str
    kind: TxtStructureKind
    proposed_heading_level: int

    def __post_init__(self) -> None:
        if self.kind not in {TxtStructureKind.TITLE, TxtStructureKind.HEADING}:
            raise TxtStructureRecoveryError("outline candidates must be title or heading")
        if not 1 <= self.proposed_heading_level <= 6:
            raise TxtStructureRecoveryError("outline proposed heading level must be from 1 through 6")


@dataclass(frozen=True, slots=True)
class TxtOutlineAnalysisWindow:
    window_id: str
    window_order: int
    candidates: tuple[TxtOutlineCandidate, ...]


@dataclass(frozen=True, slots=True)
class TxtHeadingLevelAssignment:
    line_id: str
    heading_level: int

    def __post_init__(self) -> None:
        if not isinstance(self.line_id, str) or not self.line_id.strip():
            raise TxtStructureRecoveryError("outline line_id must be a non-empty string")
        if (
            not isinstance(self.heading_level, int)
            or isinstance(self.heading_level, bool)
            or not 1 <= self.heading_level <= 6
        ):
            raise TxtStructureRecoveryError("outline heading_level must be an integer from 1 through 6")


@dataclass(frozen=True, slots=True)
class TxtOutlineWindowResult:
    window_id: str
    assignments: tuple[TxtHeadingLevelAssignment, ...]


class TxtStructureAnalyzer(Protocol):
    """Provider-neutral local structure analyzer contract."""

    def analyze(self, window: TxtStructureAnalysisWindow) -> TxtStructureWindowResult:
        ...


class TxtOutlineReconciler(Protocol):
    """Optional second-pass document outline reconciler.

    The reconciler may adjust heading levels for already identified title/heading
    candidates. It cannot return replacement text, create headings, or own parent
    identifiers; deterministic backend hierarchy construction remains authoritative.
    """

    def reconcile_outline(self, window: TxtOutlineAnalysisWindow) -> TxtOutlineWindowResult:
        ...


@dataclass(frozen=True, slots=True)
class _NodeGroup:
    lines: tuple[TxtSourceLine, ...]
    assignment: TxtLineStructureAssignment


def _validate_window_bounds(max_items: int, overlap_items: int, *, item_name: str) -> None:
    if not isinstance(max_items, int) or isinstance(max_items, bool) or max_items <= 0:
        raise TxtStructureRecoveryError(f"max_{item_name} must be a positive integer")
    if not isinstance(overlap_items, int) or isinstance(overlap_items, bool) or overlap_items < 0:
        raise TxtStructureRecoveryError(f"{item_name}_overlap must be a nonnegative integer")
    if overlap_items >= max_items:
        raise TxtStructureRecoveryError(f"{item_name}_overlap must be smaller than max_{item_name}")


def build_txt_structure_windows(
    source: NormalizedTxtSource,
    *,
    max_lines: int = DEFAULT_MAX_LINES_PER_ANALYSIS_WINDOW,
    overlap_lines: int = DEFAULT_ANALYSIS_WINDOW_OVERLAP_LINES,
) -> tuple[TxtStructureAnalysisWindow, ...]:
    if not isinstance(source, NormalizedTxtSource):
        raise TypeError("source must be a NormalizedTxtSource")
    if not isinstance(max_lines, int) or isinstance(max_lines, bool) or max_lines <= 0:
        raise TxtStructureRecoveryError("max_lines must be a positive integer")
    if not isinstance(overlap_lines, int) or isinstance(overlap_lines, bool) or overlap_lines < 0:
        raise TxtStructureRecoveryError("overlap_lines must be a nonnegative integer")
    if overlap_lines >= max_lines:
        raise TxtStructureRecoveryError("overlap_lines must be smaller than max_lines")

    windows: list[TxtStructureAnalysisWindow] = []
    start = 0
    order = 0
    while start < len(source.lines):
        end = min(start + max_lines, len(source.lines))
        lines = tuple(
            TxtStructureWindowLine(line.line_id, line.text, line.is_empty)
            for line in source.lines[start:end]
        )
        windows.append(
            TxtStructureAnalysisWindow(
                window_id=f"txt-structure-window:{order + 1:06d}",
                window_order=order,
                lines=lines,
            )
        )
        if end == len(source.lines):
            break
        start = end - overlap_lines
        order += 1
    return tuple(windows)


def reconcile_txt_window_assignments(
    source: NormalizedTxtSource,
    window_results: tuple[TxtStructureWindowResult, ...],
    *,
    max_lines: int = DEFAULT_MAX_LINES_PER_ANALYSIS_WINDOW,
    overlap_lines: int = DEFAULT_ANALYSIS_WINDOW_OVERLAP_LINES,
) -> dict[str, TxtLineStructureAssignment]:
    windows = build_txt_structure_windows(source, max_lines=max_lines, overlap_lines=overlap_lines)
    return _reconcile_assignments(source, windows, window_results)


def build_txt_outline_windows(
    source: NormalizedTxtSource,
    assignments: dict[str, TxtLineStructureAssignment],
    *,
    max_candidates: int = DEFAULT_MAX_OUTLINE_CANDIDATES_PER_WINDOW,
    overlap_candidates: int = DEFAULT_OUTLINE_WINDOW_OVERLAP_CANDIDATES,
) -> tuple[TxtOutlineAnalysisWindow, ...]:
    """Build a compact bounded document outline from local title/heading decisions."""
    if not isinstance(source, NormalizedTxtSource):
        raise TypeError("source must be a NormalizedTxtSource")
    if not isinstance(max_candidates, int) or isinstance(max_candidates, bool) or max_candidates <= 0:
        raise TxtStructureRecoveryError("max_candidates must be a positive integer")
    if not isinstance(overlap_candidates, int) or isinstance(overlap_candidates, bool) or overlap_candidates < 0:
        raise TxtStructureRecoveryError("overlap_candidates must be a nonnegative integer")
    if overlap_candidates >= max_candidates:
        raise TxtStructureRecoveryError("overlap_candidates must be smaller than max_candidates")

    candidates: list[TxtOutlineCandidate] = []
    for line in source.lines:
        if line.is_empty:
            continue
        assignment = assignments.get(line.line_id)
        if assignment is None:
            raise TxtStructureRecoveryError(f"source line has no structure assignment: {line.line_id}")
        if assignment.kind not in {TxtStructureKind.TITLE, TxtStructureKind.HEADING}:
            continue
        candidates.append(
            TxtOutlineCandidate(
                line_id=line.line_id,
                text=line.text,
                kind=assignment.kind,
                proposed_heading_level=assignment.heading_level or 1,
            )
        )

    windows: list[TxtOutlineAnalysisWindow] = []
    start = 0
    order = 0
    while start < len(candidates):
        end = min(start + max_candidates, len(candidates))
        windows.append(
            TxtOutlineAnalysisWindow(
                window_id=f"txt-outline-window:{order + 1:06d}",
                window_order=order,
                candidates=tuple(candidates[start:end]),
            )
        )
        if end == len(candidates):
            break
        start = end - overlap_candidates
        order += 1
    return tuple(windows)


def reconcile_txt_outline_levels(
    windows: tuple[TxtOutlineAnalysisWindow, ...],
    results: tuple[TxtOutlineWindowResult, ...],
) -> dict[str, int]:
    """Validate and deterministically reconcile overlapping outline-level decisions."""
    window_by_id = {window.window_id: window for window in windows}
    result_by_id: dict[str, TxtOutlineWindowResult] = {}
    for result in results:
        if result.window_id not in window_by_id:
            raise TxtStructureRecoveryError(f"unknown outline window: {result.window_id}")
        if result.window_id in result_by_id:
            raise TxtStructureRecoveryError(f"duplicate result for outline window: {result.window_id}")
        result_by_id[result.window_id] = result
    if set(result_by_id) != set(window_by_id):
        missing = sorted(set(window_by_id) - set(result_by_id))
        raise TxtStructureRecoveryError(f"missing outline window results: {', '.join(missing)}")

    votes: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for window in windows:
        allowed = {candidate.line_id for candidate in window.candidates}
        seen: set[str] = set()
        for assignment in result_by_id[window.window_id].assignments:
            if assignment.line_id not in allowed:
                raise TxtStructureRecoveryError(
                    f"outline window {window.window_id} references candidate outside the window: {assignment.line_id}"
                )
            if assignment.line_id in seen:
                raise TxtStructureRecoveryError(
                    f"outline window {window.window_id} contains duplicate assignment for {assignment.line_id}"
                )
            seen.add(assignment.line_id)
            votes[assignment.line_id].append((window.window_order, assignment.heading_level))
        if seen != allowed:
            missing = sorted(allowed - seen)
            raise TxtStructureRecoveryError(
                f"outline window {window.window_id} is missing assignments for: {', '.join(missing)}"
            )

    reconciled: dict[str, int] = {}
    for window in windows:
        for candidate in window.candidates:
            if candidate.line_id in reconciled:
                continue
            line_votes = votes[candidate.line_id]
            counts = Counter(level for _, level in line_votes)
            max_count = max(counts.values())
            winning_levels = {level for level, count in counts.items() if count == max_count}
            _, level = min(
                (order, level)
                for order, level in line_votes
                if level in winning_levels
            )
            reconciled[candidate.line_id] = level
    return reconciled


def apply_txt_outline_levels(
    assignments: dict[str, TxtLineStructureAssignment],
    outline_levels: dict[str, int],
) -> dict[str, TxtLineStructureAssignment]:
    """Apply only validated level corrections to existing title/heading candidates."""
    result = dict(assignments)
    for line_id, heading_level in outline_levels.items():
        current = result.get(line_id)
        if current is None:
            raise TxtStructureRecoveryError(f"outline references unknown source line: {line_id}")
        if current.kind not in {TxtStructureKind.TITLE, TxtStructureKind.HEADING}:
            raise TxtStructureRecoveryError(f"outline references non-heading source line: {line_id}")
        result[line_id] = TxtLineStructureAssignment(
            line_id=current.line_id,
            kind=current.kind,
            starts_new_node=current.starts_new_node,
            heading_level=heading_level,
        )
    return result


def recover_txt_structure_to_spr_v2(
    source: NormalizedTxtSource,
    window_results: tuple[TxtStructureWindowResult, ...],
    *,
    outline_results: tuple[TxtOutlineWindowResult, ...] | None = None,
    max_lines: int = DEFAULT_MAX_LINES_PER_ANALYSIS_WINDOW,
    overlap_lines: int = DEFAULT_ANALYSIS_WINDOW_OVERLAP_LINES,
    max_outline_candidates: int = DEFAULT_MAX_OUTLINE_CANDIDATES_PER_WINDOW,
    outline_overlap_candidates: int = DEFAULT_OUTLINE_WINDOW_OVERLAP_CANDIDATES,
) -> StructuredProcessingResultV2:
    """Reconcile bounded structure analysis and optional global outline into SPR v2."""
    windows = build_txt_structure_windows(source, max_lines=max_lines, overlap_lines=overlap_lines)
    base = source.bundle
    ordered_units = tuple(sorted(base.source_units, key=lambda unit: (unit.source_order, unit.source_unit_id)))
    unit_order = {unit.source_unit_id: unit.source_order for unit in ordered_units}
    ordered_observations = tuple(
        sorted(
            base.observations,
            key=lambda item: (unit_order[item.source_unit_id], item.order, item.observation_id),
        )
    )
    ordered_evidence = tuple(sorted(base.evidence, key=lambda item: item.evidence_id))

    normalized_graph = StructuredProcessingResultV2(
        document_ref=base.document_ref,
        processing_run_ref=base.processing_run_ref,
        raw_result_ref=base.raw_result_ref,
        source_units=ordered_units,
        observations=ordered_observations,
        nodes=(),
        evidence=ordered_evidence,
    )
    validate_spr_v2(normalized_graph)

    consensus = _reconcile_assignments(source, windows, window_results)
    if outline_results is not None:
        outline_windows = build_txt_outline_windows(
            source,
            consensus,
            max_candidates=max_outline_candidates,
            overlap_candidates=outline_overlap_candidates,
        )
        if outline_windows:
            outline_levels = reconcile_txt_outline_levels(outline_windows, outline_results)
            consensus = apply_txt_outline_levels(consensus, outline_levels)
        elif outline_results:
            raise TxtStructureRecoveryError("outline results were supplied without heading candidates")

    groups = _group_lines(source, consensus)
    observation_by_line = _observation_by_line_id(ordered_observations)
    nodes = _build_nodes(source, groups, observation_by_line, unit_order)

    spr = StructuredProcessingResultV2(
        document_ref=base.document_ref,
        processing_run_ref=base.processing_run_ref,
        raw_result_ref=base.raw_result_ref,
        source_units=ordered_units,
        observations=ordered_observations,
        nodes=nodes,
        evidence=ordered_evidence,
    )
    validate_spr_v2(spr)
    return spr


def _reconcile_assignments(
    source: NormalizedTxtSource,
    windows: tuple[TxtStructureAnalysisWindow, ...],
    results: tuple[TxtStructureWindowResult, ...],
) -> dict[str, TxtLineStructureAssignment]:
    window_by_id = {window.window_id: window for window in windows}
    result_by_id: dict[str, TxtStructureWindowResult] = {}
    for result in results:
        if result.window_id not in window_by_id:
            raise TxtStructureRecoveryError(f"unknown analysis window: {result.window_id}")
        if result.window_id in result_by_id:
            raise TxtStructureRecoveryError(f"duplicate result for analysis window: {result.window_id}")
        result_by_id[result.window_id] = result
    if set(result_by_id) != set(window_by_id):
        missing = sorted(set(window_by_id) - set(result_by_id))
        raise TxtStructureRecoveryError(f"missing analysis window results: {', '.join(missing)}")

    votes: dict[str, list[tuple[int, TxtLineStructureAssignment]]] = defaultdict(list)
    source_line_by_id = {line.line_id: line for line in source.lines}

    for window in windows:
        result = result_by_id[window.window_id]
        allowed = {line.line_id: line for line in window.lines}
        seen: set[str] = set()
        for assignment in result.assignments:
            if assignment.line_id not in allowed:
                raise TxtStructureRecoveryError(
                    f"window {window.window_id} references line outside the window: {assignment.line_id}"
                )
            if assignment.line_id in seen:
                raise TxtStructureRecoveryError(
                    f"window {window.window_id} contains duplicate assignment for {assignment.line_id}"
                )
            seen.add(assignment.line_id)
            line = source_line_by_id[assignment.line_id]
            if line.is_empty:
                raise TxtStructureRecoveryError("empty source lines must not receive structural assignments")
            votes[assignment.line_id].append((window.window_order, assignment))

        expected_nonempty = {line.line_id for line in window.lines if not line.is_empty}
        if seen != expected_nonempty:
            missing = sorted(expected_nonempty - seen)
            raise TxtStructureRecoveryError(
                f"window {window.window_id} is missing assignments for: {', '.join(missing)}"
            )

    consensus: dict[str, TxtLineStructureAssignment] = {}
    for line in source.lines:
        if line.is_empty:
            continue
        line_votes = votes.get(line.line_id, [])
        if not line_votes:
            raise TxtStructureRecoveryError(f"source line has no structure assignment: {line.line_id}")
        keys = [
            (vote.kind.value, vote.starts_new_node, vote.heading_level)
            for _, vote in line_votes
        ]
        counts = Counter(keys)
        max_count = max(counts.values())
        candidate_keys = {key for key, count in counts.items() if count == max_count}
        winning_order, winning_assignment = min(
            (
                order,
                assignment,
            )
            for order, assignment in line_votes
            if (assignment.kind.value, assignment.starts_new_node, assignment.heading_level) in candidate_keys
        )
        _ = winning_order
        consensus[line.line_id] = winning_assignment
    return _reclassify_repeated_running_headers(source, consensus)


def _reclassify_repeated_running_headers(
    source: NormalizedTxtSource,
    assignments: dict[str, TxtLineStructureAssignment],
) -> dict[str, TxtLineStructureAssignment]:
    """Demote repeated standalone running labels without allowing them into the outline.

    Serial/ebook TXT sources commonly repeat an author + book-title line between
    chapters. Local LLM windows can classify different occurrences as title,
    heading, or paragraph. Exact short lines that recur at least three times and
    are separated through the document are treated as running headers after one
    semantic occurrence is retained. Canonical source text is never changed.
    """
    occurrences: dict[str, list[TxtSourceLine]] = defaultdict(list)
    for line in source.lines:
        if line.is_empty:
            continue
        assignment = assignments.get(line.line_id)
        if assignment is None:
            raise TxtStructureRecoveryError(f"source line has no structure assignment: {line.line_id}")
        comparison_text = line.text.strip()
        if (
            not comparison_text
            or len(comparison_text) > _REPEATED_RUNNING_HEADER_MAX_CHARS
            or assignment.kind.value not in _REPEATED_RUNNING_HEADER_ELIGIBLE_KINDS
        ):
            continue
        occurrences[comparison_text].append(line)

    result = dict(assignments)
    for lines in occurrences.values():
        if len(lines) < _REPEATED_RUNNING_HEADER_MIN_OCCURRENCES:
            continue
        # Repeated adjacent duplicate lines are more likely source duplication than
        # running furniture. Require recurrence across separated source positions.
        separated_gaps = sum(
            1
            for previous, current in zip(lines, lines[1:])
            if current.line_number - previous.line_number >= 2
        )
        if separated_gaps < 2:
            continue

        keeper = next(
            (
                line
                for line in lines
                if result[line.line_id].kind is TxtStructureKind.TITLE
            ),
            lines[0],
        )
        for line in lines:
            if line.line_id == keeper.line_id:
                continue
            result[line.line_id] = TxtLineStructureAssignment(
                line_id=line.line_id,
                kind=TxtStructureKind.HEADER,
                starts_new_node=True,
                heading_level=None,
            )
    return result


def _group_lines(
    source: NormalizedTxtSource,
    assignments: dict[str, TxtLineStructureAssignment],
) -> tuple[_NodeGroup, ...]:
    groups: list[_NodeGroup] = []
    current_lines: list[TxtSourceLine] = []
    current_assignment: TxtLineStructureAssignment | None = None
    previous_line: TxtSourceLine | None = None

    def flush() -> None:
        nonlocal current_lines, current_assignment
        if current_lines and current_assignment is not None:
            groups.append(_NodeGroup(tuple(current_lines), current_assignment))
        current_lines = []
        current_assignment = None

    for line in source.lines:
        if line.is_empty:
            flush()
            previous_line = line
            continue
        assignment = assignments[line.line_id]
        compatible = (
            current_assignment is not None
            and not assignment.starts_new_node
            and assignment.kind is current_assignment.kind
            and assignment.heading_level == current_assignment.heading_level
            and previous_line is not None
            and previous_line.line_number + 1 == line.line_number
            and not previous_line.is_empty
        )
        if not compatible:
            flush()
            current_assignment = assignment
        current_lines.append(line)
        previous_line = line
    flush()
    return tuple(groups)


def _observation_by_line_id(observations) -> dict[str, object]:
    result: dict[str, object] = {}
    for observation in observations:
        metadata = observation.metadata or {}
        line_id = metadata.get("line_id")
        if not isinstance(line_id, str) or not line_id:
            raise TxtStructureRecoveryError("TXT observation is missing stable line_id metadata")
        if line_id in result:
            raise TxtStructureRecoveryError(f"duplicate TXT observation line_id: {line_id}")
        result[line_id] = observation
    return result


def _build_nodes(
    source: NormalizedTxtSource,
    groups: tuple[_NodeGroup, ...],
    observation_by_line: dict[str, object],
    unit_order: dict[str, int],
) -> tuple[ProcessingNode, ...]:
    nodes: list[ProcessingNode] = []
    heading_stack: dict[int, str] = {}
    last_list_id: str | None = None

    for order, group in enumerate(groups):
        assignment = group.assignment
        processing_kind = _KIND_MAP[assignment.kind]
        first = group.lines[0]
        last = group.lines[-1]
        line_ids = tuple(line.line_id for line in group.lines)
        observations = []
        for line_id in line_ids:
            observation = observation_by_line.get(line_id)
            if observation is None:
                raise TxtStructureRecoveryError(f"missing TXT observation for source line: {line_id}")
            observations.append(observation)

        source_unit_ids = tuple(
            sorted(
                {observation.source_unit_id for observation in observations},
                key=lambda value: (unit_order[value], value),
            )
        )
        anchors = tuple(anchor for observation in observations for anchor in observation.anchors)
        observation_ids = tuple(observation.observation_id for observation in observations)
        evidence_ids = tuple(
            sorted({evidence_id for observation in observations for evidence_id in observation.evidence_ids})
        )
        text = source.decoded.text[first.body_start:last.body_end]
        node_id = f"txt-recovered-node:{first.line_id}-{last.line_id}"

        heading_level: int | None = None
        if processing_kind in {ProcessingNodeKind.TITLE, ProcessingNodeKind.HEADING}:
            heading_level = assignment.heading_level or 1
            parent_id = _nearest_heading_parent(heading_stack, heading_level)
            for level in tuple(heading_stack):
                if level >= heading_level:
                    del heading_stack[level]
            heading_stack[heading_level] = node_id
            last_list_id = None
        elif processing_kind is ProcessingNodeKind.LIST:
            parent_id = _deepest_heading(heading_stack)
            last_list_id = node_id
        elif processing_kind is ProcessingNodeKind.LIST_ITEM:
            parent_id = last_list_id or _deepest_heading(heading_stack)
        else:
            parent_id = _deepest_heading(heading_stack)
            last_list_id = None

        nodes.append(
            ProcessingNode(
                node_id=node_id,
                kind=processing_kind,
                order=order,
                source_unit_ids=source_unit_ids,
                parent_id=parent_id,
                text=text,
                heading_level=heading_level,
                anchors=anchors,
                observation_ids=observation_ids,
                evidence_ids=evidence_ids,
                metadata={
                    "recovery_rule": "txt_structure_assignment_reconciliation",
                    "txt_structure_kind": assignment.kind.value,
                    "source_line_ids": line_ids,
                },
            )
        )
    return tuple(nodes)


def _nearest_heading_parent(heading_stack: dict[int, str], level: int) -> str | None:
    lower = [candidate for candidate in heading_stack if candidate < level]
    return heading_stack[max(lower)] if lower else None


def _deepest_heading(heading_stack: dict[int, str]) -> str | None:
    return heading_stack[max(heading_stack)] if heading_stack else None


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
