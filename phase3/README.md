# Phase 3 · 环境与脚本

沿用 P2 环境（见 `../phase2/README.md`）：DARYU `bench-vllm` Qwen3-1.7B :8003，wy 上 Grafana `p2-lifecycle`。P3 新增一层网关。

## 网关 `gateway/gw.py` → DARYU `/opt/p2/gateway/`

`p2-gw.service` :8010 → :8003，`BindsTo=bench-vllm`（bench 停它就停），disabled。开关在 `/etc/default/p2-gw`：`GW_MODE` pass / reject / queue、`GW_BUDGET`（默认 12000 token）、`GW_TTFT`（首字期限秒）、`GW_QUEUE_WAIT`、`GW_PRIORITY`（按 `x-priority` 头出队）。估行李走后端 `/tokenize`（2–8 ms，就是 P2 两面对上里那段「分词」）。每条请求一行 JSONL 到 `/opt/p2/results/gw.jsonl`；`/metrics` 有 `gw_*`；`/gw/stats` 给人看。只用标准库，单测 `python3 -m unittest gateway/test_gw.py`。

## bench `bench/` → DARYU `/opt/p2/bench/`

- `lib3.sh`：source P2 的 `lib.sh`，`BASE` 改到 8010；`gw_set k=v ...` 改网关参数并重启；`gw_bench` = `bench` + 把这次的网关日志切成 `<name>-<ts>.gw.jsonl`
- `smoke3.sh`：pass / reject / queue 各 16 条验链路
- `exp5_admission.sh`：并发 32 × 256 条，pass / reject / queue 三种门 + pass 加首字期限 5 s；`CONC= N= TTFT_DEADLINE=` 可改
- `mix.py`：混发闭环客户端（`--cls 名:路数:in:out:优先级:思考秒`），流式记每字时间戳，每类出 TTFT / ITL / 被卡比例
- `exp6_priority.sh`：1 交互 + 7 批处理，pass / fcfs / prio / reserve 四组各 150 s
- `exp7_routing.sh`：两辆 0.6B（`bench-pair@8004/8005`）+ 独立网关 :8011，8 组常客 × 1.5K 前缀，rr / hash / hash-zipf / bounded 各 150 s；前后抓两辆车 `/metrics` 差分
- `../deploy.sh` 部署；`sync_results.sh` 拉 `exp5-*`、`smoke3-*`、`gw.jsonl` 回 `results/`

## 2026-09-23 smoke3 通过

窗口 16:29–16:31。预算 1500 / 每人 ~330 token → 放 4 人：reject 模式 17 条放 5 拒 12（客户端 `completed 4, errors 12`，vllm bench 把 429 记成 error）；queue 模式全放行，后 12 条排队约 1.0 s；pass 模式 TTFT 132 ms 与 P2 smoke 一致（网关开销不可见）。服务端 `/tokenize` 数出 268 vs 名义 256，与 P2 的 +5% 重分词一致。

## 2026-09-23 exp5 完成

窗口 17:20–17:28，四组：pass / reject / queue / ttft5。结论 `results/exp5-结论.md`；服务端峰值 `python3 prom_windows.py --prefix exp5`（ssh wy 查 Prometheus，输出 md）；图 `img/exp5.png`（用 phase2/.venv 画）。

## 2026-09-23 exp6 完成

窗口 18:06–18:19。网关新增 `GW_RESERVE`（高优预留座位，低优只能用 BUDGET − RESERVE），优先级模式下新请求入队后立即尝试出队（不必等下一次 release）。结论 `results/exp6-结论.md`；图 `plot_exp6.py` → `img/exp6.png`；服务端 `prom_windows.py --prefix exp6`。

## 2026-09-23 exp7 完成

窗口 19:41–19:53。双实例单元 `daryu/bench-pair@.service` + `/etc/default/bench-pair`（可选 `/etc/default/bench-pair-<port>` 按实例覆盖）。网关新增 `GW_BACKENDS`（多后端）、`GW_ROUTE` rr / hash（prompt 前 `GW_HASH_CHARS` 字符 crc32）/ bounded（有界负载哈希，`GW_BOUND`）。`mix.py` 新增 `--prefix-groups --prefix-len --zipf --seed`。结论 `results/exp7-结论.md`；图 `plot_exp7.py` → `img/exp7.png`。
