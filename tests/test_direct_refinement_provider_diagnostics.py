from __future__ import annotations

from app.processing.refinement_provider_diagnostics import emit_refinement_provider_event


def test_provider_event_is_flushed_to_stderr_without_secrets(capsys) -> None:
    emit_refinement_provider_event(
        "PDF_STRUCTURE_REFINEMENT_PROVIDER_FAILURE",
        {
            "attempt": 1,
            "max_attempts": 3,
            "retryable": False,
            "status_code": 400,
            "will_retry": False,
        },
    )

    stderr = capsys.readouterr().err
    assert "PDF_STRUCTURE_REFINEMENT_PROVIDER_FAILURE" in stderr
    assert "status_code=400" in stderr
    assert "retryable=False" in stderr
    assert "api_key" not in stderr
    assert "Authorization" not in stderr
