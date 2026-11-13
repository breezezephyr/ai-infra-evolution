#!/usr/bin/env python3
"""P3 实验网关：:8010 → vLLM :8003。站台上的那道门。

四个开关（环境变量，改 /etc/default/p2-gw 后 systemctl restart p2-gw）：
  GW_MODE      pass   透传，只记账（基线）
               reject 按 token 预算准入，放不下直接 429（网关拒绝）
               queue  按 token 预算准入，放不下在网关排队，超过 GW_QUEUE_WAIT 秒 503（站台限时）
  GW_BUDGET    车上同时允许的 token 数（in + max_tokens 之和），默认 12000（13,184 座位留 10% 余量）
  GW_TTFT      首字期限秒，>0 时后端在期限内没吐出第一块就 504 并断开（两种超时之一）
  GW_PRIORITY  1 时排队按 x-priority 头（小的先上，默认 100）出队，否则 FCFS
  GW_BACKENDS  逗号分隔的后端端口（exp7 双实例 8004,8005），缺省 = GW_BACKEND
  GW_ROUTE     rr 轮询 / hash 按 prompt 前 GW_HASH_CHARS 字符哈希（同一常客总去同一辆车）
               / bounded 哈希但目标车在途数 > GW_BOUND × 平均 时改去最空的车（命中 vs 均衡）
  排空（P3b exp10）：POST /gw/drain?deadline=秒 → 新请求一律 503 + Retry-After；在途的等到期限，到期强制断开后端连接
               （vLLM 随之 abort）并记下已发出的字数；/gw/undrain 恢复
  GW_RESERVE   给高优（x-priority < 100）留的座位 token 数：低优只能用 BUDGET − RESERVE（优先级只管顺序，不留座位）
估算 token：POST 后端 /tokenize 数 prompt，加 max_tokens。每条请求落一行 JSONL 到 GW_LOG。
/metrics 暴露 gw_* 指标（Prometheus 文本格式），/gw/stats 给人看。
只依赖标准库；HTTP 解析/转发骨架取自 /opt/gpu-router/proxy.py。
"""
from __future__ import annotations

import asyncio
import heapq
import itertools
import json
import math
import os
import time
import zlib
from dataclasses import dataclass, field

LISTEN = os.environ.get("GW_HOST", "127.0.0.1")
PORT = int(os.environ.get("GW_PORT", "8010"))
BACKEND = int(os.environ.get("GW_BACKEND", "8003"))
MODE = os.environ.get("GW_MODE", "pass")
BUDGET = int(os.environ.get("GW_BUDGET", "12000"))
TTFT = float(os.environ.get("GW_TTFT", "0"))
QUEUE_WAIT = float(os.environ.get("GW_QUEUE_WAIT", "10"))
PRIORITY = os.environ.get("GW_PRIORITY", "0") == "1"
RESERVE = int(os.environ.get("GW_RESERVE", "0"))
BACKENDS = [int(x) for x in os.environ.get("GW_BACKENDS", str(BACKEND)).split(",")]
ROUTE = os.environ.get("GW_ROUTE", "rr")
HASH_CHARS = int(os.environ.get("GW_HASH_CHARS", "512"))
BOUND = float(os.environ.get("GW_BOUND", "1.25"))
LOG = os.environ.get("GW_LOG", "/opt/p2/results/gw.jsonl")
DEFAULT_PRIO = 100

HOP = {"connection", "keep-alive", "te", "trailers", "transfer-encoding", "upgrade", "proxy-connection", "host", "content-length"}


# ---------- 准入：纯逻辑，可单测 ----------
@dataclass(order=True)
class _Waiter:
    prio: int
    seq: int
    tokens: int = field(compare=False)
    fut: asyncio.Future = field(compare=False)


class Admission:
    """记着车上的 token 数；放得下就上，放不下按 mode 拒绝或排队。"""

    def __init__(self, mode: str, budget: int, priority: bool, reserve: int = 0) -> None:
        self.mode, self.budget, self.priority, self.reserve = mode, budget, priority, reserve
        self.inflight_tokens = 0
        self.inflight_reqs = 0
        self.queue: list[_Waiter] = []
        self._seq = itertools.count()
        self.counters = {"admitted": 0, "rejected": 0, "queue_timeout": 0, "ttft_timeout": 0, "backend_error": 0}

    def fits(self, tokens: int, prio: int = 0) -> bool:
        cap = self.budget - (self.reserve if prio >= DEFAULT_PRIO else 0)
        return self.inflight_tokens + tokens <= cap

    def _take(self, tokens: int) -> None:
        self.inflight_tokens += tokens
        self.inflight_reqs += 1
        self.counters["admitted"] += 1

    async def acquire(self, tokens: int, prio: int, max_wait: float) -> str:
        """返回 admit / reject / queue_timeout。admit 之后必须 release。"""
        if self.mode == "pass":
            self._take(tokens)
            return "admit"
        if self.fits(tokens, prio) and not self.queue:
            self._take(tokens)
            return "admit"
        if self.mode == "reject":
            self.counters["rejected"] += 1
            return "reject"
        w = _Waiter(prio if self.priority else DEFAULT_PRIO, next(self._seq), tokens, asyncio.get_running_loop().create_future())
        heapq.heappush(self.queue, w)
        self._drain()  # 高优新来的可能排到队首且放得下：不必等下一次有人下车
        try:
            await asyncio.wait_for(w.fut, max_wait)
            return "admit"
        except asyncio.TimeoutError:
            self.queue.remove(w)
            heapq.heapify(self.queue)
            self.counters["queue_timeout"] += 1
            self._drain()
            return "queue_timeout"

    def release(self, tokens: int) -> None:
        self.inflight_tokens -= tokens
        self.inflight_reqs -= 1
        self._drain()

    def _drain(self) -> None:
        # 队首放得下就放，放不下就等（不跳过队首：保住 FCFS / 优先级语义，避免大件饿死）
        while self.queue and self.fits(self.queue[0].tokens, self.queue[0].prio):
            w = heapq.heappop(self.queue)
            if not w.fut.done():
                self._take(w.tokens)
                w.fut.set_result(True)


class Router:
    """多辆车时选哪辆。纯逻辑，可单测。"""

    def __init__(self, backends: list[int], route: str, hash_chars: int = 512, bound: float = 1.25) -> None:
        self.backends, self.route, self.hash_chars, self.bound = backends, route, hash_chars, bound
        self.inflight = {b: 0 for b in backends}
        self._rr = itertools.count()

    def pick(self, prompt: str) -> tuple[int, bool]:
        """返回 (后端端口, 是否因超载被改道)。"""
        n = len(self.backends)
        if n == 1:
            return self.backends[0], False
        if self.route == "rr":
            return self.backends[next(self._rr) % n], False
        home = self.backends[zlib.crc32(prompt[: self.hash_chars].encode()) % n]
        if self.route == "bounded":
            cap = math.ceil(self.bound * (sum(self.inflight.values()) + 1) / n)  # bounded-load 哈希：每车上限 ⌈c·平均⌉
            if self.inflight[home] + 1 > cap:
                return min(self.backends, key=lambda b: self.inflight[b]), True
        return home, False


# ---------- HTTP 小工具 ----------
def parse_head(raw: bytes) -> tuple[str, str, list[tuple[str, str]]]:
    lines = raw.decode("iso-8859-1").split("\r\n")
    method, path, _ = lines[0].split(" ", 2)
    hs = [(k, v.strip()) for k, v in (l.split(":", 1) for l in lines[1:] if l)]
    return method, path, hs


async def read_head(reader: asyncio.StreamReader) -> bytes | None:
    buf = bytearray()
    while True:
        line = await reader.readline()
        if not line:
            return bytes(buf) or None
        buf += line
        if line in (b"\r\n", b"\n"):
            return bytes(buf)


async def read_body(reader: asyncio.StreamReader, hs: dict[str, str]) -> bytes:
    if "chunked" in hs.get("transfer-encoding", "").lower():
        parts = []
        while True:
            size = int((await reader.readline()).split(b";", 1)[0].strip() or b"0", 16)
            if size == 0:
                await reader.readline()
                return b"".join(parts)
            parts.append(await reader.readexactly(size))
            await reader.readline()
    n = int(hs.get("content-length", "0") or 0)
    return await reader.readexactly(n) if n > 0 else b""


def backend_head(method: str, path: str, hs: list[tuple[str, str]], body: bytes) -> bytes:
    out = [f"{method} {path} HTTP/1.1", f"Host: 127.0.0.1:{BACKEND}", "Connection: close"]
    out += [f"{k}: {v}" for k, v in hs if k.lower() not in HOP]
    out.append(f"Content-Length: {len(body)}")
    return ("\r\n".join(out) + "\r\n\r\n").encode()


def resp(status: int, reason: str, payload: dict | bytes, ctype: str = "application/json", extra: list[tuple[str, str]] = ()) -> bytes:
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    hs = [f"HTTP/1.1 {status} {reason}", f"Content-Type: {ctype}", f"Content-Length: {len(body)}", "Connection: close", *(f"{k}: {v}" for k, v in extra)]
    return ("\r\n".join(hs) + "\r\n\r\n").encode() + body


async def backend_call(head: bytes, body: bytes, port: int | None = None) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    r, w = await asyncio.open_connection("127.0.0.1", port or BACKENDS[0])
    w.write(head + body)
    await w.drain()
    return r, w


async def count_tokens(prompt: str) -> int:
    body = json.dumps({"prompt": prompt}).encode()
    r, w = await backend_call(backend_head("POST", "/tokenize", [("Content-Type", "application/json")], body), body)
    try:
        raw = await r.read()
    finally:
        w.close()
    return int(json.loads(raw.split(b"\r\n\r\n", 1)[1])["count"])


def estimate_from_body(body: bytes) -> tuple[str, int]:
    """返回 (prompt 文本, max_tokens)。chat 请求把 messages 拼起来数。"""
    d = json.loads(body)
    p = d.get("prompt")
    if p is None and "messages" in d:
        p = "\n".join(str(m.get("content", "")) for m in d["messages"])
    if isinstance(p, list):
        p = "\n".join(map(str, p))
    return p or "", int(d.get("max_tokens") or d.get("max_completion_tokens") or 16)


# ---------- 主流程 ----------
class Gateway:
    def __init__(self) -> None:
        self.adm = Admission(MODE, BUDGET, PRIORITY, RESERVE)
        self.router = Router(BACKENDS, ROUTE, HASH_CHARS, BOUND)
        self.draining: float | None = None  # 开始排空的 monotonic 时刻
        self.live: dict[int, dict] = {}     # 在途请求：id -> {bw, chunks, cut}
        self._ids = itertools.count()
        self.log = open(LOG, "a", buffering=1)
        self.ttft_hist: list[float] = []

    async def _drain_cut(self, deadline: float) -> None:
        await asyncio.sleep(deadline)
        for st in list(self.live.values()):
            st["cut"] = True
            try:
                st["bw"].close()
            except Exception:  # noqa: BLE001
                pass

    def record(self, **kv) -> None:
        kv["ts"] = round(time.time(), 3)
        self.log.write(json.dumps(kv, ensure_ascii=False) + "\n")

    def metrics(self) -> bytes:
        a = self.adm
        lines = [f"gw_inflight_tokens {a.inflight_tokens}", f"gw_inflight_requests {a.inflight_reqs}", f"gw_queue_length {len(a.queue)}", f"gw_budget_tokens {a.budget}"]
        lines += [f'gw_requests_total{{outcome="{k}"}} {v}' for k, v in a.counters.items()]
        return ("\n".join(lines) + "\n").encode()

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        tokens = 0
        admitted = False
        routed: int | None = None
        rid: int | None = None
        bw: asyncio.StreamWriter | None = None
        try:
            raw = await read_head(reader)
            if not raw:
                return
            method, path, hs = parse_head(raw)
            hl = {k.lower(): v for k, v in hs}
            body = await read_body(reader, hl)
            p = path.split("?", 1)[0].rstrip("/")

            if p == "/metrics" and method == "GET":
                writer.write(resp(200, "OK", self.metrics(), "text/plain; version=0.0.4"))
                return
            if p == "/gw/stats":
                a = self.adm
                writer.write(resp(200, "OK", {"mode": a.mode, "budget": a.budget, "reserve": a.reserve, "route": ROUTE, "backends_inflight": self.router.inflight, "ttft_deadline": TTFT, "inflight_tokens": a.inflight_tokens, "inflight_requests": a.inflight_reqs, "queue": len(a.queue), **a.counters}))
                return
            if p == "/gw/drain":
                q = dict(kv.split("=", 1) for kv in path.split("?", 1)[1].split("&")) if "?" in path else {}
                dl = float(q.get("deadline", "30"))
                self.draining = time.monotonic()
                asyncio.create_task(self._drain_cut(dl))
                self.record(outcome="drain_start", deadline_s=dl, inflight=len(self.live))
                writer.write(resp(200, "OK", {"draining": True, "deadline_s": dl, "inflight": len(self.live)}))
                return
            if p == "/gw/undrain":
                self.draining = None
                writer.write(resp(200, "OK", {"draining": False}))
                return
            if p in ("/v1/completions", "/v1/chat/completions") and self.draining is not None:
                self.record(outcome="drain_reject")
                writer.write(resp(503, "Service Unavailable", {"error": {"message": "draining", "type": "draining"}}, extra=[("Retry-After", "5")]))
                return
            if p not in ("/v1/completions", "/v1/chat/completions"):
                r, bw = await backend_call(backend_head(method, path, hs, body), body)
                await self.pump(r, writer)
                return

            # --- 站台：估行李，决定上不上 ---
            t0 = time.monotonic()
            prompt, max_tokens = estimate_from_body(body)
            n_in = await count_tokens(prompt) if self.adm.mode != "pass" else -1
            tokens = (n_in if n_in >= 0 else 0) + max_tokens
            prio = int(hl.get("x-priority", DEFAULT_PRIO))
            t_est = time.monotonic()
            decision = await self.adm.acquire(tokens, prio, QUEUE_WAIT)
            t_adm = time.monotonic()
            base = dict(mode=self.adm.mode, n_in=n_in, max_tokens=max_tokens, tokens=tokens, prio=prio, est_ms=round((t_est - t0) * 1e3, 1), queue_ms=round((t_adm - t_est) * 1e3, 1), inflight_tokens=self.adm.inflight_tokens, queue_len=len(self.adm.queue))
            if decision == "reject":
                self.record(outcome="reject", **base)
                writer.write(resp(429, "Too Many Requests", {"error": {"message": f"token budget full: inflight {self.adm.inflight_tokens} + {tokens} > {self.adm.budget}", "type": "rate_limit"}}, extra=[("Retry-After", "1")]))
                return
            if decision == "queue_timeout":
                self.record(outcome="queue_timeout", **base)
                writer.write(resp(503, "Service Unavailable", {"error": {"message": f"queued {QUEUE_WAIT}s, still no seat", "type": "queue_timeout"}}, extra=[("Retry-After", "1")]))
                return
            admitted = True

            # --- 上车：选车，转发，盯首字 ---
            port, spilled = self.router.pick(prompt)
            base.update(backend=port, spilled=spilled)
            self.router.inflight[port] += 1
            routed = port
            r, bw = await backend_call(backend_head(method, path, hs, body), body, port)
            rid = next(self._ids); st = {"bw": bw, "chunks": 0, "cut": False}; self.live[rid] = st
            head = await r.readuntil(b"\r\n\r\n")
            status = int(head.split(b" ", 2)[1])
            try:
                first = await asyncio.wait_for(r.read(65536), TTFT) if TTFT > 0 else await r.read(65536)
            except asyncio.TimeoutError:
                self.adm.counters["ttft_timeout"] += 1
                self.record(outcome="ttft_timeout", status=status, ttft_ms=round(TTFT * 1e3), **base)
                writer.write(resp(504, "Gateway Timeout", {"error": {"message": f"no first token within {TTFT}s", "type": "ttft_timeout"}}))
                return
            ttft_ms = round((time.monotonic() - t_adm) * 1e3, 1)
            writer.write(head + first)
            await writer.drain()
            st["chunks"] += first.count(b"data: ")
            try:
                await self.pump(r, writer, st)
            except Exception:  # noqa: BLE001
                if not st["cut"]:
                    raise
            self.live.pop(rid, None)
            if status >= 400:
                self.adm.counters["backend_error"] += 1
            if st["cut"]:
                self.record(outcome="drain_cut", status=status, ttft_ms=ttft_ms, chunks=st["chunks"], total_ms=round((time.monotonic() - t_adm) * 1e3, 1), **base)
                return
            self.record(outcome="ok" if status < 400 else "backend_error", status=status, ttft_ms=ttft_ms, chunks=st["chunks"], total_ms=round((time.monotonic() - t_adm) * 1e3, 1),
                        after_drain_ms=round((time.monotonic() - self.draining) * 1e3) if self.draining is not None else None, **base)
        except Exception as exc:  # noqa: BLE001
            try:
                writer.write(resp(502, "Bad Gateway", {"error": {"message": repr(exc), "type": "gateway_error"}}))
            except Exception:  # noqa: BLE001
                pass
        finally:
            if admitted:
                self.adm.release(tokens)
            if routed is not None:
                self.router.inflight[routed] -= 1
            if rid is not None:
                self.live.pop(rid, None)
            for w in (bw, writer):
                if w is not None:
                    try:
                        w.close()
                        await w.wait_closed()
                    except Exception:  # noqa: BLE001
                        pass

    @staticmethod
    async def pump(r: asyncio.StreamReader, writer: asyncio.StreamWriter, st: dict | None = None) -> None:
        while chunk := await r.read(65536):
            if st is not None:
                st["chunks"] += chunk.count(b"data: ")
            writer.write(chunk)
            await writer.drain()


async def main() -> None:
    gw = Gateway()
    server = await asyncio.start_server(gw.handle, LISTEN, PORT)
    print(f"p2-gw {LISTEN}:{PORT} -> {BACKENDS} route={ROUTE} mode={MODE} budget={BUDGET} ttft={TTFT}s queue_wait={QUEUE_WAIT}s priority={PRIORITY} log={LOG}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
