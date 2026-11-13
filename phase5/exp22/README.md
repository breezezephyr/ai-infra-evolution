# exp22：调度循环与不同batch里的同一请求

2026-10-26：144条正式GPU请求完成，4条预检分开。CPU调度计划、实际输入/输出token IDs、四层请求证据均已保留。DeepInfer仅阅读固定源码，独立运行Qwen/vLLM小后端。

- [设计](设计.md)、[执行记录](执行记录.md)、[源码笔记](源码笔记.md)、[结论](../results/exp22-结论.md)。
- [正式摘要](../results/exp22/formal-v1/summary.json)、[完整计划](../results/exp22/formal-v1/plan.json)、[原始响应](../results/exp22/formal-v1/records.json)、[网关](../results/exp22/formal-v1/gateway.jsonl)、[API/引擎/调度原始记录](../results/exp22/backend.jsonl)。
- [逐请求矩阵](../results/exp22/formal-v1/matrix.csv)、[差异原始ID样本](../results/exp22/formal-v1/difference-example.json)、[独立审校](../results/exp22/independent-review.json)、[清理回读](../results/exp22/cleanup.json)。
- [实际后端身份](../results/exp22/backend-identity.json)、[服务日志](../results/exp22/server.log)、[固定DeepInfer原始文件manifest（第三方依赖需恢复，未随仓库收录）](../../docs/THIRD_PARTY.md)。

## 本地复核

在系列根目录执行，无需启动GPU。21项测试检验实际并发上限、队列溢出/释放、独立时钟差值、墙钟跨度异常、逐请求完整身份/usage/设置门禁、无效基线不可替换、缺失输出不误算一致、重复/陈旧/状态不符证据能被识别。

```bash
phase5/.venv-exp19/bin/python -B -m pytest -q phase5/exp22/test_measure.py
phase5/.venv-exp19/bin/python -B phase5/exp22/analyze.py \
  phase5/results/exp22/formal-v1 --backend phase5/results/exp22/backend.jsonl
/tmp/exp14-local-env/bin/python -B phase5/exp22/plot.py
```

## 实际启动配置与重新执行

本轮服务已关闭。若重新跑，先查GPU/端口，创建新的远端目录、日志文件和本地输出目录，不能覆盖本轮证据。安装版本和模型文件身份必须重新核对。示例启动使用本轮隔离路径；这是需要GPU和真实模型的运行配置。

```bash
PYTHONPATH=/opt/p2/stub:/opt/exp22-20261026-p5d VLLM_USE_V1=0 \
EXP22_AUDIT_PATH=/opt/exp22-20261026-p5d/backend.jsonl \
/root/vllm-env/bin/vllm serve /opt/models/Qwen3-0.6B \
 --served-model-name exp22-qwen3-0.6b --host 127.0.0.1 --port 8022 \
 --dtype bfloat16 --max-model-len 2048 --max-num-seqs 4 \
 --max-num-batched-tokens 4096 --gpu-memory-utilization 0.60 \
 --enforce-eager --disable-frontend-multiprocessing --disable-log-requests \
 --generation-config vllm --middleware backend_audit.AuditMiddleware
```

`backend_audit.py`必须放在PYTHONPATH中的独立目录；关闭前端多进程，使插桩位于引擎同一进程。不要把该实验插桩直接用于生产。通过SSH把本地18022转到远端127.0.0.1:8022后：

```bash
phase5/.venv-exp19/bin/python -B phase5/exp22/gpu_run.py \
 --backend http://127.0.0.1:18022 --out phase5/results/exp22/replay-unique
```

`--preflight`创建独立4条试跑；正式为144条。输出目录必须不存在，避免混入旧行。每行HTTP超时/拒绝/错误保留，网关overflow返回429；本轮正式均200，未发生HTTP overflow控制实验，队列拒绝由本地并发测试验证。原始记录未经重写或自动修复。

`formal-v1/provenance`明确标注为运行后源文件快照：gpu_run/backend_audit执行代码未变；measure的Admission实现未变，运行后附加reconcile分析函数；随后审校修复扩展严格分析门禁，最终源文件快照在`analysis-revision2`，无新GPU请求。不要把事后快照说成运行前密封包。分析器/图像是事后处理，不增加GPU样本。

## 口径

8任务、2模式、并发1/2/4、3轮。temperature0贪心自由生成，seed17，enable_thinking=False，无teacher forcing。8条单独基线后的136比较为88同48异；85条混批观察37同48异，59条单批观察含8基线及51个相同比较。输出stop90/length54，比较到上限，不验收答案质量。

同一时钟内求差；完整HTTP响应非TTFT；调度计划非CUDA trace。有限闭环负载、动态输出长度、插桩和网络成本，不代表生产容量、通用确定性或DeepInfer复现。P5·4本地成稿，未上传。

独立审校F1/F2的修复与回归记录见[review-resolution](../results/exp22/review-resolution.json)。墙钟异常3条仅影响旧引擎时延统计，144条请求/输出分母不变；原始墙钟总时长不聚合，单调时钟观察区间明确命名。旧首次排队/首token墙钟统计排除3条并标n及混合变化。并发4正文表格未受影响。
