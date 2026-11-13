"""exp26: transparent ASGI and vLLM 0.8.5 V0 CPU-side cancellation audit.

Load with --middleware backend_audit.AuditMiddleware. Native engine evidence
requires --disable-frontend-multiprocessing and V0. No GPU-stop claim is made.
Only requests carrying X-Exp26-Request-ID / X-Exp26-Attempt-ID are audited.
"""
import base64
import contextvars
import functools
import hashlib
import inspect
import json
import os
import socket
import sys
import threading
import time
import uuid


_HTTP = contextvars.ContextVar("exp26_http", default=None)
_LOCK = threading.RLock()
_REQUESTS = {}  # Retained for the isolated run, including after abort/finish.
_INSTALLED = False
_HOOKS = []
_ERRORS = 0
_RUN = uuid.uuid4().hex


def write(record):
    """Fail open: audit failures must never replace a native return/exception."""
    global _ERRORS
    try:
        import fcntl
        with _LOCK:
            row = dict(record, schema="exp26.backend.v1", pid=os.getpid(),
                       clock_domain=f"{socket.gethostname()}:{os.getpid()}:{_RUN}",
                       backend_monotonic_ns=time.monotonic_ns(),
                       wall_time_ns=time.time_ns())
            data = (json.dumps(row, ensure_ascii=True, default=str) + "\n").encode()
            # No directory creation, environment change, or deferred writer task.
            with open(os.environ["EXP26_AUDIT_PATH"], "ab", buffering=0) as stream:
                fcntl.flock(stream, fcntl.LOCK_EX)
                view = memoryview(data)
                while view:
                    count = stream.write(view)
                    if not count:
                        raise OSError("audit short write")
                    view = view[count:]
    except Exception as exc:
        _ERRORS += 1
        if _ERRORS == 1:
            try:
                print(f"exp26 audit unavailable: {type(exc).__name__}; evidence incomplete",
                      file=sys.stderr)
            except Exception:
                pass


def _observe(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        write({"event": "observation_error", "observer": fn.__name__,
               "error": type(exc).__name__})


def _event(event, engine_request_id, **fields):
    identity = _REQUESTS.get(engine_request_id)
    if identity is not None:
        write(dict(identity, event=event, engine_request_id=engine_request_id, **fields))


def _bind(request_id):
    ctx = _HTTP.get()
    if ctx is None or not isinstance(request_id, str):
        return
    identity = {k: ctx[k] for k in ("request_id", "attempt_id", "http_id")}
    previous = _REQUESTS.get(request_id)
    if previous is not None and previous != identity:
        write(dict(identity, event="engine_id_conflict", engine_request_id=request_id,
                   previous=previous))
        return
    _REQUESTS[request_id] = identity
    ctx["engine_request_ids"].add(request_id)
    _event("engine_request", request_id)


def _snapshot(owner, event, **fields):
    """Observe queues without consuming them or calling step/abort ourselves."""
    if not _REQUESTS:
        return
    engine = getattr(owner, "engine", owner)
    tracker = getattr(owner, "_request_tracker", None)
    aliases = {k: v.group_id for k, v in engine.seq_id_to_seq_group.items()}
    # Remember actual child IDs while vLLM's n>1 mapping still exists.
    for child, parent in aliases.items():
        if parent in _REQUESTS and child not in _REQUESTS:
            _REQUESTS[child] = dict(_REQUESTS[parent])
            _event("engine_child_request", child, parent_engine_request_id=parent)
    queues = []
    for index, scheduler in enumerate(engine.scheduler):
        for name in ("waiting", "running", "swapped"):
            for group in tuple(getattr(scheduler, name)):
                queues.append({"virtual_engine": index, "queue": name,
                               "engine_request_id": group.request_id,
                               "parent_engine_request_id": aliases.get(group.request_id),
                               "unfinished": not group.is_finished()})
    cached = []
    multi_step = engine.scheduler_config.is_multi_step
    for state in engine.cached_scheduler_outputs:
        for meta in state.seq_group_metadata_list or ():
            cached.append({"engine_request_id": meta.request_id,
                           "remaining_steps": meta.state.remaining_steps if multi_step else 0})
    active = set(tracker._request_streams) if tracker is not None else set()
    new = {item[1]["request_id"] for item in tuple(tracker._new_requests._queue)} if tracker is not None else set()
    aborted = set(tracker._aborted_requests._queue) if tracker is not None else set()
    for rid in tuple(_REQUESTS):
        children = {key for key, parent in aliases.items() if parent == rid}
        ids = {rid, *children}
        matched = [q for q in queues if q["engine_request_id"] in ids]
        cache = [q for q in cached if q["engine_request_id"] in ids]
        tracker_state = None if tracker is None else {
            "active_stream": bool(ids & active), "new_pending": bool(ids & new),
            "abort_pending": bool(ids & aborted)}
        engine_pending = (any(q["unfinished"] for q in matched)
                          or any(q["remaining_steps"] > 0 for q in cache))
        _event(event, rid, engine_object_id=id(engine), queues=matched, cached=cache,
               scheduler_unfinished=any(q["unfinished"] for q in matched),
               engine_pending_or_unfinished=engine_pending, tracker=tracker_state,
               pending_or_unfinished=(engine_pending or any(tracker_state.values()))
               if tracker_state is not None else None,
               snapshot_complete=True, **fields)


def _ids(value):
    # In particular, do NOT consume arbitrary abort iterators before vLLM does.
    if isinstance(value, str):
        return (value,)
    if type(value) in (list, tuple, set, frozenset):
        return tuple(x for x in value if isinstance(x, str))
    return ()


def _patch(cls, name, kind, argument="request_id"):
    original = getattr(cls, name)
    signature = inspect.signature(original)
    label = f"{cls.__name__}.{name}"

    def before(owner, args, kwargs):
        bound = signature.bind_partial(owner, *args, **kwargs)
        value = bound.arguments.get(argument)
        if kind == "add":
            _bind(value)  # Only frontend add inherits HTTP context; never engine loop.
        ids = _ids(value)
        if kind == "output":
            output = bound.arguments["request_output"]
            rid = output.request_id
            _event("engine_finished" if output.finished else "engine_output", rid,
                   finished=output.finished,
                   outputs=[{"index": o.index, "finish_reason": o.finish_reason,
                             "stop_reason": o.stop_reason, "token_ids": list(o.token_ids)}
                            for o in getattr(output, "outputs", ())])
        if kind == "abort":
            for rid in ids:
                _event("abort_called", rid, hook=label)
        if (kind in ("step", "abort") and hasattr(owner, "scheduler")) or kind == "outer_step":
            _observe(_snapshot, owner, "state_before", hook=label)
        return ids

    def after(owner, ids, error=None):
        if kind in ("add", "abort"):
            for rid in ids or ():
                _event(f"{kind}_returned" if error is None else f"{kind}_raised", rid,
                       hook=label, error=error)
                if label == "LLMEngine.abort_request" and error is None:
                    _event("abort_done", rid, hook=label, meaning="native abort_request returned; may be no-op")
        if (kind in ("step", "abort") and hasattr(owner, "scheduler")) or kind == "outer_step":
            _observe(_snapshot, owner, "state_after", hook=label, error=error,
                     cause_engine_request_ids=list(ids or ()))

    if inspect.iscoroutinefunction(original):
        @functools.wraps(original)
        async def wrapped(self, *args, **kwargs):
            ids = _observe(before, self, args, kwargs)
            try:
                result = await original(self, *args, **kwargs)
            except BaseException as exc:
                _observe(after, self, ids, type(exc).__name__)
                raise
            _observe(after, self, ids)
            return result
    else:
        @functools.wraps(original)
        def wrapped(self, *args, **kwargs):
            ids = _observe(before, self, args, kwargs)
            try:
                result = original(self, *args, **kwargs)
            except BaseException as exc:
                _observe(after, self, ids, type(exc).__name__)
                raise
            _observe(after, self, ids)
            return result
    setattr(cls, name, wrapped)
    _HOOKS.append(label)


def install_hooks():
    """Install before the first request; class hooks cover existing V0 instances."""
    global _INSTALLED
    if _INSTALLED:
        return get_hook_status()
    from vllm.version import __version__
    from vllm.engine.async_llm_engine import AsyncLLMEngine, _AsyncLLMEngine, RequestTracker
    from vllm.engine.llm_engine import LLMEngine
    if __version__ != "0.8.5":
        raise RuntimeError(f"exp26 requires audited vLLM 0.8.5 V0, got {__version__}")
    targets = [(AsyncLLMEngine, "add_request", "add", "request_id"),
               (AsyncLLMEngine, "abort", "abort", "request_id"),
               (AsyncLLMEngine, "_abort", "abort", "request_id"),
               (RequestTracker, "abort_request", "abort", "request_id"),
               (RequestTracker, "process_request_output", "output", "request_output"),
               (LLMEngine, "abort_request", "abort", "request_id"),
               (LLMEngine, "step", "step", "virtual_engine"),
               (_AsyncLLMEngine, "step_async", "step", "virtual_engine"),
               (AsyncLLMEngine, "engine_step", "outer_step", "virtual_engine")]
    # Check every target before making any mutation.
    for cls, name, kind, argument in targets:
        fn = getattr(cls, name)
        sig = inspect.signature(fn)
        if kind in ("add", "abort", "output") and argument not in sig.parameters:
            raise RuntimeError(f"unexpected vLLM signature: {cls.__name__}.{name}{sig}")
    for cls, name, kind, argument in targets:
        _patch(cls, name, kind, argument)
    _INSTALLED = True
    write(dict(event="hooks_installed", vllm_version=__version__, **get_hook_status()))
    return get_hook_status()


def get_hook_status():
    return {"installed": _INSTALLED, "hooks": list(_HOOKS),
            "audit_errors": _ERRORS, "mapped_engine_ids": len(_REQUESTS)}


class AuditMiddleware:
    def __init__(self, app):
        self.app = app
        if not os.environ.get("EXP26_AUDIT_PATH"):
            raise RuntimeError("EXP26_AUDIT_PATH must name an existing writable parent directory")
        install_hooks()

    async def __call__(self, scope, receive, send):
        headers = {k.lower(): v.decode("latin1") for k, v in scope.get("headers", ())}
        if (scope.get("type") != "http" or scope.get("path") != "/v1/chat/completions"
                or not (headers.get(b"x-exp26-request-id") or headers.get(b"x-exp26-attempt-id"))):
            return await self.app(scope, receive, send)
        ctx = {"request_id": headers.get(b"x-exp26-request-id"),
               "attempt_id": headers.get(b"x-exp26-attempt-id"),
               "http_id": uuid.uuid4().hex, "engine_request_ids": set()}
        identity = {k: ctx[k] for k in ("request_id", "attempt_id", "http_id")}
        token = _HTTP.set(ctx)
        incoming, outgoing, returned = bytearray(), bytearray(), bytearray()
        status, error, first = None, None, None
        request_complete, response_complete, disconnected = False, False, False
        started = time.monotonic_ns()
        write(dict(identity, event="http_started", method=scope.get("method"),
                   path=scope["path"], native_x_request_id=headers.get(b"x-request-id")))

        async def recv():
            nonlocal request_complete, disconnected
            message = await receive()
            if message["type"] == "http.request":
                data = message.get("body", b"")
                incoming.extend(data)
                request_complete = not message.get("more_body", False)
                _observe(write, dict(identity, event="http_request_chunk",
                                    body_b64=base64.b64encode(data).decode(),
                                    more_body=message.get("more_body", False)))
            elif message["type"] == "http.disconnect":
                disconnected = True
                write(dict(identity, event="http_disconnect"))
            return message

        async def sent(message):
            nonlocal status, first, response_complete
            data = message.get("body", b"")
            if message["type"] == "http.response.start":
                status = message["status"]
                write(dict(identity, event="http_response_start", status=status))
            if message["type"] == "http.response.body":
                outgoing.extend(data)
                if data and first is None:
                    first = time.monotonic_ns()
                write(dict(identity, event="http_response_chunk", body_b64=base64.b64encode(data).decode(),
                           more_body=message.get("more_body", False), stage="before_send"))
            try:
                await send(message)
            except BaseException as exc:
                write(dict(identity, event="http_send_raised", error=type(exc).__name__))
                raise
            if message["type"] == "http.response.body":
                returned.extend(data)
                response_complete = not message.get("more_body", False)

        try:
            return await self.app(scope, recv, sent)
        except BaseException as exc:
            error = type(exc).__name__
            raise
        finally:
            try:
                write(dict(identity, event="http_finished", component="backend-http", status=status,
                           body=incoming.decode("utf-8", "replace"),
                           request_b64=base64.b64encode(incoming).decode(),
                           request_sha256=hashlib.sha256(incoming).hexdigest(),
                           sse=outgoing.decode("utf-8", "replace"),
                           response_b64=base64.b64encode(outgoing).decode(),
                           response_sha256=hashlib.sha256(outgoing).hexdigest(),
                           send_returned_b64=base64.b64encode(returned).decode(),
                           engine_request_ids=sorted(ctx["engine_request_ids"]),
                           request_complete=request_complete, response_complete=response_complete,
                           disconnect_observed=disconnected, started_ns=started,
                           first_body_ns=first, ended_ns=time.monotonic_ns(), error=error,
                           audit_errors=_ERRORS))
            finally:
                _HTTP.reset(token)
