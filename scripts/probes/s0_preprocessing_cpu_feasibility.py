"""Stdlib-only local CPU attribution counterexamples, not an app producer.

Run directly with Python 3.11 or 3.12. No app imports, PDF/native processing,
network, database, runtime installation or benchmark fixture is involved.
The synthetic bracket below does not establish durable/collector acceptance.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from dataclasses import dataclass
import platform
from threading import Event, get_ident
import time
import unittest


@dataclass(frozen=True)
class Sample:
    start: tuple | None
    end: tuple | None
    outcome: str

    @property
    def delta_ns(self):
        if self.start is None or self.end is None:
            return None
        start_thread, start_ns = self.start
        end_thread, end_ns = self.end
        if start_thread != end_thread:
            return None
        if any(type(value) is not int or value < 0 for value in (start_ns, end_ns)):
            return None
        return end_ns - start_ns if end_ns >= start_ns else None


def _read(clock, identity):
    try:
        return identity(), clock()
    except Exception:
        return None


def _bracket(delegate, publish, *, clock=time.thread_time_ns, identity=get_ident):
    # A local toy seam, intentionally not imported by the application.
    start = _read(clock, identity)
    outcome = "failed"
    try:
        result = delegate()
        outcome = "completed"
        return result
    finally:
        end = _read(clock, identity)
        try:
            publish(Sample(start, end, outcome))
        except Exception:
            pass


def _burn_cpu(target_ns=50_000_000):
    start = time.thread_time_ns()
    deadline = time.monotonic() + 5
    value = 1
    while time.thread_time_ns() - start < target_ns:
        for _ in range(128):
            value = (value * 17 + 3) % 65521
        if time.monotonic() >= deadline:
            raise TimeoutError("synthetic CPU control exceeded watchdog")
    return time.thread_time_ns() - start


def _wait(event):
    if not event.wait(5):
        raise TimeoutError("synthetic coordination exceeded watchdog")


class ClockContract(unittest.TestCase):
    def test_same_thread_integer_delta(self):
        self.assertEqual(Sample((7, 100), (7, 150), "completed").delta_ns, 50)

    def test_explicit_zero_is_valid_only_with_two_valid_samples(self):
        self.assertEqual(Sample((7, 100), (7, 100), "completed").delta_ns, 0)
        self.assertIsNone(Sample(None, None, "completed").delta_ns)

    def test_invalid_clock_or_thread_evidence_is_not_zero(self):
        for start, end in (
            ((7, 100), (8, 150)), ((7, 100), (7, 99)),
            ((7, -1), (7, 0)), ((7, True), (7, 2)),
            ((7, 1.0), (7, 2)), ((7, 1), (7, float("nan"))),
            (None, (7, 2)), ((7, 1), None),
        ):
            with self.subTest(start=start, end=end):
                self.assertIsNone(Sample(start, end, "completed").delta_ns)

    def test_clock_end_precedes_publication(self):
        order = []

        def clock():
            order.append("clock")
            return len(order)

        result = _bracket(lambda: order.append("delegate"),
                          lambda _: order.append("publish"), clock=clock)
        self.assertIsNone(result)
        self.assertEqual(order, ["clock", "delegate", "clock", "publish"])

    def test_delegate_exception_is_preserved(self):
        failure = ValueError("synthetic failure")
        samples = []

        def delegate():
            raise failure

        with self.assertRaises(ValueError) as caught:
            _bracket(delegate, samples.append)
        self.assertIs(caught.exception, failure)
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0].outcome, "failed")

    def test_clock_and_publication_failure_do_not_change_delegate(self):
        def unavailable(*_):
            raise RuntimeError("synthetic observer unavailable")

        samples = []
        sentinel = object()
        self.assertIs(_bracket(lambda: sentinel, samples.append,
                               clock=unavailable), sentinel)
        self.assertIsNone(samples[0].delta_ns)
        self.assertIs(_bracket(lambda: sentinel, unavailable), sentinel)
        failure = ValueError("synthetic delegate failure")

        def delegate():
            raise failure

        with self.assertRaises(ValueError) as caught:
            _bracket(delegate, unavailable, clock=unavailable)
        self.assertIs(caught.exception, failure)

    def test_reused_worker_uses_fresh_interval_not_lifetime_cpu(self):
        samples = []
        with ThreadPoolExecutor(max_workers=1) as pool:
            for _ in range(2):
                spent = pool.submit(_bracket, _burn_cpu, samples.append).result(5)
                self.assertGreaterEqual(samples[-1].delta_ns, spent)
        first, second = samples
        self.assertEqual(first.start[0], second.start[0])
        self.assertGreaterEqual(second.start[1], first.end[1])
        self.assertEqual(second.delta_ns, second.end[1] - second.start[1])

    def test_raw_executor_submit_does_not_copy_context(self):
        current = ContextVar("synthetic_run", default=None)
        token = current.set("synthetic-operation")
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                inherited, explicit = pool.submit(
                    lambda run: (current.get(), run), current.get()
                ).result(5)
            self.assertIsNone(inherited)
            self.assertEqual(explicit, "synthetic-operation")
        finally:
            current.reset(token)

    def test_process_clock_includes_unrelated_thread_work(self):
        with ThreadPoolExecutor(max_workers=1) as other:
            thread_start = time.thread_time_ns()
            process_start = time.process_time_ns()
            unrelated_cpu = other.submit(_burn_cpu).result(5)
            process_delta = time.process_time_ns() - process_start
            own_delta = time.thread_time_ns() - thread_start
        self.assertGreaterEqual(process_delta, unrelated_cpu)
        # Generous smoke-test separation, not a production admission threshold.
        self.assertLess(own_delta, unrelated_cpu // 2)

    def test_worker_clock_omits_owned_helper_cpu(self):
        samples = []

        def delegate():
            with ThreadPoolExecutor(max_workers=1) as helper:
                return helper.submit(_burn_cpu).result(5)

        with ThreadPoolExecutor(max_workers=1) as worker:
            helper_cpu = worker.submit(_bracket, delegate, samples.append).result(5)
        self.assertLess(samples[0].delta_ns, helper_cpu // 2)
        # Python helper stands in for missing ownership; no OpenCV claim is made.


class AsyncBoundary(unittest.IsolatedAsyncioTestCase):
    async def test_awaiting_thread_clock_is_not_worker_clock(self):
        samples = []
        with ThreadPoolExecutor(max_workers=1) as pool:
            start = time.thread_time_ns()
            spent = await asyncio.wrap_future(pool.submit(
                _bracket, _burn_cpu, samples.append
            ))
            loop_delta = time.thread_time_ns() - start
        self.assertNotEqual(samples[0].start[0], get_ident())
        self.assertGreaterEqual(samples[0].delta_ns, spent)
        self.assertLess(loop_delta, spent // 2)

    async def test_cancelled_awaiter_is_not_worker_terminal(self):
        entered, release = Event(), Event()
        samples = []

        def delegate():
            entered.set()
            _wait(release)
            return "synthetic-result"

        async def wait_shielded(future):
            return await asyncio.shield(asyncio.wrap_future(future))

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_bracket, delegate, samples.append)
            waiter = asyncio.create_task(wait_shielded(future))
            try:
                await asyncio.to_thread(_wait, entered)
                waiter.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await waiter
                self.assertFalse(future.done())
                self.assertFalse(future.cancel())
                self.assertEqual(samples, [])
            finally:
                release.set()
            self.assertEqual(await asyncio.wrap_future(future), "synthetic-result")
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0].outcome, "completed")

    async def test_cancelled_queued_future_has_no_stage_entry(self):
        entered, release = Event(), Event()
        samples = []

        def occupy():
            entered.set()
            _wait(release)

        with ThreadPoolExecutor(max_workers=1) as pool:
            running = pool.submit(occupy)
            try:
                await asyncio.to_thread(_wait, entered)
                queued = pool.submit(_bracket, lambda: None, samples.append)
                self.assertTrue(queued.cancel())
                self.assertTrue(queued.cancelled())
                self.assertEqual(samples, [])
            finally:
                release.set()
            await asyncio.wrap_future(running)


if __name__ == "__main__":
    print(f"Local synthetic CPU probes: {platform.python_implementation()} "
          f"{platform.python_version()}", flush=True)
    unittest.main(verbosity=2)
