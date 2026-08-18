"""Provider-independent MinerU/Popo-style PDF structure recovery.

This module is the PDF structure-recovery stage between normalized OCR
observations and SPR v2.  It deliberately has no database, storage, network,
legacy ``PdfPage``, or ``MineruResult`` dependency.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

from app.processing.normalized_observations import NormalizedObservationBundle
from app.processing.structured_result_v2.model import (
    ProcessingNode,
    ProcessingNodeKind,
    StructuredProcessingResultV2,
)
from app.processing.structured_result_v2.validation import validate_spr_v2
from app.source_units import SpatialAnchor


_FURNITURE = frozenset(
    {
        "number",
        "page_number",
        "header",
        "page_header",
        "header_image",
        "footer",
        "page_footer",
        "footer_image",
        "aside_text",
        "sidebar",
        "marginal_note",
    }
)
_TITLE = frozenset({"doc_title", "document_title", "title"})
_HEADING = frozenset({"heading", "paragraph_title", "section_title", "headline", "para_title"})
_TEXT = frozenset({"text", "paragraph", "body", "body_text", "abstract"})
_TOC = frozenset({"toc", "catalog", "contents", "table_of_contents", "directory"})
_LIST = frozenset({"list"})
_LIST_ITEM = frozenset({"list_item", "bullet"})
_FIGURE = frozenset({"image", "figure", "picture", "photo", "chart", "diagram", "graphic", "illustration"})
_TABLE = frozenset({"table", "tabular"})
_CAPTION = frozenset({"caption", "figure_caption", "figure_title", "figure_note", "table_caption", "table_title"})
_FORMULA = frozenset({"formula", "equation", "isolate_formula", "display_formula", "inline_formula", "formula_number"})
_FOOTNOTE = frozenset({"footnote", "vision_footnote", "table_footnote"})
_REFERENCE = frozenset({"reference", "references", "reference_content"})
_CODE = frozenset({"code", "code_block", "algorithm"})

_FIGURE_CAPTION_KINDS = frozenset({"figure_caption", "figure_title", "figure_note"})
_TABLE_CAPTION_KINDS = frozenset({"table_caption", "table_title"})
_CAPTION_VISUAL_POLICY = "same_page_spatial_visual_v1"
_CAPTION_VISUAL_MAX_VERTICAL_GAP = 0.18
_CAPTION_VISUAL_MIN_HORIZONTAL_OVERLAP = 0.40
_CAPTION_VISUAL_MAX_CENTER_DELTA = 0.16
_CAPTION_VISUAL_AMBIGUITY_MARGIN = 0.025

_CJK_CHAPTER_RE = re.compile(r"^\s*第[^\s]{1,12}[章节篇部卷]")
_ARABIC_HEADING_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)[\s.:：、-]+")
_CJK_SECTION_RE = re.compile(r"^\s*[一二三四五六七八九十百]+[、.．]\s*")
_TOC_LINE_RE = re.compile(r"^\s*.+?(?:\.{2,}|…{2,}|·{2,}|\s{2,})\s*[0-9０-９IVXLCDMivxlcdm一二三四五六七八九十百千]+\s*$")
_SENTENCE_END_RE = re.compile(r"[。！？!?；;：:]\s*[\]\[）)】》〉」』”’\"']*\s*$")


def recover_pdf_observations_via_mineru_popo(bundle: NormalizedObservationBundle) -> StructuredProcessingResultV2:
    """Recover document-semantic PDF nodes and return validated SPR v2.

    The normalized observations remain the auditable provider evidence.  This
    function owns paragraph/list/heading recovery and may merge observations
    across physical pages, while the later canonical transformer remains pure.
    """
    ordered_units = tuple(sorted(bundle.source_units, key=lambda unit: (unit.source_order, unit.source_unit_id)))
    unit_order = {unit.source_unit_id: unit.source_order for unit in ordered_units}
    ordered_observations = tuple(
        sorted(
            bundle.observations,
            key=lambda item: (unit_order.get(item.source_unit_id, 2**31), item.order, item.observation_id),
        )
    )
    ordered_evidence = tuple(sorted(bundle.evidence, key=lambda item: item.evidence_id))

    # Validate the normalized observation/evidence graph first.
    validate_spr_v2(
        StructuredProcessingResultV2(
            document_ref=bundle.document_ref,
            processing_run_ref=bundle.processing_run_ref,
            raw_result_ref=bundle.raw_result_ref,
            source_units=ordered_units,
            observations=ordered_observations,
            nodes=(),
            evidence=ordered_evidence,
        )
    )

    nodes: list[ProcessingNode] = []
    heading_stack: dict[int, str] = {}
    active_list_id: str | None = None
    last_visual: tuple[str, str] | None = None

    for observation in ordered_observations:
        observed_kind = _kind(observation.observed_kind)
        text = (observation.text or "").strip()

        if observed_kind in _FURNITURE:
            continue

        if observed_kind in _TOC or _looks_like_toc_block(text):
            active_list_id = _append_toc(nodes, observation, text, heading_stack)
            last_visual = None
            continue

        semantic_kind = _semantic_kind(observed_kind)

        if semantic_kind in {ProcessingNodeKind.TITLE, ProcessingNodeKind.HEADING}:
            level = _heading_level(semantic_kind, text, observation.metadata)
            parent_id = _nearest_heading_parent(heading_stack, level)
            node = _node_from_observations(
                nodes,
                semantic_kind,
                (observation,),
                parent_id=parent_id,
                text=text,
                heading_level=level,
                recovery_rule="mineru_popo_heading",
            )
            for existing_level in tuple(heading_stack):
                if existing_level >= level:
                    del heading_stack[existing_level]
            heading_stack[level] = node.node_id
            active_list_id = None
            last_visual = None
            continue

        if semantic_kind is ProcessingNodeKind.LIST:
            node = _node_from_observations(
                nodes,
                ProcessingNodeKind.LIST,
                (observation,),
                parent_id=_deepest_heading(heading_stack),
                text=text or None,
                recovery_rule="mineru_popo_list",
            )
            active_list_id = node.node_id
            last_visual = None
            continue

        if semantic_kind is ProcessingNodeKind.LIST_ITEM:
            _node_from_observations(
                nodes,
                ProcessingNodeKind.LIST_ITEM,
                (observation,),
                parent_id=active_list_id or _deepest_heading(heading_stack),
                text=text,
                recovery_rule="mineru_popo_list_item",
            )
            last_visual = None
            continue

        if semantic_kind in {ProcessingNodeKind.FIGURE, ProcessingNodeKind.TABLE}:
            node = _node_from_observations(
                nodes,
                semantic_kind,
                (observation,),
                parent_id=_deepest_heading(heading_stack),
                text=text or None,
                recovery_rule="mineru_popo_visual",
            )
            last_visual = (node.node_id, observation.source_unit_id)
            active_list_id = None
            continue

        if semantic_kind is ProcessingNodeKind.CAPTION:
            parent_id = last_visual[0] if last_visual and last_visual[1] == observation.source_unit_id else _deepest_heading(heading_stack)
            _node_from_observations(
                nodes,
                ProcessingNodeKind.CAPTION,
                (observation,),
                parent_id=parent_id,
                text=text,
                recovery_rule="mineru_popo_caption_association",
            )
            active_list_id = None
            continue

        if semantic_kind is ProcessingNodeKind.PARAGRAPH and _can_continue_previous_paragraph(nodes, observation, unit_order):
            _merge_into_previous_paragraph(nodes, observation)
            active_list_id = None
            last_visual = None
            continue

        _node_from_observations(
            nodes,
            semantic_kind,
            (observation,),
            parent_id=_deepest_heading(heading_stack),
            text=text or None,
            recovery_rule="mineru_popo_semantic_block",
        )
        active_list_id = None
        if semantic_kind not in {ProcessingNodeKind.FIGURE, ProcessingNodeKind.TABLE}:
            last_visual = None

    nodes = _repair_caption_visual_associations(nodes, ordered_observations)

    spr = StructuredProcessingResultV2(
        document_ref=bundle.document_ref,
        processing_run_ref=bundle.processing_run_ref,
        raw_result_ref=bundle.raw_result_ref,
        source_units=ordered_units,
        observations=ordered_observations,
        nodes=tuple(nodes),
        evidence=ordered_evidence,
    )
    validate_spr_v2(spr)
    return spr


def _kind(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def _semantic_kind(kind: str) -> ProcessingNodeKind:
    if kind in _TITLE:
        return ProcessingNodeKind.TITLE
    if kind in _HEADING:
        return ProcessingNodeKind.HEADING
    if kind in _TEXT:
        return ProcessingNodeKind.PARAGRAPH
    if kind in _LIST:
        return ProcessingNodeKind.LIST
    if kind in _LIST_ITEM:
        return ProcessingNodeKind.LIST_ITEM
    if kind in _FIGURE:
        return ProcessingNodeKind.FIGURE
    if kind in _TABLE:
        return ProcessingNodeKind.TABLE
    if kind in _CAPTION:
        return ProcessingNodeKind.CAPTION
    if kind in _FORMULA:
        return ProcessingNodeKind.FORMULA
    if kind in _FOOTNOTE:
        return ProcessingNodeKind.FOOTNOTE
    if kind in _REFERENCE:
        return ProcessingNodeKind.REFERENCE
    if kind in _CODE:
        return ProcessingNodeKind.CODE
    return ProcessingNodeKind.UNKNOWN


def _heading_level(kind: ProcessingNodeKind, text: str, metadata) -> int:
    if metadata:
        explicit = metadata.get("heading_level")
        if isinstance(explicit, int) and not isinstance(explicit, bool) and explicit > 0:
            return min(explicit, 6)
    if kind is ProcessingNodeKind.TITLE or _CJK_CHAPTER_RE.match(text):
        return 1
    numbered = _ARABIC_HEADING_RE.match(text)
    if numbered:
        return min(numbered.group(1).count(".") + 1, 6)
    if _CJK_SECTION_RE.match(text):
        return 2
    return 2


def _nearest_heading_parent(stack: dict[int, str], level: int) -> str | None:
    candidates = [candidate for candidate in stack if candidate < level]
    return stack[max(candidates)] if candidates else None


def _deepest_heading(stack: dict[int, str]) -> str | None:
    return stack[max(stack)] if stack else None


def _node_from_observations(
    nodes: list[ProcessingNode],
    kind: ProcessingNodeKind,
    observations: tuple,
    *,
    parent_id: str | None,
    text: str | None,
    recovery_rule: str,
    heading_level: int | None = None,
) -> ProcessingNode:
    observation_ids = tuple(item.observation_id for item in observations)
    evidence_ids = tuple(dict.fromkeys(evidence_id for item in observations for evidence_id in item.evidence_ids))
    source_unit_ids = tuple(dict.fromkeys(item.source_unit_id for item in observations))
    anchors = tuple(anchor for item in observations for anchor in item.anchors)
    node = ProcessingNode(
        node_id=f"mineru-node:{observation_ids[0]}",
        kind=kind,
        order=len(nodes),
        source_unit_ids=source_unit_ids,
        parent_id=parent_id,
        text=text,
        heading_level=heading_level,
        anchors=anchors,
        observation_ids=observation_ids,
        evidence_ids=evidence_ids,
        metadata={"recovery_engine": "mineru_popo_v2", "recovery_rule": recovery_rule},
    )
    nodes.append(node)
    return node


def _single_page_spatial_anchor(node: ProcessingNode) -> SpatialAnchor | None:
    if len(node.source_unit_ids) != 1:
        return None
    source_unit_id = node.source_unit_ids[0]
    anchors = tuple(
        anchor
        for anchor in node.anchors
        if isinstance(anchor, SpatialAnchor) and anchor.source_unit_id == source_unit_id
    )
    return anchors[0] if len(anchors) == 1 else None


def _caption_visual_kinds(node: ProcessingNode, observation_by_id: dict[str, object]) -> frozenset[ProcessingNodeKind]:
    observed_kind = ""
    if node.observation_ids:
        observation = observation_by_id.get(node.observation_ids[0])
        observed_kind = _kind(getattr(observation, "observed_kind", "")) if observation is not None else ""
    if observed_kind in _FIGURE_CAPTION_KINDS:
        return frozenset({ProcessingNodeKind.FIGURE})
    if observed_kind in _TABLE_CAPTION_KINDS:
        return frozenset({ProcessingNodeKind.TABLE})
    return frozenset({ProcessingNodeKind.FIGURE, ProcessingNodeKind.TABLE})


def _caption_visual_metrics(caption: SpatialAnchor, visual: SpatialAnchor) -> dict[str, float] | None:
    if caption.source_unit_id != visual.source_unit_id:
        return None
    if caption.bottom < visual.top:
        vertical_gap = visual.top - caption.bottom
    elif visual.bottom < caption.top:
        vertical_gap = caption.top - visual.bottom
    else:
        vertical_gap = 0.0
    if vertical_gap > _CAPTION_VISUAL_MAX_VERTICAL_GAP:
        return None

    overlap = max(0.0, min(caption.right, visual.right) - max(caption.left, visual.left))
    smaller_width = min(caption.right - caption.left, visual.right - visual.left)
    horizontal_overlap = overlap / smaller_width if smaller_width > 0 else 0.0
    caption_center = (caption.left + caption.right) / 2
    visual_center = (visual.left + visual.right) / 2
    center_delta = abs(caption_center - visual_center)
    if horizontal_overlap < _CAPTION_VISUAL_MIN_HORIZONTAL_OVERLAP and center_delta > _CAPTION_VISUAL_MAX_CENTER_DELTA:
        return None

    score = vertical_gap + (center_delta * 0.35) + ((1.0 - min(1.0, horizontal_overlap)) * 0.05)
    return {
        "score": score,
        "vertical_gap": vertical_gap,
        "horizontal_overlap": horizontal_overlap,
        "center_delta": center_delta,
    }


def _with_caption_parent(node: ProcessingNode, parent: ProcessingNode, metrics: dict[str, float]) -> ProcessingNode:
    metadata = dict(node.metadata or {})
    metadata.update(
        {
            "caption_association_policy": _CAPTION_VISUAL_POLICY,
            "caption_association_recovered": True,
            "caption_association_original_parent_id": node.parent_id,
            "caption_association_target_kind": parent.kind.value,
            "caption_association_vertical_gap": round(metrics["vertical_gap"], 6),
            "caption_association_horizontal_overlap": round(metrics["horizontal_overlap"], 6),
            "caption_association_center_delta": round(metrics["center_delta"], 6),
        }
    )
    return ProcessingNode(
        node_id=node.node_id,
        kind=node.kind,
        order=node.order,
        source_unit_ids=node.source_unit_ids,
        parent_id=parent.node_id,
        text=node.text,
        heading_level=node.heading_level,
        anchors=node.anchors,
        observation_ids=node.observation_ids,
        evidence_ids=node.evidence_ids,
        recovery_state=node.recovery_state,
        metadata=metadata,
    )


def _repair_caption_visual_associations(nodes: list[ProcessingNode], observations: tuple) -> list[ProcessingNode]:
    if not nodes:
        return nodes
    observation_by_id = {item.observation_id: item for item in observations}
    by_id = {node.node_id: node for node in nodes}
    visual_nodes = tuple(node for node in nodes if node.kind in {ProcessingNodeKind.FIGURE, ProcessingNodeKind.TABLE})
    repaired = list(nodes)

    for index, caption in enumerate(nodes):
        if caption.kind is not ProcessingNodeKind.CAPTION:
            continue
        caption_anchor = _single_page_spatial_anchor(caption)
        if caption_anchor is None:
            continue

        allowed_kinds = _caption_visual_kinds(caption, observation_by_id)
        current_parent = by_id.get(caption.parent_id or "")
        if current_parent is not None and current_parent.kind in allowed_kinds:
            if current_parent.source_unit_ids == caption.source_unit_ids:
                continue

        candidates: list[tuple[float, ProcessingNode, dict[str, float]]] = []
        for visual in visual_nodes:
            if visual.kind not in allowed_kinds or visual.source_unit_ids != caption.source_unit_ids:
                continue
            visual_anchor = _single_page_spatial_anchor(visual)
            if visual_anchor is None:
                continue
            metrics = _caption_visual_metrics(caption_anchor, visual_anchor)
            if metrics is None:
                continue
            candidates.append((metrics["score"], visual, metrics))

        candidates.sort(key=lambda item: (item[0], item[1].order, item[1].node_id))
        if not candidates:
            continue
        if len(candidates) > 1 and candidates[1][0] - candidates[0][0] < _CAPTION_VISUAL_AMBIGUITY_MARGIN:
            continue

        _, parent, metrics = candidates[0]
        repaired[index] = _with_caption_parent(caption, parent, metrics)
        by_id[caption.node_id] = repaired[index]

    return repaired


def _looks_like_toc_block(text: str) -> bool:
    if not text:
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return len(lines) >= 2 and sum(bool(_TOC_LINE_RE.match(line)) for line in lines) >= 2


def _toc_items(text: str) -> tuple[str, ...]:
    lines = tuple(line.strip() for line in text.splitlines() if line.strip())
    return lines or ((text.strip(),) if text.strip() else ())


def _append_toc(nodes: list[ProcessingNode], observation, text: str, heading_stack: dict[int, str]) -> str:
    list_node = _node_from_observations(
        nodes,
        ProcessingNodeKind.LIST,
        (observation,),
        parent_id=_deepest_heading(heading_stack),
        text=None,
        recovery_rule="mineru_popo_toc_list",
    )
    for index, item_text in enumerate(_toc_items(text)):
        node = ProcessingNode(
            node_id=f"mineru-node:{observation.observation_id}:toc:{index:04d}",
            kind=ProcessingNodeKind.LIST_ITEM,
            order=len(nodes),
            source_unit_ids=(observation.source_unit_id,),
            parent_id=list_node.node_id,
            text=item_text,
            anchors=observation.anchors,
            observation_ids=(observation.observation_id,),
            evidence_ids=observation.evidence_ids,
            metadata={"recovery_engine": "mineru_popo_v2", "recovery_rule": "mineru_popo_toc_item"},
        )
        nodes.append(node)
    return list_node.node_id


def _spatial_anchor(observation) -> SpatialAnchor | None:
    return next((anchor for anchor in observation.anchors if isinstance(anchor, SpatialAnchor)), None)


def _can_continue_previous_paragraph(nodes: list[ProcessingNode], observation, unit_order: dict[str, int]) -> bool:
    if not nodes or nodes[-1].kind is not ProcessingNodeKind.PARAGRAPH:
        return False
    previous = nodes[-1]
    if not previous.text or _SENTENCE_END_RE.search(previous.text):
        return False
    previous_unit = previous.source_unit_ids[-1]
    current_unit = observation.source_unit_id
    if unit_order.get(current_unit) != unit_order.get(previous_unit, -2) + 1:
        return False
    previous_anchor = next((anchor for anchor in reversed(previous.anchors) if isinstance(anchor, SpatialAnchor)), None)
    current_anchor = _spatial_anchor(observation)
    return bool(previous_anchor and current_anchor and previous_anchor.bottom >= 0.82 and current_anchor.top <= 0.18)


def _merge_into_previous_paragraph(nodes: list[ProcessingNode], observation) -> None:
    previous = nodes[-1]
    left = (previous.text or "").rstrip()
    right = (observation.text or "").lstrip()
    separator = "" if _cjk_join(left, right) else " "
    nodes[-1] = ProcessingNode(
        node_id=previous.node_id,
        kind=previous.kind,
        order=previous.order,
        source_unit_ids=tuple(dict.fromkeys((*previous.source_unit_ids, observation.source_unit_id))),
        parent_id=previous.parent_id,
        text=f"{left}{separator}{right}",
        anchors=(*previous.anchors, *observation.anchors),
        observation_ids=(*previous.observation_ids, observation.observation_id),
        evidence_ids=tuple(dict.fromkeys((*previous.evidence_ids, *observation.evidence_ids))),
        metadata={"recovery_engine": "mineru_popo_v2", "recovery_rule": "mineru_popo_cross_page_paragraph"},
    )


def _cjk_join(left: str, right: str) -> bool:
    if not left or not right:
        return True
    return bool(re.search(r"[\u3000-\u303f\u3400-\u9fff，。！？；：、——…]$", left) or re.match(r"^[\u3000-\u303f\u3400-\u9fff，。！？；：、——…]", right))


__all__ = ["recover_pdf_observations_via_mineru_popo"]
