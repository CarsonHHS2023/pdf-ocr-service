from __future__ import annotations

import asyncio

import app.main as main


def test_startup_reinstalls_provider_handler_after_uvicorn_logging(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        main,
        "install_refinement_provider_stderr_handler",
        lambda: calls.append("install_handler"),
    )
    monkeypatch.setattr(
        main,
        "validate_and_log_structure_refinement_config",
        lambda _logger: calls.append("validate_config"),
    )
    monkeypatch.setattr(main, "init_db", lambda: calls.append("init_db"))

    asyncio.run(main.startup_event())

    assert calls == ["install_handler", "validate_config", "init_db"]
