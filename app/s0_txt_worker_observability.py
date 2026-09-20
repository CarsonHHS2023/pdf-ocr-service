"""Staging TXT worker instrumentation; all observer work is outside the interval."""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from time import perf_counter_ns
import uuid

from app import s0_txt_worker_metrics as contract
from app.s0_txt_worker_persistence import publish, revision

_CLAIM = ContextVar("s0_txt_worker_claim", default=None)


def invoke(processor, document_id, source_id, ids, *, claim, session_factory):
    """Runs inside to_thread. Cancellation of its waiter cannot synthesize a stop."""
    token = _CLAIM.set((claim, session_factory))
    try:
        return processor(document_id, source_id, ids)
    finally:
        _CLAIM.reset(token)


@dataclass
class Observation:
    claim: object
    engine: object
    common: dict
    started: int | None = None
    clock_error: str | None = None
    finished: bool = False

    def start(self):
        try:
            sample = perf_counter_ns()
            if type(sample) is not int or sample < 0:
                self.clock_error = "invalid_clock"
            else:
                self.started = sample
        except Exception:
            self.clock_error = "clock_unavailable"

    def finish(self, outcome=None, *, reason=None):
        # Freeze the worker clock before any publication, outcome validation or SQL.
        if self.finished:
            return
        self.finished = True
        ended = None
        if reason is None:
            try:
                ended = perf_counter_ns()
            except Exception:
                self.clock_error = "clock_unavailable"
        payload = dict(self.common, ordinal=1, outcome="failed", duration_ns=None,
                       candidate_scope_id=None, reason=reason or "unexpected_error")
        if reason is None:
            payload.update(outcome="invalid", reason=self.clock_error or "invalid_clock")
            if (not self.clock_error and type(ended) is int and self.started is not None
                    and contract.integer(ended - self.started)):
                try:
                    matches = (outcome.document_ref == self.claim.document_id
                        and outcome.source_file_ref == self.claim.source_file_id
                        and outcome.processing_run_ref == self.claim.payload.txt_processing_run_ref)
                    candidate = contract.opaque_scope("candidate", outcome.candidate_id)
                except Exception:
                    matches, candidate = False, None
                if matches and candidate:
                    payload.update(outcome="completed", duration_ns=ended-self.started,
                                   candidate_scope_id=candidate, reason="none")
                else:
                    payload["reason"] = "candidate_mismatch"
        publish(self.engine, self.claim, contract.TERMINAL, payload)


def admit(document_id, source_id, ids):
    try:
        bound = _CLAIM.get()
        backend = revision()
        if bound is None or backend is None:
            return None
        claim, factory = bound
        if (claim.document_id != document_id or claim.source_file_id != source_id
            or claim.payload.kind != "txt" or claim.payload.txt_processing_run_ref != ids.processing_run_ref
            or not contract.matches(ids.processing_run_ref, r"txt-ingest-[0-9a-f]{32}")):
            return None
        common = dict(contract_version=contract.VERSION, method=contract.METHOD,
            measurement_scope=contract.SCOPE, worker_scope_id="txtw_" + uuid.uuid4().hex,
            source_scope_id=contract.opaque_scope("source", source_id),
            dispatch_scope_id=contract.opaque_scope("dispatch", claim.dispatch_id),
            dispatch_attempt=claim.attempt_count, backend_revision=backend)
        engine = factory.kw["bind"]
        if not publish(engine, claim, contract.START, dict(common, ordinal=0)):
            return None
        return Observation(claim, engine, common)
    except Exception:
        return None


def begin(observation):
    if observation is not None:
        observation.start()


def finish(observation, outcome=None, *, reason=None):
    if observation is not None:
        try:
            observation.finish(outcome, reason=reason)
        except Exception:
            pass
