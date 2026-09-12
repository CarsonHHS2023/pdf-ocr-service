"""Synthetic evidence contracts only; no database, producer or provider calls."""
import copy
from dataclasses import replace
import json
import unittest

from app import s0_txt_worker_metrics as c


def context(**changes):
    base = c.AdmissionContext(run_id="txt-ingest-" + "1" * 32, document_id="doc-test",
        source_id="source-test", candidate_id="candidate-test", dispatch_id="dispatch-test",
        dispatch_attempt=2, backend_revision="a" * 40, source_bytes=2048,
        source_type="txt", run_status="succeeded", document_status="completed", dispatch_status="succeeded")
    return replace(base, **changes)


def payloads():
    ctx = context()
    common = dict(contract_version=c.VERSION, method=c.METHOD, measurement_scope=c.SCOPE,
        worker_scope_id="txtw_" + "b" * 32, source_scope_id=c.opaque_scope("source", ctx.source_id),
        dispatch_scope_id=c.opaque_scope("dispatch", ctx.dispatch_id), dispatch_attempt=ctx.dispatch_attempt,
        backend_revision=ctx.backend_revision)
    return [{**common, "ordinal": 0}, {**common, "ordinal": 1, "outcome": "completed",
        "duration_ns": 1_234_567_890, "candidate_scope_id": c.opaque_scope("candidate", ctx.candidate_id), "reason": "none"}]


def envelope(name, payload):
    ctx = context()
    return dict(id=c.slot_id(ctx.run_id, payload["ordinal"]), processing_run_id=ctx.run_id,
        document_id=ctx.document_id, schema_version=c.SCHEMA, event_name=name,
        severity="warning" if name == c.INVALIDATED else
            "error" if name == c.TERMINAL and payload["outcome"] == "failed" else "info",
        page_number=None, payload_json=json.dumps(payload, allow_nan=False, separators=(",", ":")))


def rows():
    start, terminal = payloads()
    return [envelope(c.START, start), envelope(c.TERMINAL, terminal)]


class TxtWorkerMetricsTests(unittest.TestCase):
    def assert_unavailable(self, events, ctx=None, **kwargs):
        result = c.evaluate(events, ctx or context(), **kwargs)
        self.assertEqual(result.status, "not_available")
        self.assertIsNone(result.value)

    def test_complete_evidence_is_order_independent(self):
        for evidence in (rows(), list(reversed(rows())), tuple(rows())):
            result = c.evaluate(evidence, context())
            self.assertEqual(result.status, "observed")
            self.assertEqual(result.value, 1.23456789)

    def test_zero_and_exact_integer_clock_ceiling_are_measured(self):
        for duration in (0, 1, c.MAX_NS):
            with self.subTest(duration=duration):
                a, b = payloads(); b["duration_ns"] = duration
                result = c.evaluate([envelope(c.START, a), envelope(c.TERMINAL, b)], context())
                self.assertEqual(result.status, "observed")
                self.assertEqual(result.value, duration / 1_000_000_000)

    def test_bad_clock_values_do_not_become_zero(self):
        for duration in (True, False, -1, 1.0, "1", None, c.MAX_NS + 1, [], {}):
            with self.subTest(duration=duration):
                a, b = payloads(); b["duration_ns"] = duration
                self.assert_unavailable([envelope(c.START, a), envelope(c.TERMINAL, b)])

    def test_missing_duplicate_and_excess_events(self):
        a, b = rows()
        for evidence in ([], [a], [b], [a, a], [a, b, b], [a, b, a, b], None, iter([a, b])):
            with self.subTest(evidence=evidence):
                self.assert_unavailable(evidence)

    def test_durable_invalidation_rejects_prior_success(self):
        for reason in c.INVALIDATIONS:
            with self.subTest(reason=reason):
                a, _ = payloads(); a.update(ordinal=2, reason=reason)
                self.assert_unavailable(rows() + [envelope(c.INVALIDATED, a)])

    def test_unknown_event_and_protocol_are_rejected(self):
        a, b = rows(); b["event_name"] = c.PREFIX + "FUTURE_TERMINAL"
        self.assert_unavailable([a, b])
        for field, value in (("contract_version", "v2"), ("method", "process_rss"), ("measurement_scope", "pdf")):
            with self.subTest(field=field):
                a, b = payloads(); b[field] = value
                self.assert_unavailable([envelope(c.START, a), envelope(c.TERMINAL, b)])

    def test_identity_must_match_start_terminal_and_context(self):
        mutations = {"worker_scope_id": "txtw_" + "c"*32, "source_scope_id": "source_" + "c"*64,
            "dispatch_scope_id": "dispatch_" + "c"*64, "dispatch_attempt": 3, "backend_revision": "c"*40}
        for field, value in mutations.items():
            with self.subTest(field=field):
                a, b = payloads(); b[field] = value
                self.assert_unavailable([envelope(c.START, a), envelope(c.TERMINAL, b)])
        for field in ("source_scope_id", "dispatch_scope_id", "dispatch_attempt", "backend_revision"):
            with self.subTest(both=field):
                a, b = payloads(); a[field] = b[field] = mutations[field]
                self.assert_unavailable([envelope(c.START, a), envelope(c.TERMINAL, b)])

    def test_candidate_binding_is_full_digest_and_exact(self):
        a, b = payloads(); b["candidate_scope_id"] = c.opaque_scope("candidate", "another-candidate")
        self.assert_unavailable([envelope(c.START, a), envelope(c.TERMINAL, b)])
        self.assertEqual(len(c.opaque_scope("candidate", "another-candidate")), len("candidate_") + 64)

    def test_envelope_identity_schema_and_slots_are_checked(self):
        changes = {"id": "arbitrary-slot", "processing_run_id": "txt-ingest-"+"2"*32,
            "document_id": "other-doc", "schema_version": "unknown", "severity": "warning", "page_number": 1}
        for field, value in changes.items():
            with self.subTest(field=field):
                evidence = rows(); evidence[1][field] = value
                self.assert_unavailable(evidence)

    def test_envelope_extra_or_missing_fields_are_rejected(self):
        for field in c.ENVELOPE:
            with self.subTest(field=field):
                evidence = rows(); del evidence[0][field]
                self.assert_unavailable(evidence)
        evidence = rows(); evidence[0]["raw_url"] = "https://synthetic.invalid"
        self.assert_unavailable(evidence)

    def test_false_ordinals_and_attempts_are_rejected(self):
        for field, value in (("ordinal", False), ("ordinal", True), ("dispatch_attempt", True),
                ("dispatch_attempt", 0), ("dispatch_attempt", c.MAX_ATTEMPT + 1)):
            with self.subTest(field=field, value=value):
                a, _ = payloads(); a[field] = value
                self.assertFalse(c.valid_payload(c.START, a))

    def test_invalid_identity_shapes_are_rejected(self):
        for field in ("worker_scope_id", "source_scope_id", "dispatch_scope_id", "backend_revision"):
            for value in (None, {}, [], "", "../bad", "a"*256):
                with self.subTest(field=field, value=value):
                    a, _ = payloads(); a[field] = value
                    self.assertFalse(c.valid_payload(c.START, a))

    def test_durable_status_gates_cover_cancelled_or_lost_dispatch(self):
        for state in ("queued", "claimed", "running", "failed", None):
            with self.subTest(dispatch=state):
                self.assert_unavailable(rows(), context(dispatch_status=state))
        for field, value in (("run_status", "running"), ("document_status", "processing"),
                ("document_status", "failed"), ("source_type", "pdf")):
            with self.subTest(field=field):
                self.assert_unavailable(rows(), context(**{field: value}))

    def test_context_identity_and_source_size_are_required(self):
        for field, value in (("run_id", "pdf-ingest-"+"1"*32), ("source_bytes", 0), ("source_bytes", True),
                ("dispatch_attempt", True), ("dispatch_id", "different-dispatch"), ("candidate_id", "different-candidate"),
                ("source_id", "different-source"), ("backend_revision", "d"*40)):
            with self.subTest(field=field):
                self.assert_unavailable(rows(), context(**{field: value}))
        self.assertEqual(c.evaluate(rows(), None).status, "not_available")

    def test_incomplete_snapshot_cannot_be_admitted(self):
        for flag in (True, None, 0, "false"):
            with self.subTest(flag=flag):
                self.assert_unavailable(rows(), evidence_incomplete=flag)

    def test_failure_and_clock_loss_are_valid_evidence_but_not_success(self):
        for outcome, reasons in (("failed", c.FAILURES), ("invalid", c.INVALID_REASONS)):
            for reason in reasons:
                with self.subTest(outcome=outcome, reason=reason):
                    a, b = payloads(); b.update(outcome=outcome, reason=reason, duration_ns=None, candidate_scope_id=None)
                    self.assertTrue(c.valid_payload(c.TERMINAL, b))
                    self.assert_unavailable([envelope(c.START, a), envelope(c.TERMINAL, b)])
                    b["duration_ns"] = 0
                    self.assertFalse(c.valid_payload(c.TERMINAL, b))

    def test_missing_or_private_payload_fields_are_rejected(self):
        for name, original in zip((c.START, c.TERMINAL), payloads()):
            for key in original:
                with self.subTest(name=name, missing=key):
                    changed = dict(original); del changed[key]
                    self.assertFalse(c.valid_payload(name, changed))
            for key in ("filename", "title", "source_text", "token", "storage_reference", "raw_url"):
                with self.subTest(name=name, private=key):
                    self.assertFalse(c.valid_payload(name, {**original, key: "synthetic"}))

    def test_decoder_rejects_duplicate_keys_nonfinite_and_malformed_json(self):
        for raw in ('{"x":1,"x":2}', '{"x":{"n":1,"n":2}}', '{"x":NaN}', '{"x":Infinity}',
                'null', '[]', '{', b'\xff', None, 2, '\ud800', '['*1000 + ']'*1000):
            with self.subTest(raw=repr(raw)[:60]):
                self.assertFalse(c.decode_payload(raw)[1])

    def test_decoder_limits_encoded_bytes_not_just_characters(self):
        raw = '{"x":"' + '\u4e2d'*700 + '"}'
        self.assertLess(len(raw), c.MAX_BYTES)
        self.assertFalse(c.decode_payload(raw)[1])
        for extra, expected in ((0, True), (1, False)):
            raw = '{"x":"' + 'a'*(c.MAX_BYTES - 8 + extra) + '"}'
            self.assertEqual(c.decode_payload(raw)[1], expected)

    def test_all_fixture_payloads_fit_bound_and_round_trip(self):
        for row in rows():
            self.assertLess(len(row["payload_json"].encode()), c.MAX_BYTES)
            payload, ok = c.decode_payload(row["payload_json"].encode())
            self.assertTrue(ok)
            self.assertTrue(c.valid_payload(row["event_name"], payload))

    def test_evaluation_is_pure_and_output_has_no_identity(self):
        evidence = rows(); before = copy.deepcopy(evidence)
        result = c.evaluate(evidence, context())
        self.assertEqual(before, evidence)
        for private in (context().run_id, context().document_id, context().source_id, context().dispatch_id):
            self.assertNotIn(private, repr(result))

    def test_hash_identity_validation_and_stable_separate_slots(self):
        self.assertIsNone(c.opaque_scope("url", "source-test"))
        for value in (None, "", "../bad", "a"*256):
            self.assertIsNone(c.opaque_scope("source", value))
        self.assertEqual(len({c.slot_id(context().run_id, i) for i in range(3)}), 3)
        self.assertNotEqual(c.slot_id(context().run_id, 0), c.slot_id("txt-ingest-"+"2"*32, 0))


if __name__ == "__main__":
    unittest.main()
