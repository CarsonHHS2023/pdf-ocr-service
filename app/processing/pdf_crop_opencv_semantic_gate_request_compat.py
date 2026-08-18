"""Harden the outbound GPT-5.6 Judge request and faint-structure evidence.

The Chat Completions image detail contract uses high/low/auto. The first semantic
gate revision used ``original``. This layer rewrites every Judge image input to
``high`` so faint lines and tiny punctuation receive high-resolution review, and
it validates HTTPS at the final call boundary so even directly constructed Judge
instances cannot send bearer credentials to a non-HTTPS endpoint.

It also raises recall only for *evidence selection*: faint local structural
residual changes are eligible for ROI review even when neither side is dark
foreground. This does not protect, composite, select, or alter any output pixel.
Finally, an ACCEPT carrying any suspected content change is treated as internally
inconsistent and fails open.
"""
from __future__ import annotations

from dataclasses import replace
import threading
from typing import Any, Mapping

import cv2
import numpy as np

from app.processing import pdf_crop_opencv_semantic_gate_compat as gate
from app.processing import pdf_crop_opencv_semantic_gate_hardening_compat as hardening
from app.processing.pdf_crop_opencv_semantic_gate_hardening_compat import (
    _https_base_url,
)

_INSTALL_LOCK = threading.Lock()
_INSTALLED = False


def _force_high_image_detail(payload: Mapping[str, Any]) -> None:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "image_url":
                continue
            image_url = part.get("image_url")
            if isinstance(image_url, dict):
                image_url["detail"] = "high"


def _faint_sensitive_structure_masks(
    before: np.ndarray,
    after: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Return high-recall ROI hints for meaningful dark *or faint* structure.

    The returned masks are only intersected with actual changed pixels later and
    are used to choose what GPT-5.6 sees. A false positive here costs an ROI slot;
    it can never change document pixels or authorize a candidate by itself.
    """
    before_gray = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY).astype(np.float32)
    after_gray = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY).astype(np.float32)
    height, width = before_gray.shape
    sigma = max(4.0, min(height, width) / 35.0)
    before_local = cv2.GaussianBlur(
        before_gray,
        (0, 0),
        sigmaX=sigma,
        sigmaY=sigma,
        borderType=cv2.BORDER_REPLICATE,
    )
    after_local = cv2.GaussianBlur(
        after_gray,
        (0, 0),
        sigmaX=sigma,
        sigmaY=sigma,
        borderType=cv2.BORDER_REPLICATE,
    )

    before_residual = before_local - before_gray
    after_residual = after_local - after_gray
    before_strong = (before_residual >= 14.0) | (before_gray <= 120.0)
    after_strong = (after_residual >= 14.0) | (after_gray <= 120.0)
    strong_union = before_strong | after_strong
    strong_xor = before_strong ^ after_strong

    before_lab = cv2.cvtColor(before, cv2.COLOR_BGR2LAB).astype(np.float32)
    after_lab = cv2.cvtColor(after, cv2.COLOR_BGR2LAB).astype(np.float32)
    ab_delta = np.sqrt(
        (before_lab[:, :, 1] - after_lab[:, :, 1]) ** 2
        + (before_lab[:, :, 2] - after_lab[:, :, 2]) ** 2
    )
    strong_color_changed = (ab_delta >= 8.0) & strong_union
    priority = strong_xor | strong_color_changed

    # Crucially, do not require a faint feature to have crossed the strong
    # foreground threshold. Uniform paper lightening largely cancels in this
    # local residual; a disappearing faint 1px rule does not.
    faint_residual_changed = np.abs(before_residual - after_residual) >= 7.0
    structural = priority | faint_residual_changed

    # Strong priority evidence may be denoised conservatively. Broader structural
    # evidence must retain 1px lines, so use dilation rather than an opening that
    # would erase them before component extraction.
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    priority = cv2.morphologyEx(
        priority.astype(np.uint8), cv2.MORPH_OPEN, kernel
    ) > 0
    structural = cv2.dilate(
        structural.astype(np.uint8),
        kernel,
        iterations=1,
    ) > 0
    return priority, structural


def _install_semantic_consistency_guard() -> None:
    original = gate._semantic_accepts
    if getattr(original, "_opencv_semantic_consistency_guard", False):
        return

    def semantic_accepts_consistent(result: Mapping[str, Any]) -> tuple[bool, str]:
        accepted, reason = original(result)
        if not accepted:
            return accepted, reason
        suspected = result.get("suspected_content_changes")
        if isinstance(suspected, list) and suspected:
            return False, "semantic_gate_suspected_content_changes"
        return True, reason

    semantic_accepts_consistent._opencv_semantic_consistency_guard = True  # type: ignore[attr-defined]
    gate._semantic_accepts = semantic_accepts_consistent


def install_pdf_crop_opencv_semantic_gate_request_compat() -> None:
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return
        original = gate.OpenAIOpenCVCropJudge.judge
        if not getattr(original, "_opencv_semantic_gate_request_hardened", False):

            def judge_with_request_hardening(self, **kwargs):
                _https_base_url(self.base_url)
                original_post = self.json_post

                def post_with_high_detail(url, headers, payload, timeout_seconds):
                    _force_high_image_detail(payload)
                    return original_post(url, headers, payload, timeout_seconds)

                reviewer = replace(self, json_post=post_with_high_detail)
                return original(reviewer, **kwargs)

            judge_with_request_hardening._opencv_semantic_gate_request_hardened = True  # type: ignore[attr-defined]
            gate.OpenAIOpenCVCropJudge.judge = judge_with_request_hardening

        hardening._foreground_change_masks = _faint_sensitive_structure_masks
        if "Field semantics: color_or_fill_changed" not in gate._GATE_SYSTEM_PROMPT:
            gate._GATE_SYSTEM_PROMPT += (
                "\n\nField semantics: color_or_fill_changed means a meaningful intentional "
                "document color, shaded cell, fill, stamp, logo, or graphic color changed. "
                "Do not set it merely because gray/aged paper background was normalized "
                "toward clean neutral paper. If suspected_content_changes is non-empty, "
                "do not return ACCEPT."
            )
        _install_semantic_consistency_guard()
        _INSTALLED = True


__all__ = ["install_pdf_crop_opencv_semantic_gate_request_compat"]
