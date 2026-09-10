"""Staging-only canonical upload acknowledgement and detached Reader terminal."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from threading import BoundedSemaphore

from fastapi import Request, Response
from app import s0_upload_reader_metrics as contract
from app import s0_upload_reader_persistence as persistence
from app.s0_reader_open_observability import revision


@dataclass
class Upload:
    root: str
    frontend: str
    backend: str
    dispatch_id: str | None = None
    ambiguous: bool = False


_CURRENT = ContextVar("s0_upload_reader", default=None)
_WRITERS = ThreadPoolExecutor(max_workers=2, thread_name_prefix="s0-upload-reader")
_CAPACITY = BoundedSemaphore(2)


async def _publish(function, *args):
    # At most two owned writes, including queued/running work. Cancellation of
    # the HTTP waiter cannot abandon a running transaction's cleanup ownership.
    if not _CAPACITY.acquire(blocking=False):
        raise RuntimeError("observer capacity unavailable")
    try:
        future = _WRITERS.submit(function, *args)
    except Exception:
        _CAPACITY.release()
        raise
    future.add_done_callback(lambda _: _CAPACITY.release())
    return await asyncio.wrap_future(future)


def _header(scope, name, field):
    values = [v.decode("ascii", errors="replace") for k, v in scope.get("headers", []) if k.lower() == name]
    return values[0] if len(values) == 1 and contract.valid_id(field, values[0]) else None


def _wrap_finalize(delegate):
    if getattr(delegate, "__s0_upload_reader__", False):
        return delegate

    @wraps(delegate)
    def wrapped(func, args, kwargs):
        # Existing timing freezes first. This hook retains only a dispatch ID;
        # the observer-owned transaction runs before response headers, off-loop.
        result = delegate(func, args, kwargs)
        try:
            from app.s0_upload_durable_dispatch_compat import _durable_dispatch_id
            op = _CURRENT.get()
            dispatch_id = _durable_dispatch_id(func, args, kwargs)
            if op is not None and dispatch_id is not None:
                if op.dispatch_id is not None:
                    op.ambiguous = True
                op.dispatch_id = dispatch_id
        except Exception:
            pass
        return result

    wrapped.__s0_upload_reader__ = True
    return wrapped


class UploadReaderMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        backend = revision()
        root = _header(scope, b"x-atlas-s0-upload", "upload_scope_id")
        frontend = _header(scope, b"x-atlas-s0-upload-frontend", "frontend_revision")
        if (scope.get("type") != "http" or scope.get("method") != "POST"
                or scope.get("path") != "/api/v1/upload" or not backend or not root or not frontend):
            return await self.app(scope, receive, send)
        op = Upload(root, frontend, backend)
        token = _CURRENT.set(op)

        async def observed_send(message):
            if (message["type"] == "http.response.start" and 200 <= message["status"] < 300
                    and op.dispatch_id is not None and not op.ambiguous and revision() == op.backend):
                try:
                    accepted = await _publish(persistence.accept, op.dispatch_id, op.root, op.frontend, op.backend)
                except Exception:
                    accepted = False
                if accepted and revision() == op.backend:
                    headers = list(message.get("headers", []))
                    headers.extend([(b"x-atlas-s0-upload-accepted", op.root.encode()),
                        (b"x-atlas-s0-upload-revision", op.backend.encode()),
                        (b"access-control-expose-headers", b"X-Atlas-S0-Upload-Accepted, X-Atlas-S0-Upload-Revision")])
                    message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, observed_send)
        finally:
            _CURRENT.reset(token)


async def terminal(request: Request, document_ref: str):
    backend = revision()
    if not backend:
        return Response(status_code=404)
    media = request.headers.get("content-type", "").lower().replace(" ", "")
    if media not in ("application/json", "application/json;charset=utf-8"):
        return Response(status_code=422)
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > 2048:
            return Response(status_code=413)
        data.extend(chunk)
    payload, ok = contract.decode_payload(bytes(data), 2048)
    if not ok or not contract.valid_request(payload):
        return Response(status_code=422)
    try:
        status = await _publish(persistence.terminal, document_ref, payload, backend)
    except Exception:
        status = 503
    return Response(status_code=status)


def install(app):
    if not revision() or getattr(app.state, "s0_upload_reader_installed", False):
        return
    from app import s0_upload_boundary_observability as upload
    upload._finalize_from_background_task = _wrap_finalize(upload._finalize_from_background_task)
    app.add_middleware(UploadReaderMiddleware)
    app.add_api_route("/api/reader/v2/documents/{document_ref}/s0-upload-ready", terminal,
        methods=["POST"], include_in_schema=False)
    app.state.s0_upload_reader_installed = True
