#!/usr/bin/env python3
"""开环爬坡压测：泊松到达，λ 从 --lam0 线性爬到 --lam1（--secs 秒），再保持 --hold 秒。
同时每秒采一次后端 /metrics（waiting / running / KV 占用）和 GPU 利用率（WSL nvidia-smi）。
输出 <RES>/<name>-<ts>.req.jsonl（每条请求：到达时刻、TTFT、e2e）和 .samp.jsonl（每秒一行采样），汇总 .json。
"""
from __future__ import annotations

import argparse, asyncio, json, random, re, subprocess, time

import aiohttp
from transformers import AutoTokenizer

ap = argparse.ArgumentParser()
ap.add_argument("--name", required=True)
ap.add_argument("--base", default="http://127.0.0.1:8003")
ap.add_argument("--model", default="qwen3-1.7b")
ap.add_argument("--tokenizer", default="/opt/models/Qwen3-1.7B")
ap.add_argument("--res", default="/opt/p2/results")
ap.add_argument("--lam0", type=float, default=0.5)
ap.add_argument("--lam1", type=float, default=2.2)
ap.add_argument("--secs", type=float, default=240)
ap.add_argument("--hold", type=float, default=60)
ap.add_argument("--inp", type=int, default=1024)
ap.add_argument("--out", type=int, default=256)
ap.add_argument("--seed", type=int, default=20260924)
args = ap.parse_args()

tok = AutoTokenizer.from_pretrained(args.tokenizer)
rng = random.Random(args.seed)
VOCAB = min(tok.vocab_size, 150000)
SMI = "/usr/lib/wsl/lib/nvidia-smi"


def prompt(n: int) -> str:
    return tok.decode([rng.randrange(1000, VOCAB) for _ in range(n)])


def lam(t: float) -> float:
    return args.lam0 + (args.lam1 - args.lam0) * min(t / args.secs, 1.0)


async def one(sess, t_arr: float, T0: float, fh, out):
    body = {"model": args.model, "prompt": prompt(args.inp), "max_tokens": args.out, "stream": True, "ignore_eos": True, "temperature": 0}
    rec = {"t_arr": round(t_arr - T0, 3), "lam": round(lam(t_arr - T0), 3), "ttft_ms": None, "e2e_ms": None, "status": None}
    first = last = None
    try:
        async with sess.post(f"{args.base}/v1/completions", json=body) as r:
            rec["status"] = r.status
            async for line in r.content:
                if line.startswith(b"data: ") and not line.startswith(b"data: [DONE]"):
                    now = time.monotonic(); first = first or now; last = now
    except Exception as e:  # noqa: BLE001
        rec["status"] = f"exc:{type(e).__name__}"
    if first:
        rec["ttft_ms"] = round((first - t_arr) * 1e3, 1); rec["e2e_ms"] = round((last - t_arr) * 1e3, 1)
    out.append(rec); fh.write(json.dumps(rec) + "\n"); fh.flush()


async def sampler(sess, T0: float, stop: asyncio.Event, fh):
    pat = {k: re.compile(rf"^vllm:{k}\{{[^}}]*\}} ([\d.e+-]+)", re.M) for k in ("num_requests_waiting", "num_requests_running", "gpu_cache_usage_perc")}
    while not stop.is_set():
        t = time.monotonic() - T0
        row = {"t": round(t, 2), "lam": round(lam(t), 3)}
        try:
            async with sess.get(f"{args.base}/metrics") as r:
                txt = await r.text()
            for k, p in pat.items():
                m = p.search(txt); row[k] = float(m.group(1)) if m else None
        except Exception:  # noqa: BLE001
            pass
        try:
            row["gpu_util"] = float(subprocess.run([SMI, "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=2).stdout.strip())
        except Exception:  # noqa: BLE001
            row["gpu_util"] = None
        fh.write(json.dumps(row) + "\n"); fh.flush()
        await asyncio.sleep(max(0, 1 - ((time.monotonic() - T0) - t)))


async def main():
    ts = time.strftime("%Y%m%d-%H%M%S"); stem = f"{args.res}/{args.name}-{ts}"
    out: list[dict] = []; tasks = []; stop = asyncio.Event()
    conn = aiohttp.TCPConnector(limit=0)
    async with aiohttp.ClientSession(connector=conn, timeout=aiohttp.ClientTimeout(total=900)) as sess:
        with open(stem + ".req.jsonl", "w") as fr, open(stem + ".samp.jsonl", "w") as fs:
            T0 = time.monotonic(); t_start = time.time()
            samp = asyncio.create_task(sampler(sess, T0, stop, fs))
            t = 0.0
            while t < args.secs + args.hold:
                t += rng.expovariate(lam(t))
                await asyncio.sleep(max(0, T0 + t - time.monotonic()))
                tasks.append(asyncio.create_task(one(sess, T0 + t, T0, fr, out)))
            await asyncio.gather(*tasks)
            stop.set(); await samp
    summ = {"name": args.name, "prom_start": int(t_start), "prom_end": int(time.time()), "n": len(out), **{k: getattr(args, k) for k in ("lam0", "lam1", "secs", "hold", "inp", "out")}}
    json.dump(summ, open(stem + ".json", "w"), indent=1); print(json.dumps(summ))


asyncio.run(main())
