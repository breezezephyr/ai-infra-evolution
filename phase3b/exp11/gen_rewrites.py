#!/usr/bin/env python3
"""用 Qwen3-1.7B 自己改写 exp11 的 FAQ。

每条按五种问法各写一句同义改写（gold = 自己）。near 非空的 20 条再写一句：
问法模仿自己，内容是 near 的事实（gold = near，looks_like = 自己）。
和原句相同、照抄 near 原句、或没带上差别词的，重试一次后放弃。

在 DARYU 上、bench-vllm 已监听 127.0.0.1:8003 时跑。跑完恢复 qwen3-embedding。

  python3 gen_rewrites.py --base http://127.0.0.1:8003/v1 --out rewrites.jsonl
"""
import argparse, json, os, re, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
STYLES = ["换成更口语的问法", "换成更书面的问法", "改成以「请问」开头", "改成以「想了解一下」开头", "换一个说法，不要原样重复原来的动词"]
PARA = "用简体中文把这句客服问题{style}。意思不变，不改数字、对象和条件。只输出一句问话。\n{q}"
ADV = "保留原问法的句式，改成在问这个事实。必须是问句，不要把事实原样再说一遍。只输出一句简体中文。\n原问法：{src}\n事实：{fact}"

def norm(s):
    return re.sub(r"[\s？?。，,！!、：:；;（）()\"“”呢吗]", "", s or "")

def first_line(text):
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return re.sub(r"^[\d]+[\.、\)]\s*", "", line).strip("「」\"'")

def chat(base, model, prompt, temperature):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": 48,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.load(r)
    return first_line(data["choices"][0]["message"]["content"])

def is_q(s):
    return any(x in s for x in ("吗", "？", "?", "怎么", "多少", "几点", "多久", "能否", "是否", "哪", "呢"))

def distinctive(gold_q, src_q):
    return "".join(ch for ch in gold_q if ch not in src_q and ch not in "？?。，,！!、 ")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8003/v1")
    ap.add_argument("--model", default="qwen3-1.7b")
    ap.add_argument("--seed", default=os.path.join(HERE, "faq_seed.jsonl"))
    ap.add_argument("--out", default=os.path.join(HERE, "rewrites.jsonl"))
    ap.add_argument("--only-adv", action="store_true")
    args = ap.parse_args()
    rows = [json.loads(l) for l in open(args.seed)]
    by = {r["id"]: r for r in rows}
    with open(args.out, "w") as out:
        for r in rows:
            if not args.only_adv:
                seen = {norm(r["q"])}
                n_ok = 0
                for i, style in enumerate(STYLES, 1):
                    q = ""
                    for temperature in (0.7, 1.1):
                        cand = chat(args.base, args.model, PARA.format(style=style, q=r["q"]), temperature)
                        nq = norm(cand)
                        if cand and nq and nq not in seen and len(cand) <= 48 and "原句" not in cand:
                            q = cand
                            break
                    if not q:
                        print("para-miss", r["id"], i)
                        continue
                    seen.add(norm(q))
                    n_ok += 1
                    rec = {"src": r["id"], "kind": "para", "n": n_ok, "style": style, "q": q, "gold": r["id"], "looks_like": None}
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                print("para", r["id"], n_ok)
            if not r["near"]:
                out.flush()
                continue
            g = by[r["near"]]
            mark = distinctive(g["q"], r["q"]) or distinctive(g["a"], r["a"])
            q, last = "", ""
            for temperature in (0.4, 0.7, 0.9, 1.05, 1.15, 1.2):
                cand = chat(args.base, args.model, ADV.format(src=r["q"], fact=g["a"]), temperature)
                last = cand
                nq = norm(cand)
                if (is_q(cand) and nq and nq not in (norm(r["q"]), norm(g["q"]))
                        and "其实" not in cand and (not mark or mark[:1] in cand)
                        and len(cand) <= 48):
                    q = cand
                    break
            if not q:
                print("adv-miss", r["id"], last)
            else:
                rec = {"src": r["id"], "kind": "adv", "n": 1, "q": q, "gold": r["near"], "looks_like": r["id"]}
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                print("adv", r["id"], "->", r["near"], q)
            out.flush()

if __name__ == "__main__":
    main()
