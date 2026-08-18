from __future__ import annotations

import ast
from pathlib import Path


TRANSFORMER_ROOT = Path("app/structured_content_v2/transformation")
FORBIDDEN_PREFIXES = (
    "app.database",
    "app.models",
    "app.routers",
    "app.services",
    "app.reader",
    "sqlalchemy",
    "fastapi",
    "modal",
    "requests",
    "httpx",
    "openai",
)


def test_structured_content_v2_transformer_has_no_runtime_or_infrastructure_dependencies() -> None:
    violations: list[str] = []

    for path in sorted(TRANSFORMER_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)

            for module in modules:
                if module.startswith(FORBIDDEN_PREFIXES):
                    violations.append(f"{path}:{getattr(node, 'lineno', '?')} imports {module}")

    assert violations == []
