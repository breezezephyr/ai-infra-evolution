# exp21：声明、约束执行和独立验收

2026-10-26完成。CPU真实recipe0.2.0转换126条及parser探针18条；GPU使用DARYU RTX4060 Laptop、Qwen3-0.6B原生模板、vLLM0.8.5/xgrammar0.1.18。两条独立实验作语义对应，未将recipe prompt或OutputConstraint直接接Qwen，未执行DeepInfer。

## 主要证据

- [设计](设计.md)、[recipe/DeepInfer源码笔记](源码笔记.md)、[已安装后端源码与模型身份](backend-source-notes.md)。固定来源身份不等于native二进制构建commit已证明。
- [CPU摘要](../results/exp21/cpu/结果摘要.md)、[126行矩阵](../results/exp21/cpu/formal-v1/mapping-matrix.csv)、[18条parser记录](../results/exp21/cpu/formal-v1/parser-probes.jsonl)。126/126符合冻结预期，90接受/36预期拒绝；Messages输入组成不同，不能按接受数排名。
- [GPU汇总](../results/exp21/gpu-summary.json)、[120行矩阵](../results/exp21/gpu-matrix.csv)、[完整计划](../results/exp21/gpu-formal-v1/plan.json)、[原始响应](../results/exp21/gpu-formal-v1/records.json)。每组40个分母，schema组10次明确400不删除，测量分母另列。
- [API入口对账](../results/exp21/api-reconciliation.json)：120/120实际接收的body SHA256、HTTP状态与客户端一致。只证明到达入口；安装代码、配置和独立约束控制另证执行路线，没有逐token CUDA mask trace。
- [控制请求](../results/exp21/backend-probes.json)、[范围关键字预检](../results/exp21/bounds-probes.json)、[live OpenAPI](../results/exp21/backend-openapi.json)、[服务日志](../results/exp21/server.log)。6个预检请求与正式120分开，不算额外正式样本。
- [清理回读](../results/exp21/cleanup.json)、[初轮36项测试](../results/exp21/local-tests.xml)、[最终46项测试](../results/exp21/local-tests-final.xml)、[结论](../results/exp21-结论.md)、[P5·3正文](../../22-Phase5·3-按格式报站/正文.md)。

## 本地复核

在系列根目录执行。jsonschema4.25.1安装报告及依赖身份保留于`results/exp21/jsonschema-install.json`；原recipe包未升级。

```bash
phase5/.venv-exp19/bin/python -B -m pytest -q phase5/exp21/test_cpu.py phase5/exp21/test_evaluate.py
phase5/.venv-exp19/bin/python -B phase5/exp21/analyze_gpu.py \
  phase5/results/exp21/gpu-formal-v1 --ingress phase5/results/exp21/api-ingress.jsonl
/tmp/exp14-local-env/bin/python -B phase5/exp21/plot.py
```

CPU重新运行命令见源码笔记，输出使用新目录，不能覆盖正式记录。GPU服务本轮已停止；重新运行前先检查显卡/端口和后端版本。启动使用`--guided-decoding-backend xgrammar`；no-fallback放在请求顶层`guided_decoding_backend`，不能把带后缀值传给CLI。精确启动参数、模型/权重/tokenizer/template SHA256见后端源码笔记及服务日志。

```bash
phase5/.venv-exp19/bin/python -B phase5/exp21/gpu_run.py \
  --base-url http://127.0.0.1:18021 --model exp21-qwen3-0.6b \
  --thinking-disabled --run-id exp21-replay-unique --out phase5/results/exp21/gpu-replay-unique
```

这是需要真实新模型服务与本实验ASGI入口记录器的命令。`backend_audit.py`只记录带专用exp21标记的合成请求，保留字段和body摘要；结果须与对应run的入口日志对账。

当前重放运行器补齐跨run身份、仅为接受行统计交付指标、错误体坏UTF-8容错，最终46项测试通过。正式`gpu-formal-v1/provenance`保留执行时版本；上述问题未触发本轮原始记录，独立重评110条输出及120条入口对账一致，不改写旧计划/记录或合并为新GPU样本。

## 分母和限制

20任务×2seed×3组=120，单并发，三个组使用完全相同的任务及schema文字，只改变约束字段。保留原schema；array minItems/maxItems不支持，未降级或静默回退。共同30个受支持配置单独比较，不拿30/30和40分母直接排名。

严格解析完整输出，不剥代码围栏、不提取子串、不接受重复键或非有限数字。提示组33次解析失败均以围栏开始，这是本轮完整输出合约不符，不说明围栏里的内容都错误。所有已接受响应均Stop；JSON/schema/业务值/完整结束分别保留。当前固定小样本和两次seed重复不是通用模型能力统计。

无实际工具执行、生产容量/SLO、DeepInfer推理或recipe→Qwen端到端结论。后端native CPU matcher额外反例只在源码笔记中，未混入120条GPU分母。
