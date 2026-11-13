# exp27：同一批记录的联合验收

2026-10-26。最终[formal-v2](exp27/formal-v2/summary.json) accepted=true（证据有效，不等于全部回答合格）。[冻结计划](exp27/formal-v2/plan.json)、[客户端](exp27/formal-v2/clients.json)、[网关](exp27/formal-v2/gateway.jsonl)、[原生后端](exp27/formal-v2/backend.jsonl)、[资源](exp27/formal-v2/resources.json)、[清理](exp27/formal-v2/cleanup.json)。

42请求、37回答目标、29真实GPU attempt。30条completed、33条协议有效收尾（包含review/backend_error/drain_timeout的明确终态），这两个数不等于质量成功。37回答目标：协议32通过/5不通过；质量21通过/10不通过/6未知；延迟30通过/1不通过/6未知；同request交集21/37。总分母42时为21/42，不算生产成功率。

| 层 | 结果 |
|---|---|
| 正常直通 / 集成缓存冷 / 缓存暖 | 各6条全部联合通过 |
| 首内容/结束延迟样本中位数 | 49.59/75.17、79.49/79.81、1.21/1.34ms；每组n=6，固定顺序，不作普遍速度收益 |
| 算术直通/集成 | 各3条协议正常返回，质量均未满足去空白精确整数标准 |
| 突发6 | 2完成/4拒绝，2质量不合格；burst-1首内容1332.85ms超1000ms |
| 截断 | 唯一length探针，不能算质量通过 |
| 首段前重试 | 2attempt均留存；后继已知50计入总账 |
| 已提交后中断 | 完整后端后注入交付故障，明确错误终态，无拼答；已知资源保留 |
| 客户端取消/排空 | 独立原生事件与最终CPU清空；不声称CUDA kernel停止 |

GPU29attempt：26known原生usage770token（624输入/146输出），3unknown。5个非完成attempt中2known76、3unknown；后继重试1known50，均为29内部切片不再相加。6缓存hit当前无生成，原originusage单列；770只是已知小计，非总消耗或实付。

SLO阈值跑前固定为首内容<=1000ms、结束<=3000ms，同一客户端时钟；延迟列是有首内容时的流收尾，可能包含明确错误终态，业务完成另看completed。质量关和账本/来源通过再算joint，不乘异质实验比率。

模型服务+网关进程区间并集19.423s、ready区间并集8.036s、CPU wait4回收32.227s；每组件原始区间/CPU分开保存。它们包含加载/退出或并行CPU，并非独占权重/GPU kernel/租户GPU时间；这些值和货币实付为null。

[formal-v1](exp27/formal-v1/summary.json)未通过，观测请求头仍用旧编号，且缓存绕过部分故障。原始记录与最终清理保留；修正header、最后事件时间和明确故障前clear-cache前置条件后独立执行v2，两个运行不合并样本，质量答案、SLO、负载数不改。v1不得当成功或剔除其真实运行历史。[运行清单](exp27/运行清单.json)另列首轮39请求/25attempt、网关侧24条已知740/1未知（未独立对账），不当已验收账或零成本；770仅最终轮已知小计，整个实验总费用仍未知。

当前exp25 31与exp26 53项CPU闭环检查先通过；它们的结果不并入42。本轮网关与审计器测试、一次整体审校/修复最终22项主/审计器/环境CPU检查通过，见[tests.txt](exp27/tests.txt)。一次审校发现2重要/1轻微：原始chunk可见的usage不应被汇总抹掉、资源PID须绑定实际服务启动，及Linux查询路径。全部一轮修复；[修订分析](exp27/formal-v2/analysis-revision1/summary.json)重算指标不变，原raw/code/summary-execution保留，不二审、无新增GPU调用。

贡献：[候选说明](../exp27/contribution/候选说明.md)。真实recipe0.2.0 native编码41token，再人为给40/41/42上下文、两种预算共6helpercalls。中英文指南+6绑定测试补丁，本地6项、补丁后上游相关筛选7项通过，共用wheel不相加。当前main与固定源码同SHA，wheel build commit未知。已核对上游#42及关闭未合并#44，未当新bug、未提交PR、无GPU模型调用。

最终owned PID127352/127245回收、8027/8127关闭、GPU630MiB/0%、4模型hash不变。单RTX4060 Laptop/Qwen3-0.6B/vLLM0.8.5 V0 BF16 eager、两个合成租户、loopback HTTP、完整响应实验规则门控、应用精确缓存。无生产变更、语音分钟、工具/投机执行、独立HA或生产容量结论。

[复现](../exp27/README.md)、[能力与迁移](../exp27/能力与迁移清单.md)、[P5·9正文](../../28-Phase5·9-交班时拿什么说话/正文.md)。本地稿未上传。
