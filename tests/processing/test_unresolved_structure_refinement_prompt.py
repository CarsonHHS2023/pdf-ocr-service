from __future__ import annotations

from app.processing import openai_structure_refinement_provider as provider


def test_openai_provider_includes_mandatory_unresolved_review_task() -> None:
    instruction = provider._SYSTEM_INSTRUCTION
    marker = "TASK 5 — REQUIRED UNKNOWN/DEGRADED DISPOSITION"

    assert instruction.count(marker) == 1
    assert "Perform exactly five tasks." in instruction
    assert "Every scoped unresolved node must" in instruction
    assert "reclassify it to list_item" in instruction
    assert "also return set_toc_level" in instruction


def test_optional_noop_rule_does_not_apply_to_scoped_unresolved_nodes() -> None:
    instruction = provider._SYSTEM_INSTRUCTION

    assert (
        "The general instruction to return no operation when uncertain applies only to optional"
        in instruction
    )
    assert "nodes outside review_scope.unresolved_candidate_node_ids" in instruction
