#!/usr/bin/env python3
"""把 1.7B 的同义改写换成最小对立：只替换一个区分词。

新句子的 gold 是换进去的那条原问，looks_like 是改写原本所属的原问。
和任一原问逐字相同的丢掉（那不是对抗，就是原题本身）。
"""
import json, os, re
HERE = os.path.dirname(os.path.abspath(__file__))

# src -> (needle, repl, gold)。含「不记名」的规则单独先替换，避免被「记名」截断。
RULES = {
    "f01": ("市区", "郊区", "f02"),
    "f02": ("郊区", "市区", "f01"),
    "f03": ("市区", "郊区", "f04"),
    "f04": ("郊区", "市区", "f03"),
    "f07": ("免票", "半票", "f08"),
    "f08": ("半票", "免票", "f07"),
    "f15": ("便宜", "贵", "f16"),
    "f16": ("贵", "便宜", "f15"),
    "f21": ("市区", "郊区", "f25"),
    "f22": ("学生", "老人", "f23"),
    "f42": ("记名", "不记名", "f43"),
    "f43": ("不记名", "记名", "f42"),
    "f63": ("自行车", "狗", "f64"),
    "f91": ("市区", "郊区", "f93"),
    "f92": ("市区", "郊区", "f94"),
    "f93": ("郊区", "市区", "f91"),
    "f94": ("郊区", "市区", "f92"),
}
# 同一条再做第二刀：首班 ↔ 末班。和上面的市区/郊区不叠在同一次输出上。
RULES2 = {
    "f91": ("首班", "末班", "f92"),
    "f92": ("末班", "首班", "f91"),
    "f93": ("首班", "末班", "f94"),
    "f94": ("末班", "首班", "f93"),
}

def norm(s):
    return re.sub(r"[\s？?。，,！!、：:；;（）()\"“”呢吗啊]", "", s or "")

def apply(q, needle, repl):
    if needle == "记名" and "不记名" in q:
        return None
    if needle not in q:
        return None
    return q.replace(needle, repl, 1)

def main():
    seed = [json.loads(l) for l in open(os.path.join(HERE, "faq_seed.jsonl"))]
    canon = {norm(s["q"]) for s in seed}
    paras = [json.loads(l) for l in open(os.path.join(HERE, "rewrites.jsonl")) if json.loads(l)["kind"] == "para"]
    seen = set()
    out = []
    for rule in (RULES, RULES2):
        for r in paras:
            spec = rule.get(r["src"])
            if not spec:
                continue
            needle, repl, gold = spec
            q = apply(r["q"], needle, repl)
            if not q:
                continue
            nq = norm(q)
            if nq in canon or nq in seen or nq == norm(r["q"]):
                continue
            seen.add(nq)
            out.append({
                "src": r["src"], "kind": "adv", "n": len(out) + 1,
                "q": q, "gold": gold, "looks_like": r["src"],
                "via": f"{needle}->{repl}", "base": r["q"],
            })
    path = os.path.join(HERE, "adv_swap.jsonl")
    with open(path, "w") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(path, len(out))
    from collections import Counter
    print(Counter(r["via"] for r in out))

if __name__ == "__main__":
    main()
