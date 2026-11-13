# exp26：半路抛锚

日期：2026-10-26。正式[formal-v1摘要](exp26/formal-v1/summary.json)、[冻结计划](exp26/formal-v1/plan.json)、[客户端](exp26/formal-v1/clients.json)、[网关](exp26/formal-v1/gateway.jsonl)、[后端HTTP/原生引擎](exp26/formal-v1/backend.jsonl)。

17条请求逐项符合计划，19次attempt都有独立记录和结算行。12条受控场景对应13次attempt；5条真实GPU场景对应6次attempt。全部故障由实验明确安排，不是自然故障率或HA测试。

| 终态 | 请求数 |
|---|---:|
| completed | 6 |
| backend_error | 3 |
| review_rejected | 1 |
| review_unavailable | 1 |
| cancelled | 1 |
| superseded | 1 |
| drain_timeout | 2 |
| draining | 1 |
| client_disconnected | 1 |

completed是协议收尾；GPU重试后的回答以length结束（192输出token），不能称完整回答或质量合格。客户端断开的那条没有终态帧，网关与后端终态仍留存。

三个首段前重试场景均保留2attempt：受控连接拒绝、受控首段前超时、真实GPU首段延迟后的超时。无幂等key的失败仅1attempt；两个首段后断流也各1attempt，没有拼接另一回答。提交点为首个内容ASGI send成功返回；收到HTTP头不算。客户端实际收到的SSE独立核对。

取消后迟到与旧generation两个受控场景，后端继续生成“迟到”，网关丢弃，不再交付。排空自然完成、超时取消、入口拒绝分别留证。所有请求之后健康回读active=workers=0。

原生后端为单个DARYU RTX4060 Laptop、Qwen3-0.6B、vLLM0.8.5 V0/BF16/eager。6attempt均映射到实际engine request；2正常结束，4取消路径均有原生abort_done及其后tracker和scheduler无pending/unfinished的CPU状态快照，无observation_error。真实重试中第二原生请求进入晚于首个attempt清空快照。这是本次观察，不代表HTTP关闭天然保证后端已停，也不是CUDA kernel级停止证明。

GPU6attempt：2条known usage合计248token（输入54、输出194），4条unknown保留null。248仅已知小计，不是全部消耗；4条取消attempt已有原生输出观测，但不从部分输出推算完整计量。受控13attempt：4条known synthetic计数28、9条unknown；不与原生GPU计数相加。不生成货币账单或独占GPU时长结论。

按attempt唯一键结算，同值重放不新增、冲突拒绝；这是本进程内存规则，没有跨进程重启事务保证。审计器独立解析原始SSE、核对所有ID、generation、attempt、终态/结算、失败attempt与来源、源码/计划hash和工作任务收拢；原执行摘要保留在[summary-execution.json](exp26/formal-v1/summary-execution.json)。最终[analysis-revision2](exp26/formal-v1/analysis-revision2/summary.json)加入本轮审校修复；第一版分析也保留。3项重要问题均经7个失败反例修复，全套53项CPU通过，6条原生输出离线重放一致，没有新增GPU调用。已知计量与网关结算不一致时阻止验收，保留后端资源来源，不静默改写历史结算。原正式数据没有触发这3项反例，17/19与用量指标未变。

[最终清理](exp26/cleanup.json)：owned后端PID退出、8026/8126关闭，GPU663MiB/0%，四个模型文件hash未变；未停止原服务8000。

[复现](../exp26/README.md)、[源码笔记](../exp26/源码笔记.md)、[P5·8正文](../../27-Phase5·8-半路抛锚/正文.md)。本章本地成稿，不含公众号上传或群发。
