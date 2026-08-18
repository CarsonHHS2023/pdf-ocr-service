from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.processing import pdf_crop_opencv_semantic_consensus_compat as consensus
from app.processing import pdf_crop_opencv_semantic_gate_compat as gate


def _judgment(*, decision: str, confidence: float = 0.96, content_preserved: bool = True):
    return {
        "decision": decision,
        "confidence": confidence,
        "background_improved": True,
        "content_preserved": content_preserved,
        "unexpected_added_content": False,
        "unexpected_removed_content": decision == "reject",
        "geometry_changed": False,
        "color_or_fill_changed": False,
        "expected_cleanup_changes": [],
        "suspected_content_changes": [],
        "reason": decision,
    }


def _runner(monkeypatch, results, budgets=(True, True)):
    remaining = iter(results)
    budget_remaining = iter(budgets)
    calls = {"judge": 0, "budget": 0}

    def original(self, **kwargs):
        calls["judge"] += 1
        value = next(remaining)
        if isinstance(value, BaseException):
            raise value
        return value

    def consume():
        calls["budget"] += 1
        ok = next(budget_remaining)
        return ok, {"judge_calls": calls["budget"] + 1, "max_judge_calls": 6}

    monkeypatch.setattr(consensus, "_consume_confirmation_budget", consume)
    result = consensus._run_consensus(SimpleNamespace(), original)
    return result, calls


def test_clean_accept_is_single_call_fast_path(monkeypatch) -> None:
    result, calls = _runner(monkeypatch, [_judgment(decision="accept")])
    assert gate._semantic_accepts(result)[0] is True
    assert calls == {"judge": 1, "budget": 0}
    assert result["consensus"]["status"] == "single_accept_fast_path"
    assert result["consensus"]["vote_count"] == 1


def test_adverse_result_requires_second_adverse_confirmation(monkeypatch) -> None:
    result, calls = _runner(
        monkeypatch,
        [_judgment(decision="reject"), _judgment(decision="reject", confidence=0.93)],
    )
    assert gate._semantic_accepts(result)[0] is False
    assert calls == {"judge": 2, "budget": 1}
    assert result["consensus"]["status"] == "confirmed_adverse"
    assert [vote["accepted"] for vote in result["consensus"]["votes"]] == [False, False]


def test_split_votes_use_third_vote_and_majority_can_accept(monkeypatch) -> None:
    result, calls = _runner(
        monkeypatch,
        [
            _judgment(decision="reject", confidence=0.90),
            _judgment(decision="accept", confidence=0.95),
            _judgment(decision="accept", confidence=0.97),
        ],
    )
    assert gate._semantic_accepts(result)[0] is True
    assert calls == {"judge": 3, "budget": 2}
    assert result["consensus"]["status"] == "majority_accept"
    assert result["consensus"]["final_accepted"] is True


def test_split_votes_use_third_vote_and_majority_can_reject(monkeypatch) -> None:
    result, calls = _runner(
        monkeypatch,
        [
            _judgment(decision="reject", confidence=0.92),
            _judgment(decision="accept", confidence=0.96),
            _judgment(decision="reject", confidence=0.94),
        ],
    )
    assert gate._semantic_accepts(result)[0] is False
    assert calls == {"judge": 3, "budget": 2}
    assert result["consensus"]["status"] == "majority_adverse"
    assert result["consensus"]["final_accepted"] is False


def test_split_without_tiebreak_budget_fails_open_to_adverse(monkeypatch) -> None:
    result, calls = _runner(
        monkeypatch,
        [_judgment(decision="reject"), _judgment(decision="accept")],
        budgets=(True, False),
    )
    assert gate._semantic_accepts(result)[0] is False
    assert calls == {"judge": 2, "budget": 2}
    assert result["consensus"]["status"] == "split_budget_exhausted_fail_open"


def test_confirmation_provider_failure_keeps_first_adverse(monkeypatch) -> None:
    result, calls = _runner(
        monkeypatch,
        [_judgment(decision="reject"), RuntimeError("synthetic provider failure")],
    )
    assert gate._semantic_accepts(result)[0] is False
    assert calls == {"judge": 2, "budget": 1}
    assert result["consensus"]["status"] == "adverse_confirmation_provider_failed"
    assert result["consensus"]["additional_call_error_type"] == "RuntimeError"
    assert "synthetic provider failure" not in str(result)


def test_low_confidence_accept_is_treated_as_adverse_for_confirmation(monkeypatch) -> None:
    low = _judgment(decision="accept", confidence=0.89)
    confirmed = _judgment(decision="accept", confidence=0.88)
    result, calls = _runner(monkeypatch, [low, confirmed])
    assert gate._semantic_accepts(result)[0] is False
    assert calls == {"judge": 2, "budget": 1}
    assert result["consensus"]["status"] == "confirmed_adverse"


def test_consensus_does_not_change_acceptance_threshold(monkeypatch) -> None:
    monkeypatch.setenv("PDF_CROP_OPENCV_SEMANTIC_GATE_MIN_CONFIDENCE", "0.90")
    assert gate._semantic_accepts(_judgment(decision="accept", confidence=0.90))[0] is True
    assert gate._semantic_accepts(_judgment(decision="accept", confidence=0.899))[0] is False
