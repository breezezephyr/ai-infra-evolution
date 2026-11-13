#!/usr/bin/env python3
"""exp11：用现网 embedding 对 FAQ 改写做最近邻，扫 θ。

缓存键 = faq_seed 的 100 条原问。查询 = rewrites.jsonl 的同义改写和对抗改写。
命中 = 与最近的原问余弦 ≥ θ。答错 = 命中了，但那条不是 gold。
向量已是单位向量，余弦 = 点积。在 DARYU 上跑（embedding 只听 127.0.0.1:8001）。

  python3 sweep.py --out /opt/p2/exp11/sweep.json
"""
import argparse, json, os, time, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = "qwen3-embedding-0.6b"
THETAS = [round(0.80 + 0.02 * i, 2) for i in range(10)]

def embed(base, texts, batch=64):
    out = [None] * len(texts)
    calls = []
    for i in range(0, len(texts), batch):
        chunk = texts[i:i + batch]
        body = json.dumps({"model": MODEL, "input": chunk}).encode()
        req = urllib.request.Request(base.rstrip("/") + "/embeddings", data=body,
                                     headers={"Content-Type": "application/json"})
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
        calls.append({"n": len(chunk), "ms": round((time.perf_counter() - t0) * 1000, 1)})
        for item in data["data"]:
            out[i + item["index"]] = item["embedding"]
    return out, calls

def single_latency(base, text, n=20):
    ms = []
    for _ in range(n):
        body = json.dumps({"model": MODEL, "input": text}).encode()
        req = urllib.request.Request(base.rstrip("/") + "/embeddings", data=body,
                                     headers={"Content-Type": "application/json"})
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
        ms.append((time.perf_counter() - t0) * 1000)
    ms.sort()
    return {"n": n, "p50_ms": round(ms[len(ms) // 2], 1), "min_ms": round(ms[0], 1), "max_ms": round(ms[-1], 1)}

def dot(a, b):
    return sum(x * y for x, y in zip(a, b))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8001/v1")
    ap.add_argument("--seed", default=os.path.join(HERE, "faq_seed.jsonl"))
    ap.add_argument("--rewrites", default=os.path.join(HERE, "rewrites.jsonl"))
    ap.add_argument("--out", default=os.path.join(HERE, "sweep.json"))
    args = ap.parse_args()
    seed = [json.loads(l) for l in open(args.seed)]
    rew = [json.loads(l) for l in open(args.rewrites)]
    texts = [s["q"] for s in seed] + [r["q"] for r in rew]
    vecs, calls = embed(args.base, texts)
    key_v = vecs[:len(seed)]
    qry_v = vecs[len(seed):]
    lat = single_latency(args.base, seed[0]["q"])
    id_at = {s["id"]: i for i, s in enumerate(seed)}
    rows = []
    for r, v in zip(rew, qry_v):
        sims = [dot(v, kv) for kv in key_v]
        j = max(range(len(sims)), key=lambda k: sims[k])
        g = id_at[r["gold"]]
        others = [sims[k] for k in range(len(sims)) if k != g]
        rows.append({
            "src": r["src"], "kind": r["kind"], "gold": r["gold"],
            "pred": seed[j]["id"], "top": round(sims[j], 4),
            "sim_gold": round(sims[g], 4), "best_other": round(max(others), 4),
        })
    def pack(subset):
        n = len(subset)
        table = []
        for th in THETAS:
            hit = [x for x in subset if x["top"] >= th]
            wrong = [x for x in hit if x["pred"] != x["gold"]]
            table.append({
                "theta": th, "n": n, "hit": len(hit), "wrong": len(wrong),
                "hit_rate": round(len(hit) / n, 4) if n else None,
                "wrong_rate": round(len(wrong) / n, 4) if n else None,
                "wrong_among_hits": round(len(wrong) / len(hit), 4) if hit else 0,
            })
        return table
    para = [x for x in rows if x["kind"] == "para"]
    adv = [x for x in rows if x["kind"] == "adv"]
    wrongs = [x for x in rows if x["pred"] != x["gold"]]
    out = {
        "model": MODEL, "n_keys": len(seed), "n_para": len(para), "n_adv": len(adv),
        "batch_calls": calls, "single": lat,
        "para": pack(para), "adv": pack(adv), "all": pack(rows),
        "wrongs_at_0": [{"src": x["src"], "kind": x["kind"], "gold": x["gold"], "pred": x["pred"],
                         "top": x["top"], "sim_gold": x["sim_gold"]} for x in wrongs],
    }
    json.dump(out, open(args.out, "w"), ensure_ascii=False, indent=1)
    print(args.out)
    print("single p50", lat)
    print("theta hit wrong | para / all")
    for a, b in zip(out["para"], out["all"]):
        print(f"{a['theta']:.2f}  {a['hit_rate']:.3f} {a['wrong_rate']:.3f}  |  {b['hit_rate']:.3f} {b['wrong_rate']:.3f}")
    print("nearest-not-gold", len(wrongs))

if __name__ == "__main__":
    main()
