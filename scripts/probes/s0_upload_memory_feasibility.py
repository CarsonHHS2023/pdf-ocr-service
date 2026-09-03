"""Local synthetic S0.3.1 counterexamples; NOT a memory producer or benchmark.

Run from the repository root with PYTHONPATH=. and a disposable environment
containing the documented FastAPI/Starlette/python-multipart versions.
No HTTP server/client, PDF/OCR, database, storage adapter or probe installer runs.
Only small synthetic buffers and automatic temporary spools are used.
"""
from __future__ import annotations

import asyncio
from array import array
from contextvars import ContextVar, copy_context
import importlib.metadata
import io
import platform
import sys
import tempfile
from threading import Thread
import unittest
import weakref

from starlette.datastructures import Headers, UploadFile
from starlette.formparsers import MultiPartParser

from app import s0_upload_boundary_observability as upload


class UploadMemoryFeasibility(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.observation = upload._UploadObservation(wall_started=0.0)
        self.token = upload._CURRENT_UPLOAD.set(self.observation)

    async def asyncTearDown(self):
        upload._CURRENT_UPLOAD.reset(self.token)
        self.assertFalse(upload._INSTALLED)
        self.assertFalse(getattr(UploadFile.read, "__atlas_s0_upload_read__", False))

    async def test_retained_and_released_buffers_have_identical_read_evidence(self):
        async def schedule(keep_first):
            observation = upload._UploadObservation(wall_started=0.0)
            token = upload._CURRENT_UPLOAD.set(observation)
            sizes = iter((4096, 8192))

            async def delegate(_):
                # Fresh copies are intentional synthetic inputs, not a probe rule.
                return bytes(bytearray(next(sizes)))

            read = upload._wrap_uploadfile_read(delegate)
            try:
                first = await read(None)
                peak_declared_live_payload = len(first)
                if not keep_first:
                    del first
                second = await read(None)
                if keep_first:
                    self.assertIsNot(first, second)
                    peak_declared_live_payload = len(first) + len(second)
                else:
                    peak_declared_live_payload = max(peak_declared_live_payload, len(second))
                return (
                    observation.max_uploadfile_read_bytes,
                    observation.uploadfile_read_total_bytes,
                    peak_declared_live_payload,
                )
            finally:
                upload._CURRENT_UPLOAD.reset(token)

        retained = await schedule(True)
        released = await schedule(False)
        self.assertEqual(retained, (8192, 12288, 12288))
        self.assertEqual(released, (8192, 12288, 8192))
        # These are explicit caller-owned payload lengths, NOT allocator/RSS peaks.

    async def test_next_asgi_receive_does_not_release_prior_body(self):
        messages = iter((4096, 8192))

        async def receive():
            return {"type": "http.request", "body": bytes(bytearray(next(messages)))}

        async def send(_):
            return None

        observed = []

        async def delegate(_, scope, wrapped_receive, wrapped_send):
            first = await wrapped_receive()
            second = await wrapped_receive()
            self.assertEqual(len(first["body"]) + len(second["body"]), 12288)
            self.assertIsNot(first["body"], second["body"])
            obs = upload._CURRENT_UPLOAD.get()
            observed.append((obs.http_body_bytes_received, obs.max_asgi_receive_chunk_bytes))
            # Avoid the unrelated not-accepted diagnostic; no event is persisted.
            obs.finalized = True

        token = upload._CURRENT_UPLOAD.set(None)
        try:
            await upload._wrap_fastapi_call(delegate)(
                None, {"type": "http", "method": "POST", "path": "/api/v1/upload"},
                receive, send,
            )
        finally:
            upload._CURRENT_UPLOAD.reset(token)
        self.assertEqual(observed, [(12288, 8192)])

    async def test_borrowed_storage_argument_is_not_a_second_payload(self):
        payload = bytes(bytearray(4096))

        def fake_storage_put(data):
            self.assertIs(data, payload)
            return len(data)

        self.assertEqual(fake_storage_put(payload), 4096)
        alias = payload
        copied = bytes(bytearray(payload))
        self.assertIs(alias, payload)
        self.assertIsNot(copied, payload)
        self.assertEqual(copied, payload)
        # This tests Python argument sharing only, not real SDK allocation behavior.

    async def test_plain_bytes_and_bytearray_cannot_supply_weak_release_callbacks(self):
        for value in (bytes(bytearray(32)), bytearray(32)):
            with self.subTest(kind=type(value).__name__):
                with self.assertRaises(TypeError):
                    weakref.ref(value)

    async def test_weak_view_lifetime_is_not_backing_buffer_lifetime(self):
        payload = bytearray(32)
        view = memoryview(payload)
        finalized = []
        ref = weakref.ref(view, lambda _: finalized.append(True))
        del view
        self.assertIsNone(ref())
        self.assertEqual(finalized, [True])
        payload[0] = 1
        self.assertEqual(len(payload), 32)

    async def test_memoryview_element_length_and_backing_bytes_are_distinct(self):
        backing = array("I", [1, 2, 3])
        view = memoryview(backing)
        self.assertEqual(len(view), 3)
        self.assertEqual(view.nbytes, 3 * backing.itemsize)
        sliced = view[1:]
        self.assertIs(sliced.obj, backing)
        self.assertEqual(sliced.nbytes, 2 * backing.itemsize)
        self.assertLess(sliced.nbytes, view.nbytes)
        # Neither summing slices nor len(view) describes the backing allocation.

    async def test_existing_read_wrapper_returns_same_object_without_extra_retention(self):
        payload = bytes(bytearray(4096))

        async def delegate(_):
            return payload

        before = sys.getrefcount(payload)
        result = await upload._wrap_uploadfile_read(delegate)(None)
        self.assertIs(result, payload)
        self.assertEqual(sys.getrefcount(payload), before + 1)
        del result
        self.assertEqual(sys.getrefcount(payload), before)
        self.assertEqual(self.observation.max_uploadfile_read_bytes, 4096)

    async def test_real_uploadfile_memory_and_disk_spool_both_return_whole_payload(self):
        read = upload._wrap_uploadfile_read(UploadFile.read)
        for size, rolled in ((512, False), (8192, True)):
            with self.subTest(size=size):
                # Deliberately tiny TEST threshold, not an assertion about HF.
                with tempfile.SpooledTemporaryFile(max_size=1024, mode="w+b") as spool:
                    spool.write(b"x" * size)
                    spool.seek(0)
                    self.assertEqual(spool._rolled, rolled)
                    file = UploadFile(spool, size=size)
                    data = await read(file)
                    self.assertEqual(type(data), bytes)
                    self.assertEqual(len(data), size)
                    await file.close()
                    self.assertTrue(spool.closed)
                    self.assertEqual(len(data), size)
                    # Closing the spool does not release the caller's read result.

    async def test_real_multipart_parser_is_unseen_by_uploadfile_read_counter(self):
        read = upload._wrap_uploadfile_read(UploadFile.read)
        for size, rolled in ((512, False), (8192, True)):
            with self.subTest(size=size):
                observation = upload._UploadObservation(wall_started=0.0)
                token = upload._CURRENT_UPLOAD.set(observation)
                header = (
                    b"--probe\r\nContent-Disposition: form-data; name=\"file\"; "
                    b"filename=\"synthetic.bin\"\r\nContent-Type: application/octet-stream\r\n\r\n"
                )

                async def stream():
                    yield header
                    for _ in range(size // 128):
                        yield b"x" * 128
                    yield b"\r\n--probe--\r\n"

                try:
                    parser = MultiPartParser(
                        Headers({"content-type": "multipart/form-data; boundary=probe"}), stream(),
                    )
                    parser.max_file_size = 1024  # Pinned local Starlette test hook only.
                    form = await parser.parse()
                    try:
                        file = form["file"]
                        self.assertEqual(file.size, size)
                        self.assertEqual(file.file._rolled, rolled)
                        self.assertEqual(observation.uploadfile_read_total_bytes, 0)
                        self.assertEqual(len(await read(file)), size)
                        self.assertEqual(observation.uploadfile_read_total_bytes, size)
                    finally:
                        await form.close()
                finally:
                    upload._CURRENT_UPLOAD.reset(token)

    async def test_separate_overlapping_tasks_have_separate_observations(self):
        arrived = 0
        ready = asyncio.Event()

        async def worker(size):
            nonlocal arrived
            observation = upload._UploadObservation(wall_started=0.0)
            token = upload._CURRENT_UPLOAD.set(observation)

            async def delegate(_):
                return bytes(bytearray(size))

            try:
                arrived += 1
                if arrived == 2:
                    ready.set()
                await ready.wait()
                await upload._wrap_uploadfile_read(delegate)(None)
                return observation
            finally:
                upload._CURRENT_UPLOAD.reset(token)

        left, right = await asyncio.gather(worker(4096), worker(8192))
        self.assertIsNot(left, right)
        self.assertEqual((left.uploadfile_read_total_bytes, right.uploadfile_read_total_bytes), (4096, 8192))
        self.assertEqual(self.observation.uploadfile_read_total_bytes, 0)

    async def test_child_task_and_copied_context_share_mutable_observation(self):
        local = ContextVar("synthetic_mutable_context")
        original = {"count": 0}
        token = local.set(original)
        try:
            copied = copy_context()
            self.assertIs(copied[local], original)

            async def child():
                self.assertIs(upload._CURRENT_UPLOAD.get(), self.observation)
                local.get()["count"] += 1

            await asyncio.create_task(child())
            self.assertEqual(original["count"], 1)
        finally:
            local.reset(token)

    async def test_thread_propagation_is_explicit_not_universal(self):
        propagated = await asyncio.to_thread(upload._CURRENT_UPLOAD.get)
        self.assertIs(propagated, self.observation)
        values = []
        thread = Thread(target=lambda: values.append(upload._CURRENT_UPLOAD.get()))
        thread.start()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(values, [None])

    async def test_finalization_suppresses_late_read_but_does_not_prove_coverage(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def delegate(_):
            started.set()
            await release.wait()
            return bytes(bytearray(4096))

        task = asyncio.create_task(upload._wrap_uploadfile_read(delegate)(None))
        await started.wait()
        self.observation.finalized = True
        release.set()
        self.assertEqual(len(await task), 4096)
        self.assertEqual(self.observation.uploadfile_read_total_bytes, 0)
        # A synthetic concurrent child read crossing the cutoff. This is not
        # a claim that the current canonical handler starts such child reads.

    async def test_read_failure_and_cancellation_are_preserved(self):
        for exception in (ValueError("synthetic"), asyncio.CancelledError()):
            with self.subTest(kind=type(exception).__name__):
                async def delegate(_):
                    raise exception

                with self.assertRaises(type(exception)) as raised:
                    await upload._wrap_uploadfile_read(delegate)(None)
                self.assertIs(raised.exception, exception)
        self.assertEqual(self.observation.uploadfile_read_total_bytes, 0)

    async def test_read_probe_is_noop_without_request_context(self):
        token = upload._CURRENT_UPLOAD.set(None)
        try:
            file = UploadFile(io.BytesIO(b"x" * 128), size=128)
            try:
                result = await upload._wrap_uploadfile_read(UploadFile.read)(file)
                self.assertEqual(result, b"x" * 128)
                self.assertEqual(self.observation.uploadfile_read_total_bytes, 0)
            finally:
                await file.close()
        finally:
            upload._CURRENT_UPLOAD.reset(token)


if __name__ == "__main__":
    print("LOCAL SYNTHETIC FEASIBILITY ONLY; NO MEMORY ACCEPTANCE", flush=True)
    print(f"Python {platform.python_version()} ({platform.python_implementation()})", flush=True)
    for package in ("fastapi", "starlette", "python-multipart", "anyio"):
        print(f"{package}=={importlib.metadata.version(package)}", flush=True)
    unittest.main(verbosity=2)
