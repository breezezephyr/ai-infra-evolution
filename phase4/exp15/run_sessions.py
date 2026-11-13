"""Run real loopback HTTP/WS session checks; ACKs are synthetic, not playback.

Uses the current interpreter (run with /tmp/exp14-local-env/bin/python -B).
Owns one session_http.py child, stops it in finally, and probes port closure.
All waits observe network/process state; only server media pacing and the
server's actual drain deadline determine the experiment's timing.
"""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import sys
import time
import traceback
import wave
from datetime import datetime, timezone

import aiohttp


ROOT = Path(__file__).resolve().parent
HEADER = struct.Struct("!III")


def port_open(port):
    with socket.socket() as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


class Experiment:
    def __init__(self, output, port):
        self.output, self.port = output, port
        self.base = f"http://127.0.0.1:{port}"
        self.log = (output / "client-events.jsonl").open("w")
        self.scenario = "startup"
        self.checks = []
        self.summary = {"ack_source": "python_synthetic_control_only",
                        "audio_played": False, "browser_playback_latency": None,
                        "base_url": self.base, "checks": self.checks}
        with wave.open(str(ROOT / "audio/short.wav"), "rb") as audio:
            self.rate, self.total = audio.getframerate(), audio.getnframes()
            self.pcm = audio.readframes(self.total)
        self.summary["audio"] = {"sample_rate": self.rate, "total_samples": self.total,
                                 "pcm_sha256": hashlib.sha256(self.pcm).hexdigest()}

    def event(self, event, **data):
        self.log.write(json.dumps({"monotonic_ns": time.monotonic_ns(),
                                   "scenario": self.scenario, "event": event, **data}) + "\n")
        self.log.flush()

    def check(self, name, condition, **details):
        entry = {"scenario": self.scenario, "assertion": name,
                 "passed": bool(condition), **details}
        self.checks.append(entry)
        self.event("assertion", **{k: v for k, v in entry.items() if k != "scenario"})
        if not condition:
            raise AssertionError(entry)

    async def http(self, method, path, body=None, status=200):
        async with self.client.request(method, self.base + path, json=body) as response:
            value = await response.json()
            self.event("http", method=method, path=path, request=body,
                       status=response.status, response=value)
            self.check(f"HTTP {method} {path}: {status}", response.status == status,
                       actual_status=response.status)
            return value

    async def connect(self, session_id, owner, rejected_status=None):
        url = self.base + "/session-ws"
        try:
            ws = await self.client.ws_connect(url, params={"session_id": session_id, "owner": owner})
        except aiohttp.WSServerHandshakeError as error:
            self.event("ws_handshake_rejected", session_id=session_id, owner=owner, status=error.status)
            self.check("WS attach rejected before upgrade", error.status == rejected_status,
                       expected_status=rejected_status, actual_status=error.status)
            return None
        if rejected_status is not None:
            await ws.close()
            self.check("WS attach should reject", False)
        peer = Peer(self, ws, session_id)
        attached = await peer.until("attached")
        peer.epoch = attached["session"]["epoch"]
        self.check("WS attached to requested sticky owner", attached["session"]["owner"] == owner)
        return peer

    async def disconnected(self, session_id):
        async with asyncio.timeout(3):
            while True:
                state = await self.http("GET", f"/sessions/{session_id}")
                if not state["connected"]:
                    return state
                await asyncio.sleep(0.01)  # readiness polling, never playback evidence

    async def scenarios(self):
        health = self.summary["health"]["audio"]
        self.check("HTTP metadata identifies the exact PCM payload",
                   health["sample_rate"] == self.rate and health["total_samples"] == self.total
                   and health["pcm_sha256"] == self.summary["audio"]["pcm_sha256"])
        for resource in ("session-client.js", "worklet.js"):
            async with self.client.get(self.base + "/" + resource) as response:
                source = await response.text()
                self.event("browser_resource", path=resource, status=response.status,
                           cors=response.headers.get("Access-Control-Allow-Origin"),
                           sha256=hashlib.sha256(source.encode()).hexdigest())
                self.check("browser resource served with cross-origin access: " + resource,
                           response.status == 200 and bool(source)
                           and response.headers.get("Access-Control-Allow-Origin") == "*")
        async with self.client.options(self.base + "/sessions") as response:
            self.check("browser REST preflight accepted", response.status == 204
                       and response.headers.get("Access-Control-Allow-Origin") == "*")
        self.scenario = "sticky_multi_turn_and_wrong_owner"
        created = await self.http("POST", "/sessions", {"session_id": "sticky", "preferred_owner": "a"})
        self.check("explicit owner a", created["owner"] == "a")
        await self.http("POST", "/sessions", {"session_id": "resume", "preferred_owner": "a"})
        wrong = await self.http("POST", "/sessions", {"session_id": "sticky", "preferred_owner": "b"}, 409)
        self.check("wrong owner code", wrong["error"] == "wrong_owner")
        await self.connect("sticky", "b", 409)
        sticky = await self.connect("sticky", "a")
        await self.connect("sticky", "a", 409)
        for generation in ("turn-1", "turn-2"):
            await sticky.begin(generation)
            await sticky.finish()
            if generation == "turn-1":
                await sticky.ack(self.total)
        state = await self.http("GET", "/sessions/sticky")
        self.check("same owner and epoch across two turns", state["owner"] == "a" and state["epoch"] == sticky.epoch)
        self.check("second turn sent and producer_done without fake playback",
                   state["turn"]["producer_done"] and state["turn"]["sent_samples"] == self.total
                   and state["turn"]["played_samples"] == 0)

        self.scenario = "drain_rejects_new_and_waits_for_ack"
        draining = await self.http("POST", "/workers/a/drain", {"deadline_ms": 15000})
        self.check("a begins draining", draining["status"] == "draining")
        refused = await self.http("POST", "/sessions", {"session_id": "blocked", "preferred_owner": "a"}, 409)
        self.check("draining owner rejects creation", refused["error"] == "worker_unavailable")
        routed = await self.http("POST", "/sessions", {"session_id": "forced"})
        self.check("automatic new session routes to b", routed["owner"] == "b")
        sticky_state = await self.http("POST", "/sessions", {"session_id": "sticky"})
        self.check("existing session remains sticky during drain", sticky_state["owner"] == "a")
        await sticky.send("release")
        rejected = await sticky.until("error")
        self.check("sent-complete release is refused without ACK", rejected["error"] == "turn_incomplete")
        state = await self.http("GET", "/state")
        self.check("withheld ACK never marks drained", state["workers"]["a"]["status"] == "draining")
        await sticky.ack(self.total)
        await sticky.release()
        state = await self.http("GET", "/state")
        self.check("one release does not drain other retained session",
                   state["workers"]["a"]["status"] == "draining"
                   and state["workers"]["a"]["session_ids"] == ["resume"])

        self.scenario = "disconnect_resume_epoch_and_stale_ack"
        first = await self.connect("resume", "a")
        await first.begin("resume-turn")
        while first.end < 24000:
            await first.receive()
        played = 9600
        await first.ack(played)
        await first.ws.close()
        first.save("partial")
        state = await self.disconnected("resume")
        self.check("disconnect retains unfinished sent/played state",
                   state["turn"]["played_samples"] == played
                   and state["turn"]["sent_samples"] >= first.end and state["status"] == "active")
        second = await self.connect("resume", "a")
        self.check("reconnect advances epoch", second.epoch == first.epoch + 1,
                   old_epoch=first.epoch, new_epoch=second.epoch)
        begun = await second.begin("resume-turn", expected_offset=played)
        self.check("resume begins at played, not sent", begun["session"]["resume_from"] == played,
                   resume_from=begun["session"]["resume_from"], old_sent=state["turn"]["sent_samples"])
        await second.send("ack", epoch=first.epoch, played_samples_cumulative=played + 960)
        rejected = await second.until("error")
        self.check("old epoch ACK is rejected over actual WS", rejected["error"] == "stale_epoch")
        state = await self.http("GET", "/sessions/resume")
        self.check("old ACK leaves playback offset unchanged", state["turn"]["played_samples"] == played)
        await second.finish()
        self.check("replay begins exactly at retained played offset", second.first_offset == played)
        state = await self.http("GET", "/state")
        self.check("replay sent-complete still waits for ACK", state["workers"]["a"]["status"] == "draining")
        await second.ack(self.total)
        await second.release()
        state = await self.http("GET", "/state")
        self.check("all playback ACKs and releases produce normal drained",
                   state["workers"]["a"]["status"] == "drained"
                   and state["workers"]["a"]["active_sessions"] == 0
                   and state["sessions"]["resume"]["status"] == "released")

        self.scenario = "real_deadline_force_preserves_unplayed"
        forced = await self.connect("forced", "b")
        await forced.begin("force-turn")
        await forced.finish()
        played = 24000
        await forced.ack(played)
        await self.http("POST", "/workers/b/drain", {"deadline_ms": 200})
        notification = await forced.until("forced")
        state = await self.http("GET", "/state")
        terminal = state["sessions"]["forced"]
        self.check("real deadline produces explicit forced, never normal drained",
                   notification["session"]["status"] == "forced"
                   and state["workers"]["b"]["status"] == "forced"
                   and state["workers"]["b"]["drained"] is False)
        self.check("force records exact unplayed and leaves played unchanged",
                   terminal["unplayed_samples"] == self.total - played
                   and terminal["sent_unplayed_samples"] == self.total - played
                   and terminal["turn"]["played_samples"] == played
                   and terminal["turn"]["producer_done"] is True,
                   total_samples=self.total, played_samples=played,
                   unplayed_samples=terminal["unplayed_samples"])
        self.check("force invalidates old epoch", terminal["epoch"] > forced.epoch)
        await forced.ws.close()
        await self.connect("forced", "b", 409)
        events = [json.loads(line) for line in (self.output / "server-events.jsonl").read_text().splitlines()]
        scheduled = next(e for e in events if e["event"] == "deadline_scheduled" and e["owner"] == "b")
        fired = next(e for e in events if e["event"] == "deadline_fired" and e["owner"] == "b")
        self.check("deadline is a real monotonic-clock timer",
                   fired["monotonic_ns"] >= scheduled["deadline_monotonic_ns"],
                   scheduled_ns=scheduled["monotonic_ns"], fired_ns=fired["monotonic_ns"],
                   elapsed_ms=(fired["monotonic_ns"] - scheduled["monotonic_ns"]) / 1e6)
        self.check("normal drain cancels its outstanding deadline",
                   any(e["event"] == "deadline_cancelled" and e["owner"] == "a" for e in events)
                   and not any(e["event"] == "deadline_fired" and e["owner"] == "a" for e in events))
        self.summary["final_state"] = state


class Peer:
    def __init__(self, experiment, ws, session_id):
        self.experiment, self.ws, self.session_id = experiment, ws, session_id
        self.epoch = None
        self.generation = None
        self.end = 0
        self.seq = 0
        self.first_offset = None
        self.chunks = []

    async def send(self, kind, **data):
        value = {"type": kind, "epoch": self.epoch, **data}
        if kind in ("begin", "ack"):
            value.setdefault("generation", self.generation)
        self.experiment.event("ws_send", session_id=self.session_id, message=value)
        await self.ws.send_json(value)

    async def receive(self):
        message = await self.ws.receive(timeout=10)
        if message.type == aiohttp.WSMsgType.BINARY:
            if len(message.data) < HEADER.size:
                raise AssertionError("truncated binary header")
            seq, offset, count = HEADER.unpack_from(message.data)
            pcm = message.data[HEADER.size:]
            correct = (seq == self.seq and offset == self.end and len(pcm) == count * 2
                       and 0 < count <= 960
                       and pcm == self.experiment.pcm[offset * 2:(offset + count) * 2])
            self.experiment.event("ws_audio", session_id=self.session_id, epoch=self.epoch,
                                  generation=self.generation, seq=seq, offset=offset,
                                  samples=count, payload_sha256=hashlib.sha256(pcm).hexdigest(),
                                  source_matches=correct)
            if not correct:
                raise AssertionError("noncontiguous or corrupted actual audio")
            if self.first_offset is None:
                self.first_offset = offset
            self.seq += 1
            self.end += count
            self.chunks.append(pcm)
            return {"type": "audio"}
        if message.type == aiohttp.WSMsgType.TEXT:
            value = json.loads(message.data)
            self.experiment.event("ws_receive", session_id=self.session_id, message=value)
            return value
        raise RuntimeError(f"WS closed/error before expected event: {message.type} {message.data}")

    async def until(self, kind):
        while True:
            value = await self.receive()
            if value["type"] == kind:
                return value
            if value["type"] == "error":
                raise AssertionError(value)

    async def begin(self, generation, expected_offset=0):
        self.generation = generation
        self.end, self.seq, self.first_offset, self.chunks = expected_offset, 0, None, []
        await self.send("begin")
        return await self.until("begun")

    def save(self, suffix="complete"):
        name = f"{self.session_id}-{self.generation}-epoch{self.epoch}-{suffix}.pcm"
        (self.experiment.output / name).write_bytes(b"".join(self.chunks))
        return name

    async def finish(self):
        value = await self.until("producer_done")
        self.experiment.check("received complete original PCM or exact resume suffix",
                              self.end == self.experiment.total
                              and value["session"]["turn"]["producer_done"] is True,
                              frames=self.seq, first_offset=self.first_offset, end=self.end,
                              pcm_file=self.save())
        return value

    async def ack(self, played):
        await self.send("ack", played_samples_cumulative=played)
        return await self.until("acknowledged")

    async def release(self):
        await self.send("release")
        value = await self.until("released")
        await self.ws.close()
        return value


async def run(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    experiment = Experiment(output, args.port)
    process = None
    succeeded = False
    stdout = (output / "server-stdout.log").open("w")
    initially_open = port_open(args.port)
    try:
        experiment.check("dedicated port initially closed", not initially_open)
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-B", str(ROOT / "session_http.py"), "--port", str(args.port),
            "--events", str(output / "server-events.jsonl"), stdout=stdout,
            stderr=asyncio.subprocess.STDOUT, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        experiment.summary["owned_server_pid"] = process.pid
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as client:
            experiment.client = client
            async with asyncio.timeout(8):
                while True:
                    if process.returncode is not None:
                        raise RuntimeError(f"server exited {process.returncode}; see server-stdout.log")
                    try:
                        async with client.get(experiment.base + "/health") as response:
                            if response.status == 200:
                                experiment.summary["health"] = await response.json()
                                break
                    except aiohttp.ClientConnectionError:
                        pass
                    await asyncio.sleep(0.03)  # startup polling only
            await experiment.scenarios()
            succeeded = True
    except Exception as error:
        experiment.summary["error"] = str(error)
        experiment.summary["traceback"] = traceback.format_exc()
        experiment.event("experiment_failed", error=str(error))
    finally:
        experiment.scenario = "cleanup"
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 4)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        stdout.close()
        closed = not port_open(args.port)
        experiment.summary["cleanup"] = {"owned_server_exit_code": process.returncode if process else None,
                                          "port": args.port, "port_closed": closed,
                                          "monotonic_ns": time.monotonic_ns()}
        experiment.event("cleanup", **experiment.summary["cleanup"])
        experiment.summary["passed"] = succeeded and closed
        (output / "summary.json").write_text(json.dumps(experiment.summary, indent=2) + "\n")
        experiment.log.close()
        print(json.dumps({"output": str(output), "passed": experiment.summary["passed"],
                          "checks": len(experiment.checks), "port_closed": closed}))
    return 0 if experiment.summary["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18146)
    default = ROOT.parent / "results/exp15/sessions" / datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%S%fZ")
    parser.add_argument("--output", type=Path, default=default)
    raise SystemExit(asyncio.run(run(parser.parse_args())))
