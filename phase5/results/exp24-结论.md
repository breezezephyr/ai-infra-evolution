# exp24结论：先取回字节，再谈复用KV

2026-10-26；真实Mooncake non-CUDA 0.3.13.post1、DARYU Linux x86_64 / Python3.12。配置TCP，单机跨进程本地Store调用；未跟踪逐次载荷分支/socket字节，不报告纯TCP网络性能。无模型/GPU/RDMA/真实P/D。

## 核心结果

最终引用[formal-v3摘要](exp24/formal-v3/summary.json)，[238条原始操作](exp24/formal-v3/records.jsonl)全部保留。[冻结计划](exp24/formal-v3/plan.json)执行时读回，运行code/快照，worker回传请求摘要、PID、plan与worker代码hash；[逐项审计](exp24/formal-v3/audit.json)与生命周期PID核对。

| 分母 | 结果 |
|---|---|
| API操作238 | 228项声明检查通过，10项探索观察；失败、缺失、超时0 |
| 主对象40 | 1B/4KiB/64KiB/1MiB各10；40长度/hash一致 |
| 主时延120 | 4大小×put/get/remove各10；非法计时0 |
| 独立身份案例12 | 1不变可通过，11单字段变化均不匹配 |

A提供128MiB存储段，B提供0、local buffer32MiB；40主对象A写B读。不是同进程读自己的缓存。重启后的C提供16MiB，用于新client与恢复探针。日志显示memcpy优化自动开启，不能仅凭协议设置和跨进程就宣布逐次载荷均走了哪个传输分支。

formal-v1保留为同进程预跑（put含payload生成）；formal-v2修正跨进程与计时。formal-v3在审校后补齐记录器关联/失败门禁。三轮不合并为120个正式对象，不混用时延。

## 接口与故障

- 重复put：initial/identical/same-size/different-size四次均0，每次get仍是最初4KiB的hash。0不能证明覆盖；未测upsert。
- 缺失键：get为空字节，is_exist为0，remove为-704。master停止：get也为空字节，is_exist/put均-900。get空字节无法区分缺失与错误；审计ambiguous=0仅指预声明的字节形状检查，没有消除API语义歧义。未测零长度put。
- Python负整数为真值；存在性必须区分1/0/负数。is_exist与get非原子操作，不构成命中保证；存在性检查在固定源码中还会刷新读租约。
- 重启：显式关闭HA、snapshot/restore、offload，保留A/B。master重启约3秒后、再等待12秒后，以及新C，旧键存在性均0、get均为空；新键可重新写/读/hash/删。仅观察该配置和窗口，不证明物理擦除或其他HA/持久化配置。
- 串行清理使用force=True，逐键验证is_exist=0。没有测试普通删除的租约等待或并发删除；force并非绕过副本就绪和复制任务所有检查。

## 时延口径

[正式摘要](exp24/formal-v3/summary.json)含每组中位数、最小/最大；[证据图](../../25-Phase5·6-行李不跟车走/img/11-exp24.png)从该摘要生成。worker内部perf_counter_ns计时，仅Python Store调用，排除put字节生成、读回hash、JSON/IPC与parent开销。串行未预热，每档10条；不是稳定尾延迟、负载容量、GPU kernel或纯网络时间。

## 缓存身份

[身份代码](../exp24/identity.py)、[冻结合约](exp24/identity-v1/plan.json)、[结果](exp24/identity-v1/summary.json)。包含合约版本、租户/隔离域、模型/tokenizer/template revision、精确全token前缀、KV布局/dtype、并行分片、位置/RoPE/注意力命名空间和多模态身份。规范JSON→带版本SHA256。

12/12符合预期，身份完全一致且两个字面布尔门禁都为True才通过；缺少payload完整性或importer兼容声明均拒绝。两个门禁是调用方声明，不是已运行的模型导入器/真实hash核验函数。没有认证、Store ACL、部分前缀、语义缓存或真实KV兼容结论。

## 源码与旧P3对照

[源码笔记](../exp24/源码笔记.md)及[Mooncake固定文件清单（第三方依赖需恢复，未随仓库收录）](../../docs/THIRD_PARTY.md)。阅读commit c67a88f源码版本0.3.12.post1；运行wheel0.3.13.post1，[wheel与6项原生文件hash核验](exp24/preflight/binary-identity.json)通过，构建commit未验证。不能把源码分支已阅读写成wheel运行逐分支追踪。

[P3原算表](../../phase3/results/pd_ratio.md)与[脚本](../../phase3/pd_ratio.py)仍为模型/性能假设下的预算。[本轮复核](exp24/preflight/p3-budget-recheck.json)指出整数配卡表未纳入网络上限；16卡6P+10D计算上限18.08req/s，若共用理论10GbE，应再受约10.64req/s约束。不是网络测量，不将本轮1MiB本机接口时延带入117MB KV搬运预算。

普通bytes完整性之后仍缺：真实模型KV导出/导入、块映射与生命周期、布局/精度/层序/位置兼容、恢复数值检查，以及同资源同负载P/D与合车对照。

## 复核与清理

初轮185项、修复后197项本地pytest通过。原始[记录器审校](exp24/recorder-review.json)与[修复](exp24/review-resolution.json)、[复审](exp24/recorder-rereview.json)分开保留。[本轮清理](exp24/formal-v3/cleanup.json)及[远端最终回读](exp24/formal-v3/cleanup-live.json)覆盖5个owned PID和11个静态/日志实际端口，均收拢；命名键不存在另有API记录，非内存擦除证明。独立venv、wheel与原始证据留在实验目录，未修改已有vLLM环境。

[P5·6正文](../../25-Phase5·6-行李不跟车走/正文.md)、封面/图卡/本地移动端预览同轮完成；尚未上传公众号草稿箱，未群发。下一步P5·7/exp25网关纵向集成。
