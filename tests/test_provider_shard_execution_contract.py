from __future__ import annotations

import ast
import inspect
import textwrap

from app.processing import pdf_provider_sharding as sharding


def _attribute_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Attribute):
        return None
    parts: list[str] = [node.attr]
    value = node.value
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    return ".".join(reversed(parts))


def test_atlas_transport_shards_have_no_internal_fanout() -> None:
    """Modal owns compute fanout; Atlas must submit transport shards sequentially."""
    source = textwrap.dedent(inspect.getsource(sharding.run_provider_transport_shards))
    tree = ast.parse(source)
    runner = tree.body[0]
    assert isinstance(runner, ast.AsyncFunctionDef)

    called_attributes = {
        name
        for node in ast.walk(runner)
        if isinstance(node, ast.Call)
        for name in [_attribute_name(node.func)]
        if name is not None
    }
    assert "asyncio.Semaphore" not in called_attributes
    assert "asyncio.create_task" not in called_attributes
    assert "asyncio.gather" not in called_attributes

    shard_loops = [
        node
        for node in runner.body
        if isinstance(node, ast.For)
        and isinstance(node.target, ast.Name)
        and node.target.id == "plan"
        and isinstance(node.iter, ast.Name)
        and node.iter.id == "plans"
    ]
    assert len(shard_loops) == 1

    process_awaits = [
        node
        for node in ast.walk(shard_loops[0])
        if isinstance(node, ast.Await)
        and isinstance(node.value, ast.Call)
        and _attribute_name(node.value.func) == "service.process"
    ]
    assert len(process_awaits) == 1
    assert sharding.PROVIDER_TRANSPORT_SHARD_EXECUTION_MODE == "sequential"
    assert not hasattr(sharding, "PROVIDER_TRANSPORT_SHARD_MAX_CONCURRENCY")
