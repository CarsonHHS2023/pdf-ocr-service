"""Local protocol design controls; no producer, collector or database connection.

Executes only AST-selected pure sanitizer/JSON functions from pinned repo source.
The lock-based gate is a synthetic model, not application lifecycle integration.
"""
from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import platform
from threading import Barrier, Lock
from typing import Any, Mapping, Sequence
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[2]
MAX_SCOPES = 8
MAX_NS = 2**53 - 1
COMMON = {
    "contract_version": "atlas.s0.preprocessing-worker-cpu.v1",
    "measurement_scope": "worker_thread_only",
    "method": "sync_preprocessing_worker_thread_cpu_v1",
    "run_scope_id": "cpu_" + "a" * 32,
    "source_scope_id": "source_" + "b" * 64,
    "backend_revision": "c" * 40,
}


def load_pure_sanitizer():
    functions = {"_safe_key", "_safe_value", "_encoded_payload_size",
                 "_mark_truncated", "sanitize_processing_event_payload"}
    constants = {"MAX_EVENT_PAYLOAD_BYTES", "MAX_PAYLOAD_FIELDS", "MAX_NESTED_FIELDS",
                 "MAX_LIST_ITEMS", "MAX_STRING_CHARS", "MAX_NESTING_DEPTH", "_DROP",
                 "_SENSITIVE_KEY_PARTS", "_SENSITIVE_EXACT_KEYS", "_SENSITIVE_STRING_PREFIXES"}
    source = ROOT / "app/processing/processing_events.py"
    nodes = []
    found = set()
    for node in ast.parse(source.read_text()).body:
        if isinstance(node, ast.FunctionDef) and node.name in functions:
            nodes.append(node)
            found.add(node.name)
        elif (isinstance(node, ast.Assign) and len(node.targets) == 1
              and isinstance(node.targets[0], ast.Name) and node.targets[0].id in constants):
            nodes.append(node)
            found.add(node.targets[0].id)
    assert found == functions | constants, "sanitizer source contract changed"
    encoder = [node for node in ast.parse((ROOT / "app/models.py").read_text()).body
               if isinstance(node, ast.FunctionDef) and node.name == "encode_json_text"]
    assert len(encoder) == 1
    namespace = {"Any": Any, "Mapping": Mapping, "Sequence": Sequence,
                 "math": math, "json": json}
    exec(compile(ast.Module(body=encoder + nodes, type_ignores=[]),
                 "<isolated-repository-sanitizer>", "exec"), namespace)
    return namespace


def payloads(count=1):
    if type(count) is not int or not 0 <= count <= MAX_SCOPES:
        raise ValueError("synthetic scope bound")
    rows = [{**COMMON, "ordinal": 0}]
    for index in range(1, count + 1):
        scope = {**COMMON, "scope_index": index, "scope_id": f"pcpu_{index:032x}"}
        rows.append({**scope, "ordinal": 2 * index - 1})
        rows.append({**scope, "ordinal": 2 * index,
                     "operation_outcome": "completed", "clock_status": "measured",
                     "cpu_delta_ns": MAX_NS, "clock_resolution_ns": 1_000_000_000,
                     "reason": "none"})
    rows.append({**COMMON, "ordinal": 2 * count + 1, "scope_count": count,
                 "complete": True, "logical_outcome": "completed", "issue": "none"})
    return rows


def bounded_total(values):
    if not values or any(type(v) is not int or not 0 <= v <= MAX_NS for v in values):
        return None
    total = sum(values)
    return total if total <= MAX_NS else None


class Gate:
    """Model only: seal + all admitted settlements -> one immutable snapshot."""

    def __init__(self, *, started=True):
        self.lock = Lock()
        self.complete = started
        self.closed = False
        self.claimed = False
        self.settled = []
        self.outcome = None

    def admit(self, *, persisted=True):
        with self.lock:
            if self.closed:
                raise ValueError("model forbids admission after dispatch seal")
            if len(self.settled) == MAX_SCOPES:
                self.complete = False
                return None
            self.complete &= persisted
            self.settled.append(False)
            return len(self.settled) - 1

    def _claim_locked(self):
        if self.closed and all(self.settled) and not self.claimed:
            self.claimed = True
            return len(self.settled), self.complete, self.outcome
        return None

    def finish(self, index):
        with self.lock:
            self.settled[index] = True
            return self._claim_locked()

    def seal(self, outcome):
        with self.lock:
            if not self.closed:
                self.closed = True
                self.outcome = outcome
            return self._claim_locked()


class ProtocolShape(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pure = load_pure_sanitizer()

    def test_flat_payloads_fit_and_survive_actual_sanitizer(self):
        sanitize = self.pure["sanitize_processing_event_payload"]
        encode = self.pure["encode_json_text"]
        for count in (0, 1, MAX_SCOPES):
            rows = payloads(count)
            self.assertEqual(len(rows), 2 + 2 * count)
            self.assertEqual([p["ordinal"] for p in rows], list(range(len(rows))))
            for row in rows:
                self.assertEqual(sanitize(row), row)
                self.assertLessEqual(len(row), 32)
                self.assertLessEqual(len(encode(row).encode("utf-8")), 8192)

    def test_nonmeasurement_terminal_variants_remain_bounded(self):
        for outcome, status, reason in (
            ("failed", "unavailable", "clock_unavailable"),
            ("not_started", "not_started", "pre_delegate_failure"),
            ("not_started", "not_started", "submit_failed"),
            ("not_started", "not_started", "cancelled_before_entry"),
        ):
            row = payloads()[2]
            row.update(operation_outcome=outcome, clock_status=status, reason=reason,
                       cpu_delta_ns=None, clock_resolution_ns=None)
            self.assertEqual(self.pure["sanitize_processing_event_payload"](row), row)

    def test_list_and_string_truncation_are_detectable_by_equality(self):
        sanitize = self.pure["sanitize_processing_event_payload"]
        for row in ({"items": list(range(13))}, {"label": "x" * 257}):
            self.assertNotEqual(sanitize(row), row)

    def test_sanitizer_alone_is_not_a_strict_privacy_schema(self):
        row = {"filename": "synthetic-private-name", "path": "synthetic/local/name"}
        self.assertEqual(self.pure["sanitize_processing_event_payload"](row), row)
        # An exact field allowlist is necessary even when equality passes.
        self.assertFalse(set(row) <= set(COMMON))

    def test_utf8_byte_budget_not_character_budget(self):
        row = {f"field_{index:02}": "\u754c" * 256 for index in range(32)}
        encode = self.pure["encode_json_text"]
        self.assertGreater(len(encode(row).encode("utf-8")), 8192)
        cleaned = self.pure["sanitize_processing_event_payload"](row)
        self.assertNotEqual(cleaned, row)
        self.assertLessEqual(len(encode(cleaned).encode("utf-8")), 8192)

    def test_deterministic_event_primary_keys_are_slot_specific(self):
        def event_id(root, ordinal):
            return uuid.uuid5(uuid.NAMESPACE_OID,
                              f"atlas.s0.preprocessing-worker-cpu.v1:{root}:{ordinal}")

        ids = [event_id(COMMON["run_scope_id"], i) for i in range(18)]
        self.assertEqual(len(set(ids)), 18)
        self.assertEqual(ids[2], event_id(COMMON["run_scope_id"], 2))
        self.assertNotEqual(ids[2], event_id("cpu_" + "d" * 32, 2))
        # This tests key construction, not PostgreSQL uniqueness/rollback.

    def test_no_entry_invalid_or_overflow_total_is_not_zero(self):
        self.assertEqual(bounded_total([0]), 0)
        self.assertEqual(bounded_total([10, 20]), 30)
        for values in ([], [None], [True], [-1], [1.0], [MAX_NS + 1], [MAX_NS, 1]):
            with self.subTest(values=values):
                self.assertIsNone(bounded_total(values))


class LifecycleModel(unittest.TestCase):
    def test_cancelled_dispatch_waits_for_worker_settlement(self):
        gate = Gate()
        slot = gate.admit()
        self.assertIsNone(gate.seal("cancelled"))
        self.assertEqual(gate.finish(slot), (1, True, "cancelled"))
        self.assertIsNone(gate.finish(slot))

    def test_worker_first_waits_for_dispatch_seal(self):
        gate = Gate()
        slot = gate.admit()
        self.assertIsNone(gate.finish(slot))
        self.assertEqual(gate.seal("completed"), (1, True, "completed"))
        self.assertIsNone(gate.seal("completed"))

    def test_racing_seal_and_finish_claim_once(self):
        gate = Gate()
        slot = gate.admit()
        barrier = Barrier(2)

        def invoke(action):
            barrier.wait(5)
            return action()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(invoke, lambda: gate.seal("cancelled"))
            second = pool.submit(invoke, lambda: gate.finish(slot))
            values = [first.result(5), second.result(5)]
        self.assertEqual([v for v in values if v is not None], [(1, True, "cancelled")])

    def test_start_or_admission_loss_is_sticky_incomplete(self):
        for started, admitted in ((False, True), (True, False)):
            gate = Gate(started=started)
            slot = gate.admit(persisted=admitted)
            self.assertIsNone(gate.finish(slot))
            self.assertEqual(gate.seal("completed"), (1, False, "completed"))

    def test_overflow_is_bounded_and_cannot_close_complete(self):
        gate = Gate()
        slots = [gate.admit() for _ in range(MAX_SCOPES)]
        self.assertIsNone(gate.admit())
        self.assertEqual(len(gate.settled), MAX_SCOPES)
        for slot in slots:
            self.assertIsNone(gate.finish(slot))
        self.assertEqual(gate.seal("completed"), (8, False, "completed"))

    def test_no_entry_and_post_seal_registration(self):
        gate = Gate()
        self.assertEqual(gate.seal("failed"), (0, True, "failed"))
        with self.assertRaises(ValueError):
            gate.admit()
        self.assertIsNone(bounded_total([]))


if __name__ == "__main__":
    pure = load_pure_sanitizer()
    max_bytes = max(len(pure["encode_json_text"](p).encode("utf-8"))
                    for p in payloads(MAX_SCOPES))
    sanitizer_hash = hashlib.sha256(
        (ROOT / "app/processing/processing_events.py").read_bytes()).hexdigest()
    print(f"Local protocol controls: {platform.python_implementation()} "
          f"{platform.python_version()}; largest synthetic payload={max_bytes} bytes; "
          f"sanitizer_sha256={sanitizer_hash}", flush=True)
    unittest.main(verbosity=2)
