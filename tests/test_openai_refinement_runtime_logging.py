from __future__ import annotations

import logging

from app.processing.openai_batched_structure_refinement import _log_refinement_event


def test_refinement_event_is_emitted_to_stderr_and_uvicorn_logger(capsys, caplog) -> None:
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        _log_refinement_event(
            "PDF_STRUCTURE_REFINEMENT_DOCUMENT_METRICS",
            {
                "model_id": "gpt-5.2",
                "operation_count": 3,
                "outcome": "succeeded",
            },
        )

    stderr = capsys.readouterr().err
    expected = (
        "PDF_STRUCTURE_REFINEMENT_DOCUMENT_METRICS "
        "model_id=gpt-5.2 operation_count=3 outcome=succeeded"
    )
    assert expected in stderr
    assert expected in caplog.text
    assert "api_key" not in stderr.lower()
    assert "authorization" not in stderr.lower()
