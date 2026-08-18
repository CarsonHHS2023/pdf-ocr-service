"""Bounded confirmation consensus for adverse GPT-5.6 crop judgments.

The first semantic Judge call keeps the existing acceptance contract unchanged.
A clean ACCEPT remains a one-call fast path. Any adverse/uncertain/low-confidence
or integrity-failing result receives one confirmation vote when document budget
allows. If the two votes disagree, one bounded tie-break vote is requested.

Every additional vote consumes the existing per-document Judge-call budget. No
confidence threshold, catastrophic threshold, prompt, model, or pixel-producing
stage is changed. If confirmation cannot complete because budget is exhausted or
a later provider call fails, the candidate remains rejected/fail-open to the
Original/geometry baseline.
"""
from __future__ import annotations

from dataclasses import replace
import threading
from typing import Any, Callable, Mapping

from app.processing import pdf_crop_opencv_semantic_gate_compat as gate
from app.processing import pdf_opencv_modal_bridge as opencv_bridge

_POLICY_VERSION = "opencv_semantic_adverse_confirmation_consensus_v1"
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False


def _confidence(result: Mapping[str, Any]) -> float | None:
    value = result.get("confidence")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _vote(result: Mapping[str, Any]) -> dict[str, object]:
    accepted, safe_reason = gate._semantic_accepts(result)
    return {
        "decision": result.get("decision"),
        "confidence": _confidence(result),
        "accepted": bool(accepted),
        "safe_reason": safe_reason,
    }


def _with_consensus(
    result: Mapping[str, Any],
    *,
    votes: list[dict[str, object]],
    status: str,
    final_accepted: bool,
    additional_call_error_type: str | None = None,
) -> dict[str, Any]:
    output = dict(result)
    consensus: dict[str, object] = {
        "policy_version": _POLICY_VERSION,
        "strategy": "accept_fast_path_adverse_confirm_split_tiebreak",
        "status": status,
        "vote_count": len(votes),
        "votes": [dict(item) for item in votes],
        "final_accepted": bool(final_accepted),
    }
    if additional_call_error_type is not None:
        consensus["additional_call_error_type"] = additional_call_error_type
    output["consensus"] = consensus
    return output


def _choose_result(
    results: list[Mapping[str, Any]],
    accepts: list[bool],
    *,
    accepted: bool,
) -> Mapping[str, Any]:
    eligible = [
        result
        for result, vote_accepted in zip(results, accepts, strict=True)
        if vote_accepted is accepted
    ]
    if not eligible:
        return results[0]
    return max(
        eligible,
        key=lambda item: _confidence(item) if _confidence(item) is not None else -1.0,
    )


def _consume_confirmation_budget() -> tuple[bool, dict[str, int]]:
    return gate._budget_consume()


def _run_consensus(
    self,
    original: Callable[..., Mapping[str, Any]],
    **kwargs,
) -> dict[str, Any]:
    first = dict(original(self, **kwargs))
    first_accepted, _ = gate._semantic_accepts(first)
    results: list[Mapping[str, Any]] = [first]
    accepts = [bool(first_accepted)]
    votes = [_vote(first)]

    if first_accepted:
        return _with_consensus(
            first,
            votes=votes,
            status="single_accept_fast_path",
            final_accepted=True,
        )

    budget_ok, _ = _consume_confirmation_budget()
    if not budget_ok:
        return _with_consensus(
            first,
            votes=votes,
            status="adverse_unconfirmed_budget_exhausted",
            final_accepted=False,
        )

    try:
        second = dict(original(self, **kwargs))
    except Exception as exc:
        return _with_consensus(
            first,
            votes=votes,
            status="adverse_confirmation_provider_failed",
            final_accepted=False,
            additional_call_error_type=type(exc).__name__,
        )
    second_accepted, _ = gate._semantic_accepts(second)
    results.append(second)
    accepts.append(bool(second_accepted))
    votes.append(_vote(second))

    if not second_accepted:
        chosen = _choose_result(results, accepts, accepted=False)
        return _with_consensus(
            chosen,
            votes=votes,
            status="confirmed_adverse",
            final_accepted=False,
        )

    # One adverse and one accept: request one bounded tie-break vote.
    budget_ok, _ = _consume_confirmation_budget()
    if not budget_ok:
        # A split without a tie-break is intentionally conservative: do not
        # authorize a modified candidate on incomplete consensus.
        chosen = _choose_result(results, accepts, accepted=False)
        return _with_consensus(
            chosen,
            votes=votes,
            status="split_budget_exhausted_fail_open",
            final_accepted=False,
        )

    try:
        third = dict(original(self, **kwargs))
    except Exception as exc:
        chosen = _choose_result(results, accepts, accepted=False)
        return _with_consensus(
            chosen,
            votes=votes,
            status="split_tiebreak_provider_failed_fail_open",
            final_accepted=False,
            additional_call_error_type=type(exc).__name__,
        )
    third_accepted, _ = gate._semantic_accepts(third)
    results.append(third)
    accepts.append(bool(third_accepted))
    votes.append(_vote(third))

    final_accepted = sum(1 for value in accepts if value) >= 2
    chosen = _choose_result(results, accepts, accepted=final_accepted)
    return _with_consensus(
        chosen,
        votes=votes,
        status="majority_accept" if final_accepted else "majority_adverse",
        final_accepted=final_accepted,
    )


def _install_judge_wrapper() -> None:
    original = gate.OpenAIOpenCVCropJudge.judge
    if getattr(original, "_opencv_semantic_consensus", False):
        return

    def judge_with_consensus(self, **kwargs):
        return _run_consensus(self, original, **kwargs)

    judge_with_consensus._opencv_semantic_consensus = True  # type: ignore[attr-defined]
    gate.OpenAIOpenCVCropJudge.judge = judge_with_consensus


def _install_budget_metadata_refresh() -> None:
    original = opencv_bridge.process_visual_crop_v4
    if getattr(original, "_opencv_semantic_consensus_budget_refresh", False):
        return

    def process_with_consensus_budget_refresh(*args, **kwargs):
        output, metadata = original(*args, **kwargs)
        if not isinstance(metadata, dict):
            return output, metadata
        state = gate._CURRENT_BUDGET.get()
        if not isinstance(state, dict):
            return output, metadata
        maximum = gate._env_int(
            "PDF_CROP_OPENCV_SEMANTIC_GATE_MAX_JUDGE_CALLS",
            gate._DEFAULT_MAX_JUDGE_CALLS,
            minimum=0,
            maximum=100,
        )
        current_budget = {
            "judge_calls": int(state.get("judge_calls", 0)),
            "max_judge_calls": maximum,
        }

        updated = dict(metadata)
        semantic = updated.get("semantic_gate")
        if isinstance(semantic, Mapping):
            semantic_updated = dict(semantic)
            judgment = semantic_updated.get("judgment")
            if isinstance(judgment, Mapping) and isinstance(
                judgment.get("consensus"), Mapping
            ):
                semantic_updated["budget"] = current_budget
                updated["semantic_gate"] = semantic_updated
                background = updated.get("background")
                if isinstance(background, Mapping):
                    background_updated = dict(background)
                    background_updated["semantic_gate"] = dict(semantic_updated)
                    updated["background"] = background_updated
        return output, updated

    process_with_consensus_budget_refresh._opencv_semantic_consensus_budget_refresh = True  # type: ignore[attr-defined]
    opencv_bridge.process_visual_crop_v4 = process_with_consensus_budget_refresh


def install_pdf_crop_opencv_semantic_consensus_compat() -> None:
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        _install_judge_wrapper()
        _install_budget_metadata_refresh()
        _INSTALLED = True


__all__ = [
    "install_pdf_crop_opencv_semantic_consensus_compat",
]
