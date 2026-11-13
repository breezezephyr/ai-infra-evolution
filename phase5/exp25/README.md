# exp25：把独立组件接入同一条请求

2026-10-26，DARYU单个RTX4060 Laptop，Qwen3-0.6B原生模板、vLLM0.8.5 V0/BF16/eager。两个合成租户，一个实验网关，一次请求最多一个生成attempt。

- [设计](设计.md)、[源码映射](源码笔记.md)、[进度与设计决策](进度.md)、[结论](../results/exp25-结论.md)、[P5·7正文](../../26-Phase5·7-把站台接起来/正文.md)。
- [正式摘要](../results/exp25/formal-v1/summary.json)、[冻结计划](../results/exp25/formal-v1/plan.json)、[客户端](../results/exp25/formal-v1/clients.json)、[网关](../results/exp25/formal-v1/gateway.jsonl)、[后端](../results/exp25/formal-v1/backend.jsonl)、[运行时源码身份](../results/exp25/formal-v1/gateway-startup.json)。
- [模型文件与版本](../results/exp25/model-identity.json)、[清理回读](../results/exp25/cleanup.json)、[31项本地检查](../results/exp25/tests.txt)、[原始独立审校](../results/exp25/independent-review.json)、[修复与回归](../results/exp25/review-resolution.json)。
- [历史诊断引用输入](../results/exp25/preflight/legacy-diagnostics-input.json)、[独立CPU重放](../results/exp25/legacy-replay-v1/summary.json)。不新增embedding/审核模型调用，问题与分数组不能逐句关联时保留null。

## 复核

```bash
phase5/.venv-exp25/bin/python -B -m pytest -q phase5/exp25
phase5/.venv-exp25/bin/python -B phase5/results/exp25/formal-v1/analysis-revision1/analyze.py --out phase5/results/exp25/formal-v1
/tmp/exp14-local-env/bin/python -B phase5/exp25/plot.py
```

摘要重建不新增模型样本，覆盖已有summary前可先复制整个目录。运行code/快照并核对hash，最终校验使用analysis-revision1；原始code/及summary-execution.json保留。修复仅CPU回放和复核，没有新增GPU样本，不冒充原始执行代码。

诊断默认不启用语义分支，显式启用才重放历史分数；使用新输出目录：

```bash
phase5/.venv-exp25/bin/python -B phase5/exp25/diagnostics.py --enable-semantic-replay --out /absolute/new-diagnostic-directory
```

## 新做一次真实GPU运行

既有证据不覆盖。先重新核对GPU、模型文件hash、Python/库、可用端口与既有服务。独立路径是/opt/exp25-20261026-p5g，后端8025、网关8125；不能直接复用旧PID。backend_audit.py使用ASGI透明记录，不修改模型采样或执行器。

本轮启动设置：

```bash
PYTHONPATH=/opt/p2/stub:/opt/exp25-20261026-p5g VLLM_USE_V1=0 \
EXP25_AUDIT_PATH=/opt/exp25-20261026-p5g/backend.jsonl \
/root/vllm-env/bin/vllm serve /opt/models/Qwen3-0.6B \
 --served-model-name exp25-qwen3-0.6b --host 127.0.0.1 --port 8025 \
 --dtype bfloat16 --max-model-len 2048 --max-num-seqs 4 \
 --max-num-batched-tokens 4096 --gpu-memory-utilization 0.60 \
 --enforce-eager --disable-frontend-multiprocessing --disable-log-requests \
 --generation-config vllm --middleware backend_audit.AuditMiddleware
```

隔离目录准备本目录的5个运行文件、model-identity.json及后端后，以该Linux环境Python执行`run.py --out /absolute/new-output-directory`。必须使用新的目录；可用`--backend-pid`提供本轮实际PID，缺省记null，避免沿用历史PID。这个字段只作声明，不参与启停。run.py冻结计划、读回并执行code/归档文件，启动网关、跑请求、筛选本轮attempt审计，最后关闭自己的网关。后端由启动者单独回收，不能照抄本轮PID。

## 明确能力

只支持文本messages、stream=true、max_tokens1–96、temperature0、seed25，prompt实际原生token≤512。两个实验Bearer为公开fixture字符串lab-a/lab-b，不是生产凭据；客户端租户头不能改变映射。所有授权仅限独立实验服务。

精确完成响应缓存按租户、输入/生成设置、模型/tokenizer/模板、策略/路由版本隔离；64条上限、300秒TTL。仅非空、stop、usage可核对且规则允许时写入，没有事实质量认证。逻辑route2仍指向同一GPU；模型/模板/策略身份变化另有CPU测试，非实际换权重对照。

后端流先完整缓冲，再做LAB_BLOCK规则，然后向客户端发送SSE；`gateway_usage`是明确的网关扩展，分开当前生成与原缓存来源usage。不承诺完整OpenAI兼容、逐字实时审核、工具执行、重试/取消传播、生产HA或成本节省。

服务已关闭、端口回读关闭、GPU回664MiB/0%。这不证明未知外部供应商的取消或计费行为。下一站exp26再做取消/断流/排空与安全重试。
