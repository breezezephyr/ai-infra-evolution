# Phase 2 · 环境

| 角色 | 机器 | 说明 |
|---|---|---|
| vLLM | `ssh -p 6064 researcher@SSH_HOST`（DARYU，WSL2，RTX 4060 Laptop 8 GB） | 现网：embedding 8001、router 8000、Bonsai(llama.cpp) 8002 按需。实验：`bench-vllm` Qwen3-1.7B 在 **8003** |
| 面板 | `ssh wy`（Intel MBP，macOS 12.7） | Prometheus 9090（仅本机）、Grafana **3001**（admin / p2bus），二进制装在 `~/p2/`，不走 brew（Monterey 上 brew 已坏） |

wy → DARYU 指标走 SSH 隧道（launchd `local.daryu-metrics-tunnel`）：18001→8001、18003→8003、18000→8000。Prometheus 抓 `127.0.0.1:1800x`。

实验窗口：`systemctl stop qwen3-embedding` → 起 8003 → 压测 → `systemctl start qwen3-embedding`。router 不动。

文件：`prometheus/prometheus.yml`、`prometheus/tunnel.plist`、`launchd/*.plist`、`grafana/p2-lifecycle.json`（按 P1·下 生命周期图分六行）、`grafana/datasource.yml`、`grafana/dashboards.yml`。

## DARYU 侧（`/opt/p2/`，源码在本目录 `daryu/` 与 `bench/`）

- `bench-vllm.service`：Qwen3-1.7B BF16，8003，`Conflicts=` embedding / Bonsai（起它会自动停两者）；参数在 `/etc/default/bench-vllm`（GPU_UTIL / MAX_NUM_SEQS / MAX_BATCHED_TOKENS / EXTRA_ARGS），改完 `systemctl restart bench-vllm`。**disabled，不开机自启**
- `bench/lib.sh`：`window_open`（起 bench 等就绪）/ `window_close`（停 bench、恢复 embedding）/ `set_param` / `bench name conc in out n`，结果 JSON 落 `/opt/p2/results/`，带 `prom_start` / `prom_end` 时间戳用于在 Grafana 上框窗口
- `bench/smoke.sh`：空跑验链路。`exp1_concurrency.sh` 坐几人 · `exp2_prompt_len.sh` 行李多重 + 预算 2048/8192 · `exp3_prefix.sh` 常客 · `exp4_preempt.sh` 制造抢占。每个脚本自开自关窗口；`KEEP_OPEN=1` 连跑多个时不关
- 客户端在 DARYU 本机跑（`vllm bench serve`，random 数据集），排除网络抖动
- 拉结果回本地：`./sync_results.sh` → `phase2/results/`

- **坑**：DARYU 的 `flashinfer-python 0.6.18` 与 `torch 2.6` ABI 不兼容（`torch_c_dlpack_ext` undefined symbol），V1 引擎起不来；embedding 服务不走这条 import 所以没事。解法：`/opt/p2/stub/flashinfer/__init__.py` 抛 ImportError，`bench-vllm.service` 里 `Environment=PYTHONPATH=/opt/p2/stub`，只影响 bench。不改现网环境的包
- **坑**：systemd 里 `${VAR}` 为空会传空参数导致 vLLM 报 unrecognized arguments，要用不带花括号的 `$EXTRA_ARGS`

- **这张卡的账**：8188 MiB × 0.90 − Windows 基线 919 − 权重 3215 − 激活/CUDA graph ≈ **1.41 GiB KV**；Qwen3-1.7B 每 token 112 KB（2×8 头×128×2B×28 层）→ 全车 ~13K token 座位。`MAX_MODEL_LEN=8192`；实验并发按此缩到 1–32
- Grafana 开了匿名 Viewer（只读，仅 wy 局域网 / SSH 隧道可达），编辑仍需 admin 登录

## 2026-09-21 smoke 通过

- 窗口 14:23–14:27，Qwen3-1.7B，GPU_UTIL 0.90 / MAX_MODEL_LEN 8192 → **KV 13,184 tokens**
- 16 条（4 并发，256 in / 64 out）：TTFT p50 124 ms，TPOT p50 15.6 ms，输出 232 tok/s；结果 `results/smoke-20260921-142638.json`
- 面板六行全部有数据（Grafana `p2-lifecycle`，`$job=vllm-bench`）；prefix cache 指标名是 `gpu_prefix_cache_{queries,hits}_total`，已改
- 踩的坑：`vllm bench serve` 0.8.5 用 `--endpoint-type openai-comp`，`--model` 要给本地目录（客户端要 tokenizer）；`set -e` 在函数内不触发 ERR trap → 用 `set -E`，并加 flock 防两个窗口重叠

## 2026-09-21 四组压测全部完成

结果 `results/*.json` + 三份结论笔记；图 `img/exp1–4.png`（`.venv/bin/python plot_exp.py exp1 --x conc` / `plot_exp234.py exp2|exp3|exp4`）。服务端每窗口峰值用 Prometheus 查（脚本见 `results/exp4-结论.md` 的表）。GPU_UTIL 0.70 在这张卡上起不来（权重 3.2 GiB + Windows 基线 0.9 GiB 已超预算）。


## 两面对上与文章（09-21）

- `compare_sides.py`：一次 ssh 查回 18 窗口 × 7 直方图的 sum/count，服务端 mean 与客户端 JSON 对表 → `results/两面对上-表.md`、`results/两面对上-结论.md`。发现：TPOT 两边 ≤0.2 ms；服务端 count = 客户端 + 1（bench 探针请求）；服务端 prompt token 多 5%（random 数据集重新分词）；重载下服务端 TTFT 直方图 > 排队 + prefill（前端到调度器一段）。
- 文章 `05-Phase2上-*/`、`06-Phase2下-*/` 已进草稿箱；面板截图用无头 Chrome 打 `localhost:3001/d/p2-lifecycle/...?kiosk=true`（匿名 Viewer）。
