from __future__ import annotations

import ast
import inspect
import textwrap

from app.processing import pdf_provider_sharding as sharding


def _assigns_started(statement: ast.stmt) -> bool:
    for node in ast.walk(statement):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets.extend(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets.append(node.target)
            else:
                targets.append(node.target)
            if any(
                isinstance(target, ast.Name) and target.id == "started"
                for target in targets
            ):
                return True
    return False


def test_shard_elapsed_clock_starts_after_semaphore_admission() -> None:
    """Queued time must not inflate per-shard elapsed Provider diagnostics."""
    source = textwrap.dedent(inspect.getsource(sharding.run_provider_transport_shards))
    tree = ast.parse(source)
    runner = tree.body[0]
    assert isinstance(runner, ast.AsyncFunctionDef)

    run_one = next(
        node
        for node in runner.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_one"
    )
    semaphore_index = next(
        index
        for index, statement in enumerate(run_one.body)
        if isinstance(statement, ast.AsyncWith)
    )
    semaphore = run_one.body[semaphore_index]
    assert isinstance(semaphore, ast.AsyncWith)

    assert not any(
        _assigns_started(statement)
        for statement in run_one.body[:semaphore_index]
    )
    assert semaphore.body, "semaphore block must contain the admitted shard work"
    assert _assigns_started(semaphore.body[0])
