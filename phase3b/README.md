# Phase 3b · 环境与脚本

沿用 P3（`../phase3/README.md`）：DARYU `bench-vllm` Qwen3-1.7B :8003，网关 `../phase3/gateway/gw.py` → `/opt/p2/gateway/`，结果都落 DARYU `/opt/p2/results/`，本地 `results/`（scp 拉回）。

## bench/ → DARYU `/opt/p2/bench/`

- `startlog.py`：把一次 bench-vllm 启动的 journal 切成七段（进程 + import / 引擎 + CUDA 初始化 / 读权重 / torch.compile / profile + KV / CUDA graph / 收尾），输出一行 JSON
- `exp8_coldstart.sh`：warm ×3、页缓存冷 ×2、编译缓存移走 ×1、eager ×2（+ 小压测）；`exp8b_graph6.sh`：只捕获 6 个 graph 尺寸 ×2（systemd 会吃掉 `$EXTRA_ARGS` 里 JSON 的引号，改用临时 drop-in + `${COMP}`）+ 三配置并发 16 对照
- `ramp.py`：开环泊松爬坡客户端，每秒采 `/metrics` 与 GPU 利用率
- `exp9_10.sh`：exp9 爬坡（直连 8003）+ exp10 排空（经网关，`/gw/drain?deadline=`，第 `DRAIN_AT`=47 s 排空；`SKIP9=1` 只跑 exp10，`ORDER` 改期限顺序）

## 分析 / 画图（本地，`../phase2/.venv/bin/python`）

`plot_exp8.py`、`plot_exp9.py`（同时打印信号提前量表）、`analyze_exp10.py` + `plot_exp10.py` → `img/`

## exp11 语义缓存数据（`exp11/`）

虚构「北城通」客服 FAQ，不是真实票务。`faq_seed.jsonl`：10 个主题 × 10 条标准问答，20 条标了 `near`。`rewrites.jsonl`：1.7B 五种问法，427 句同义。`adv_swap.jsonl`：在这些句子上只换一个区分词，72 条。`sweep.py` 对现网 embedding 扫 θ。同义改写 θ = 0.88 答错为 0、命中 93%；这 72 条里仍有 31% 答错，要压到 0 得把 θ 抬到 0.98，同义命中掉到 20%。结论 `results/exp11-结论.md`，图 `img/exp11.png`。单条嵌入 p50 约 15 ms。

## 网关新增（P3b）

`POST /gw/drain?deadline=秒` / `POST /gw/undrain`；记录 `drain_start` / `drain_reject` / `drain_cut`（带 `chunks` 已发出字数）/ ok 的 `after_drain_ms`。`mix.py --stop-on-503`。

## exp12 离线账本与叫号回放（2026-10-22）

`exp12/README.md` 是计数合同与复现入口。`python3 exp12/analyze.py` 回放 exp7 引擎计数和 exp5 queue 日志；`../phase2/.venv/bin/python exp12/plot.py` 出图。示例费率每千token输入/缓存/输出=1/.2/3点；哈希每千次完成比轮询低39%。真实逐租户 usage 缺失，另用显式手写样例验证合同。生成流重叠时间分摊是代理。排位/历史服务率的预测，133条准入成功排队样本中仅19.5%落在±30%，113条超时单列。输出 `results/exp12-summary.json`（含输入SHA-256）、`exp12-groups.jsonl`、`exp12-queue.jsonl`、结论与 `img/exp12.png`。未连接或修改DARYU服务。

## exp13 流式审核（2026-10-22，GPU补跑）

入口 `exp13/README.md`。用户授权后停止Windows ComfyUI，显存6203→342MiB。保留CPU FP32（嵌入73ms、分类297ms）与受控回放；补测GPU BF16独立审核（22ms、48ms）和30条同卡实际生成＋真实审核。同步嵌入拦住标记句，异步已发17字＋后文中位数2字；分类器同步/异步均漏判并全文放行。17项测试本机/DARYU通过。`exp13/analyze.py`、`exp13/plot.py`生成GPU主图；`plot_cpu_controlled.py`保留CPU旧图。没有接入现网router/vLLM，画像仍为合成。ComfyUI按用户要求保持停止，WSL服务未变。
