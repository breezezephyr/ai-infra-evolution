#!/usr/bin/env python3
"""混发压测：交互路 + 批处理路同车，闭环，按时长跑。每类带自己的 x-priority 头。

  mix.py --name exp6-fcfs --secs 150 \
      --cls inter:1:256:64:1:0.5  --cls batch:7:2048:256:100:0
  --cls 名字:路数:输入:输出:优先级:思考秒

每条请求一行 JSONL 到 <RES>/<name>-<ts>.req.jsonl；汇总 <RES>/<name>-<ts>.json（按类 TTFT / ITL / e2e 分位、完成与错误、输出 tok/s、prom_start/end）。
提示词是随机 token id 解码的文本，每条不同（不让寄存箱命中）。流式，ignore_eos。
--prefix-groups P --prefix-len L：常客模式（exp7），每条 = P 组固定前缀之一 + 输入长度个随机 token；
  --zipf s 按 1/rank^s 选组（0 = 均匀），组号写进逐条记录。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import time

import aiohttp
from transformers import AutoTokenizer

ap = argparse.ArgumentParser()
ap.add_argument("--name", required=True)
ap.add_argument("--base", default="http://127.0.0.1:8010")
ap.add_argument("--model", default="qwen3-1.7b")
ap.add_argument("--tokenizer", default="/opt/models/Qwen3-1.7B")
ap.add_argument("--res", default="/opt/p2/results")
ap.add_argument("--secs", type=float, default=150)
ap.add_argument("--cls", action="append", required=True)
ap.add_argument("--timeout", type=float, default=120)
ap.add_argument("--prefix-groups", type=int, default=0)
ap.add_argument("--prefix-len", type=int, default=3072)
ap.add_argument("--zipf", type=float, default=0)
ap.add_argument("--seed", type=int, default=20260923)
ap.add_argument("--stop-on-503", action="store_true", help="收到 503（排空）后该路停止，不再空转")
args = ap.parse_args()

tok = AutoTokenizer.from_pretrained(args.tokenizer)
rng = random.Random(args.seed)
VOCAB = min(tok.vocab_size, 150000)


def prompt(n: int) -> str:
    return tok.decode([rng.randrange(1000, VOCAB) for _ in range(n)])


PREFIX = [prompt(args.prefix_len) for _ in range(args.prefix_groups)]
WEIGHTS = [1 / (i + 1) ** args.zipf for i in range(args.prefix_groups)]


def pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q / 100 * len(xs)))], 1)


async def one(sess: aiohttp.ClientSession, c: dict, out: list, fh) -> None:
    g = rng.choices(range(args.prefix_groups), WEIGHTS)[0] if PREFIX else None
    body = {"model": args.model, "prompt": (PREFIX[g] if PREFIX else "") + prompt(c["inp"]), "max_tokens": c["out"], "stream": True, "ignore_eos": True, "temperature": 0}
    t0 = time.monotonic()
    rec = {"cls": c["name"], "group": g, "t": round(time.time(), 3), "status": None, "ttft_ms": None, "e2e_ms": None, "n_out": 0}
    stamps: list[float] = []
    try:
        async with sess.post(f"{args.base}/v1/completions", json=body, headers={"x-priority": str(c["prio"])}) as r:
            rec["status"] = r.status
            if r.status == 200:
                async for line in r.content:
                    if line.startswith(b"data: ") and not line.startswith(b"data: [DONE]"):
                        stamps.append(time.monotonic())
            else:
                await r.read()
    except Exception as e:  # noqa: BLE001
        rec["status"] = f"exc:{type(e).__name__}"
    if stamps:
        rec["ttft_ms"] = round((stamps[0] - t0) * 1e3, 1)
        rec["e2e_ms"] = round((stamps[-1] - t0) * 1e3, 1)
        rec["n_out"] = len(stamps)
        rec["itl_ms"] = [round((b - a) * 1e3, 1) for a, b in zip(stamps, stamps[1:])]
    out.append(rec)
    fh.write(json.dumps(rec) + "\n")


async def worker(sess, c, deadline, out, fh) -> None:
    while time.monotonic() < deadline:
        await one(sess, c, out, fh)
        if args.stop_on_503 and out[-1]["status"] == 503:
            break
        if c["think"]:
            await asyncio.sleep(c["think"])


async def main() -> None:
    classes = []
    for s in args.cls:
        n, k, i, o, p, th = s.split(":")
        classes.append(dict(name=n, k=int(k), inp=int(i), out=int(o), prio=int(p), think=float(th)))
    ts = time.strftime("%Y%m%d-%H%M%S")
    stem = f"{args.res}/{args.name}-{ts}"
    out: list[dict] = []
    t_start = time.time()
    deadline = time.monotonic() + args.secs
    conn = aiohttp.TCPConnector(limit=0)
    async with aiohttp.ClientSession(connector=conn, timeout=aiohttp.ClientTimeout(total=args.timeout)) as sess:
        with open(stem + ".req.jsonl", "w") as fh:
            await asyncio.gather(*[worker(sess, c, deadline, out, fh) for c in classes for _ in range(c["k"])])
    t_end = time.time()
    summ = {"name": args.name, "prefix_groups": args.prefix_groups, "prefix_len": args.prefix_len, "zipf": args.zipf, "prom_start": int(t_start), "prom_end": int(t_end), "secs": round(t_end - t_start, 1), "classes": {}}
    for c in classes:
        rs = [r for r in out if r["cls"] == c["name"]]
        ok = [r for r in rs if r["status"] == 200 and r["n_out"] == c["out"]]
        itl = [x for r in ok for x in r["itl_ms"]]
        summ["classes"][c["name"]] = {
            **{k: c[k] for k in ("k", "inp", "out", "prio", "think")},
            "done": len(ok), "err": len(rs) - len(ok),
            "ttft_p50": pct([r["ttft_ms"] for r in ok], 50), "ttft_p90": pct([r["ttft_ms"] for r in ok], 90), "ttft_p99": pct([r["ttft_ms"] for r in ok], 99),
            "itl_p50": pct(itl, 50), "itl_p99": pct(itl, 99),
            "e2e_p50": pct([r["e2e_ms"] for r in ok], 50),
            "out_tok_s": round(sum(r["n_out"] for r in ok) / (t_end - t_start), 1),
        }
    json.dump(summ, open(stem + ".json", "w"), indent=1, ensure_ascii=False)
    print(json.dumps(summ, ensure_ascii=False, indent=1))


asyncio.run(main())
