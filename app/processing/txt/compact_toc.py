"""Deterministic recovery for compact TXT table-of-contents lines."""
from __future__ import annotations

from dataclasses import replace
import re

from app.processing.structured_result_v2.model import ProcessingNode, ProcessingNodeKind, StructuredProcessingResultV2
from app.processing.structured_result_v2.validation import validate_spr_v2
from app.processing.txt.normalization import NormalizedTxtSource, TxtSourceLine
from app.processing.txt._structure_recovery_core import TxtLineStructureAssignment, TxtStructureKind, TxtStructureWindowResult
from app.source_units import TextSpanAnchor

_COMPACT_TOC_MAX_LINE_CHARS = 240
_COMPACT_TOC_MAX_ENTRY_CHARS = 120
_CHINESE_ORDINAL = "〇零一二三四五六七八九十百千万两"
_COMPACT_TOC_MARKER_RE = re.compile(rf"(?<!\S)(?:第[{_CHINESE_ORDINAL}0-9]+[章节卷部篇]|卷[{_CHINESE_ORDINAL}0-9]+)")


def _compact_toc_segments(line: TxtSourceLine) -> tuple[tuple[int, int], ...]:
    text = line.text
    if not text or len(text) > _COMPACT_TOC_MAX_LINE_CHARS:
        return ()
    matches = tuple(_COMPACT_TOC_MARKER_RE.finditer(text))
    if len(matches) < 2 or text[: matches[0].start()].strip():
        return ()
    spans: list[tuple[int, int]] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start >= end or end - start > _COMPACT_TOC_MAX_ENTRY_CHARS:
            return ()
        spans.append((start, end))
    return tuple(spans)


def compact_toc_line_ids(source: NormalizedTxtSource) -> frozenset[str]:
    if not isinstance(source, NormalizedTxtSource):
        raise TypeError("source must be a NormalizedTxtSource")
    return frozenset(line.line_id for line in source.lines if not line.is_empty and _compact_toc_segments(line))


def reclassify_compact_toc_window_results(source: NormalizedTxtSource, window_results: tuple[TxtStructureWindowResult, ...]) -> tuple[TxtStructureWindowResult, ...]:
    target_ids = compact_toc_line_ids(source)
    if not target_ids:
        return window_results
    rewritten: list[TxtStructureWindowResult] = []
    for result in window_results:
        assignments = tuple(
            TxtLineStructureAssignment(assignment.line_id, TxtStructureKind.TOC, True, None)
            if assignment.line_id in target_ids else assignment
            for assignment in result.assignments
        )
        rewritten.append(TxtStructureWindowResult(result.window_id, assignments))
    return tuple(rewritten)


def split_compact_toc_nodes(source: NormalizedTxtSource, spr: StructuredProcessingResultV2) -> StructuredProcessingResultV2:
    line_by_id = {line.line_id: line for line in source.lines}
    expanded: list[ProcessingNode] = []
    for node in sorted(spr.nodes, key=lambda item: (item.order, item.node_id)):
        metadata = dict(node.metadata or {})
        source_line_ids = metadata.get("source_line_ids")
        if isinstance(source_line_ids, list):
            source_line_ids = tuple(source_line_ids)
        line = None
        if metadata.get("txt_structure_kind") == TxtStructureKind.TOC.value and isinstance(source_line_ids, tuple) and len(source_line_ids) == 1 and isinstance(source_line_ids[0], str):
            line = line_by_id.get(source_line_ids[0])
        spans = _compact_toc_segments(line) if line is not None else ()
        if not spans:
            expanded.append(node)
            continue
        if len(node.source_unit_ids) != 1:
            raise ValueError("compact TOC node must belong to exactly one source unit")
        source_unit_id = node.source_unit_ids[0]
        for segment_index, (relative_start, relative_end) in enumerate(spans, start=1):
            absolute_start = line.body_start + relative_start
            absolute_end = line.body_start + relative_end
            segment_metadata = dict(metadata)
            segment_metadata.update({
                "recovery_rule": "txt_compact_toc_split",
                "txt_structure_kind": TxtStructureKind.TOC.value,
                "compact_toc_segment_index": segment_index,
                "compact_toc_segment_count": len(spans),
                "source_line_ids": (line.line_id,),
            })
            expanded.append(ProcessingNode(
                node_id=f"{node.node_id}:toc-{segment_index:02d}",
                kind=ProcessingNodeKind.REFERENCE,
                order=0,
                source_unit_ids=node.source_unit_ids,
                parent_id=node.parent_id,
                text=source.decoded.text[absolute_start:absolute_end],
                heading_level=None,
                anchors=(TextSpanAnchor(source_unit_id, absolute_start, absolute_end),),
                observation_ids=node.observation_ids,
                evidence_ids=node.evidence_ids,
                recovery_state=node.recovery_state,
                metadata=segment_metadata,
            ))
    nodes = tuple(replace(node, order=order) for order, node in enumerate(expanded))
    result = StructuredProcessingResultV2(
        document_ref=spr.document_ref,
        processing_run_ref=spr.processing_run_ref,
        raw_result_ref=spr.raw_result_ref,
        source_units=spr.source_units,
        observations=spr.observations,
        nodes=nodes,
        evidence=spr.evidence,
        schema_id=spr.schema_id,
        schema_version=spr.schema_version,
    )
    validate_spr_v2(result)
    return result


__all__ = ["compact_toc_line_ids", "reclassify_compact_toc_window_results", "split_compact_toc_nodes"]
