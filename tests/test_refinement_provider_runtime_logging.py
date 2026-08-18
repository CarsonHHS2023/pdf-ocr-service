from __future__ import annotations

import logging

from app.processing import install_refinement_provider_stderr_handler


def test_provider_events_are_mirrored_to_stderr_without_secrets(capsys) -> None:
    logger = logging.getLogger("uvicorn.error")
    original_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        install_refinement_provider_stderr_handler()
        install_refinement_provider_stderr_handler()

        logger.info(
            "PDF_STRUCTURE_REFINEMENT_PROVIDER_FAILURE "
            "attempt=1 error_type=StructureRefinementProviderError "
            "max_attempts=3 retryable=False status_code=400 will_retry=False"
        )
        logger.info("UNRELATED_RUNTIME_EVENT api_key=must-not-be-mirrored")
    finally:
        logger.setLevel(original_level)

    stderr = capsys.readouterr().err
    assert stderr.count("PDF_STRUCTURE_REFINEMENT_PROVIDER_FAILURE") == 1
    assert "status_code=400" in stderr
    assert "retryable=False" in stderr
    assert "UNRELATED_RUNTIME_EVENT" not in stderr
    assert "api_key" not in stderr
    assert "Authorization" not in stderr
