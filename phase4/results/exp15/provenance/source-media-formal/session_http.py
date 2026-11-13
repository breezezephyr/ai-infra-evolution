"""Independent loopback aiohttp session/PCM service; no GPU or aiortc imports.

HTTP: POST /sessions {session_id, preferred_owner?}; GET /sessions/{id};
GET /state; POST /workers/{owner}/drain {deadline_ms?}; GET /health.
WS: /session-ws?session_id=ID&owner=a. Attached message includes epoch/audio.
Commands: {type: begin|ack|release, epoch, generation?}. begin uses the fixed
WAV total; ACK includes played_samples_cumulative. All state is in memory.
Audio binary: 3 unsigned big-endian uint32 (seq, offset, sample_count), then
little-endian PCM16 mono. Frames contain <=960 samples at 48kHz (20ms).
Sent frames are paced against a real monotonic timeline, not simulated loss.
"""

import argparse
import asyncio
from contextlib import suppress
import hashlib
import json
import math
from pathlib import Path
import signal
import struct
import time
import wave

from aiohttp import WSMsgType, web

from session import SessionError, SessionRegistry


ROOT = Path(__file__).resolve().parent
HEADER = struct.Struct("!III")


class SessionHTTP:
    def __init__(self, audio, events):
        self.registry = SessionRegistry()
        self.events = events.open("w")
        self.sequence = 0
        self.connections = {}
        self.timers = {}
        self.deadline_tasks = set()
        with wave.open(str(audio), "rb") as source:
            if (source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getcomptype()) != (1, 2, 48000, "NONE"):
                raise ValueError("requires 48kHz mono PCM16 WAV")
            self.total = source.getnframes()
            self.pcm = source.readframes(self.total)
        self.audio = {"sample_rate": 48000, "channels": 1, "sample_width": 2,
                      "total_samples": self.total, "duration_seconds": self.total / 48000,
                      "frame_samples": 960, "header": "!III: seq, sample_offset, sample_count",
                      "pcm_format": "s16le", "path": str(audio),
                      "wav_sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
                      "pcm_sha256": hashlib.sha256(self.pcm).hexdigest()}

    def event(self, event, **data):
        self.sequence += 1
        value = {"sequence": self.sequence, "monotonic_ns": time.monotonic_ns(),
                 "event": event, **data}
        self.events.write(json.dumps(value) + "\n")
        self.events.flush()
        return value

    @staticmethod
    def error_status(error):
        if error.code == "unknown_session":
            return 404
        if error.code.startswith("invalid_") or error.code == "payload_mismatch":
            return 400
        return 409

    async def http(self, request):
        action = request.match_info.route.name
        body = None
        try:
            if request.method == "POST":
                body = await request.json()
                if not isinstance(body, dict):
                    raise SessionError("invalid_request")
            if action == "health":
                value = {"status": "ready", "service": "session-http", "audio": self.audio}
            elif action == "create":
                value = self.registry.create(body["session_id"], body.get("preferred_owner"))
            elif action == "session":
                value = self.registry.get(request.match_info["session_id"])
            elif action == "state":
                value = self.registry.snapshot()
            elif action == "drain":
                owner, deadline = request.match_info["owner"], body.get("deadline_ms")
                if deadline is not None and (type(deadline) not in (int, float)
                                             or not math.isfinite(deadline) or not 0 < deadline <= 60000):
                    raise SessionError("invalid_deadline")
                value = self.registry.drain(owner)
                self.event("drain_requested", owner=owner, deadline_ms=deadline, worker=value)
                if deadline is not None and value["status"] == "draining" and owner not in self.timers:
                    scheduled = self.event("deadline_scheduled", owner=owner, deadline_ms=deadline,
                                           deadline_monotonic_ns=time.monotonic_ns() + int(deadline * 1e6))
                    self.timers[owner] = asyncio.get_running_loop().call_later(
                        deadline / 1000, self.start_deadline, owner, scheduled["deadline_monotonic_ns"])
            self.event("http", method=request.method, path=request.path, request=body, status=200)
            return web.json_response(value)
        except (KeyError, ValueError, TypeError) as error:
            if not isinstance(error, SessionError):
                error = SessionError("invalid_request")
            status = self.error_status(error)
            self.event("http_rejected", method=request.method, path=request.path,
                       request=body, error=error.code, status=status)
            return web.json_response({"error": error.code}, status=status)

    def start_deadline(self, owner, deadline_ns):
        self.timers.pop(owner, None)
        task = asyncio.create_task(self.deadline(owner, deadline_ns))
        self.deadline_tasks.add(task)
        task.add_done_callback(self.deadline_tasks.discard)

    async def deadline(self, owner, deadline_ns):
        worker = self.registry.snapshot()["workers"][owner]
        if worker["status"] != "draining":
            self.event("deadline_skipped", owner=owner, status=worker["status"])
            return
        self.event("deadline_fired", owner=owner, deadline_monotonic_ns=deadline_ns)
        worker = self.registry.force_drain(owner, "drain_deadline_expired")
        self.event("worker_forced", owner=owner, worker=worker)
        for session_id, (epoch, ws) in list(self.connections.items()):
            state = self.registry.get(session_id)
            if state["owner"] == owner and state["status"] == "forced":
                self.event("session_forced", session_id=session_id, old_epoch=epoch, session=state)
                with suppress(ConnectionError):
                    await ws.send_json({"type": "forced", "session": state, "worker": worker})
                    await ws.close(code=4001, message=b"drain_deadline_expired")

    async def send_audio(self, ws, session_id, epoch, generation, offset):
        sequence, started = 0, asyncio.get_running_loop().time()
        initial_offset = offset
        try:
            while offset < self.total:
                target = started + (offset - initial_offset) / 48000
                remaining = target - asyncio.get_running_loop().time()
                if remaining > 0:
                    await asyncio.sleep(remaining)  # actual 20ms media cadence
                count = min(960, self.total - offset)
                payload = self.pcm[offset * 2:(offset + count) * 2]
                await ws.send_bytes(HEADER.pack(sequence, offset, count) + payload)
                self.registry.sent(session_id, epoch, generation, offset + count)
                self.event("audio_sent", session_id=session_id, epoch=epoch,
                           generation=generation, seq=sequence, offset=offset, samples=count,
                           payload_sha256=hashlib.sha256(payload).hexdigest())
                offset += count
                sequence += 1
            state = self.registry.producer_done(session_id, epoch, generation)
            self.event("producer_done", session_id=session_id, epoch=epoch,
                       generation=generation, session=state)
            await ws.send_json({"type": "producer_done", "session": state})
        except (ConnectionError, SessionError) as error:
            self.event("sender_stopped", session_id=session_id, epoch=epoch,
                       generation=generation, reason=getattr(error, "code", type(error).__name__))

    async def websocket(self, request):
        session_id, owner = request.query.get("session_id", ""), request.query.get("owner")
        try:
            epoch = self.registry.attach(session_id, owner)
        except SessionError as error:
            self.event("attach_rejected", session_id=session_id, owner=owner, error=error.code)
            return web.json_response({"error": error.code}, status=self.error_status(error))
        ws = web.WebSocketResponse(heartbeat=15, max_msg_size=65536)
        sender = None
        try:
            await ws.prepare(request)
            self.connections[session_id] = (epoch, ws)
            state = self.registry.get(session_id)
            self.event("attached", session_id=session_id, epoch=epoch, owner=state["owner"])
            await ws.send_json({"type": "attached", "session": state, "audio": self.audio})
            async for message in ws:
                command = None
                try:
                    if message.type != WSMsgType.TEXT:
                        if message.type == WSMsgType.ERROR:
                            break
                        raise SessionError("invalid_command")
                    command = json.loads(message.data)
                    if not isinstance(command, dict):
                        raise SessionError("invalid_command")
                    self.event("command", session_id=session_id, connection_epoch=epoch, command=command)
                    supplied_epoch = command["epoch"]
                    if type(supplied_epoch) is not int:
                        raise SessionError("invalid_epoch")
                    if supplied_epoch != epoch:
                        raise SessionError("stale_epoch")
                    kind = command["type"]
                    if kind == "begin":
                        generation = command["generation"]
                        if command.get("total_samples", self.total) != self.total:
                            raise SessionError("payload_mismatch")
                        state = self.registry.begin_turn(session_id, epoch, generation, self.total)
                        if sender is not None:
                            await sender
                        self.event("begun", session_id=session_id, epoch=epoch,
                                   generation=generation, resume_from=state["resume_from"])
                        await ws.send_json({"type": "begun", "session": state, "audio": self.audio})
                        sender = asyncio.create_task(self.send_audio(ws, session_id, epoch, generation,
                                                                     state["resume_from"]))
                    elif kind == "ack":
                        state = self.registry.acknowledge(session_id, epoch, command["generation"],
                                                          command["played_samples_cumulative"])
                        self.event("acknowledged", session_id=session_id, epoch=epoch,
                                   generation=command["generation"],
                                   played_samples=state["turn"]["played_samples"])
                        await ws.send_json({"type": "acknowledged", "session": state})
                    elif kind == "release":
                        state = self.registry.release(session_id, epoch)
                        owner = state["owner"]
                        worker = self.registry.snapshot()["workers"][owner]
                        self.event("released", session_id=session_id, epoch=epoch, session=state, worker=worker)
                        if worker["status"] == "drained":
                            self.event("worker_drained", owner=owner, worker=worker)
                            handle = self.timers.pop(owner, None)
                            if handle is not None:
                                handle.cancel()
                                self.event("deadline_cancelled", owner=owner)
                        await ws.send_json({"type": "released", "session": state, "worker": worker})
                        await ws.close()
                        break
                    else:
                        raise SessionError("invalid_command")
                except (KeyError, ValueError, TypeError) as error:
                    if not isinstance(error, SessionError):
                        error = SessionError("invalid_command")
                    self.event("command_rejected", session_id=session_id, connection_epoch=epoch,
                               command=command, error=error.code)
                    await ws.send_json({"type": "error", "error": error.code, "epoch": epoch})
        finally:
            if sender is not None:
                sender.cancel()
                with suppress(asyncio.CancelledError, ConnectionError):
                    await sender
            if self.connections.get(session_id, (None,))[0] == epoch:
                self.connections.pop(session_id)
            with suppress(SessionError):
                self.registry.disconnect(session_id, epoch)
                self.event("disconnected", session_id=session_id, epoch=epoch,
                           session=self.registry.get(session_id))
            self.event("connection_closed", session_id=session_id, epoch=epoch)
        return ws

    async def static(self, request):
        return web.FileResponse(ROOT / request.match_info["name"])

    async def close(self):
        for handle in self.timers.values():
            handle.cancel()
        for task in list(self.deadline_tasks):
            task.cancel()
        if self.deadline_tasks:
            await asyncio.gather(*self.deadline_tasks, return_exceptions=True)
        for _, ws in list(self.connections.values()):
            await ws.close(code=1001, message=b"server_shutdown")


@web.middleware
async def cors(request, handler):
    if request.method == "OPTIONS":
        response = web.Response(status=204)
    else:
        response = await handler(request)
    # Allows a browser page hosted by the independent media server to use this
    # local experiment's REST and ES module/worklet resources.
    if not isinstance(response, web.WebSocketResponse):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response


async def serve(args):
    args.events.parent.mkdir(parents=True, exist_ok=True)
    service = SessionHTTP(args.audio.resolve(), args.events.resolve())
    app = web.Application(middlewares=[cors])
    for method, path, name in (
        ("GET", "/health", "health"), ("POST", "/sessions", "create"),
        ("GET", "/sessions/{session_id}", "session"), ("GET", "/state", "state"),
        ("POST", "/workers/{owner}/drain", "drain"),
    ):
        app.router.add_route(method, path, service.http, name=name)
    app.router.add_get("/session-ws", service.websocket)
    app.router.add_get("/{name:session-client\\.js|worklet\\.js}", service.static)
    app.router.add_options("/{tail:.*}", lambda request: web.Response(status=204))
    runner = web.AppRunner(app, access_log=None, shutdown_timeout=2)
    stop = asyncio.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(signum, stop.set)
    try:
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", args.port).start()
        service.event("server_started", bind="127.0.0.1", port=args.port, audio=service.audio)
        print(json.dumps({"ready": True, "bind": "127.0.0.1", "port": args.port}), flush=True)
        await stop.wait()
    finally:
        await service.close()
        await runner.cleanup()
        # Request-handler finally blocks can still log disconnects during
        # runner cleanup. Keep the event file open until handlers have ended.
        service.event("server_stopped", snapshot=service.registry.snapshot())
        service.events.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18146)
    parser.add_argument("--audio", type=Path, default=ROOT / "audio/short.wav")
    parser.add_argument("--events", type=Path, default=ROOT.parent / "results/exp15/sessions/manual-server-events.jsonl")
    asyncio.run(serve(parser.parse_args()))
