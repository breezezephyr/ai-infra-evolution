# exp25结论：42请求、12attempt、642token是三种分母

2026-10-26。单个DARYU RTX4060 Laptop、Qwen3-0.6B原生模板、vLLM0.8.5 V0/BF16/eager，两个合成租户、一个独立实验网关。无recipe→Qwen、DeepInfer、KV迁移、多GPU/生产HA运行。

[设计](../exp25/设计.md)、[源码映射与旧诊断边界](../exp25/源码笔记.md)、[复现](../exp25/README.md)、[P5·7正文](../../26-Phase5·7-把站台接起来/正文.md)。

## 正式分母

[冻结计划](exp25/formal-v1/plan.json)、[42条客户端记录](exp25/formal-v1/clients.json)、[网关终态账本](exp25/formal-v1/gateway.jsonl)、[12条后端入口/原始SSE](exp25/formal-v1/backend.jsonl)、[摘要](exp25/formal-v1/summary.json)。4条预检不并入正式。code/快照实际执行，gateway-startup记录运行源码hash；对应5文件由分析器校验。

| 终态 | 数量 |
|---|---:|
| 交付 | 17 |
| 身份拒绝 | 1 |
| 能力/参数拒绝 | 9 |
| 实际输入token预算拒绝 | 1 |
| 有界准入拒绝 | 12 |
| 实验规则拒绝交付 | 2 |
| 合计 | 42 |

42/42三方关联符合冻结场景预期，不是42个正确答案。17交付=7精确缓存+10新生成交付；10新生成含6个length（2短上限探针+4突发长回答）。另2次新生成被规则阻止交付，因此12真实attempt。缓存判定7hit/24miss/11未检查，24miss中12被准入拒绝；不能把miss都视为model call。

## 用量与交付

每个真实attempt的请求体hash/HTTP状态/原始SSE/后端usage匹配，原生prompt token长度与backend prompt_tokens一致。12项usage均可测，未知0；未得到每请求cached_tokens，没有文字长度估算或货币计费。

| 合成租户 | prompt_tokens | completion_tokens | total_tokens |
|---|---:|---:|---:|
| A | 263 | 144 | 407 |
| B | 105 | 130 | 235 |
| 合计 | 368 | 274 | 642 |

两次LAB_BLOCK生成各24输入+3输出=27，合计54token；网关模型正文发出0B，客户端收到422且无该正文。缓存当前请求无attempt、生成usage为0；原生成request/attempt/usage作为来源单列，不重复结算。

接口是明确子集并带gateway_usage扩展，不宣称完整OpenAI兼容。LAB_BLOCK仅为无害教学规则；先收完backend流再做整段门控，然后向client发送SSE，不是实时逐字审核。非空/stop/可测usage/规则允许是缓存写入条件，不是事实质量认证。

## 隔离、准入与时钟

实验Bearer固定映射A/B；客户端伪租户头不改变映射。精确完成响应缓存按租户、实际输入/设置、模型/tokenizer/模板、策略与路由版本隔离，64条/300秒TTL。route2仍使用同一GPU，正式仅验证逻辑路由/参数变化，实际模型权重/模板/策略版本变化由CPU边界测试覆盖。

每轮8条长请求+1条warm缓存读取，两轮中每轮2条长请求进入、6条准入拒绝；缓存读取可交付。网关活跃名额1/等待名额1，gateway域内attempt调用区间最大重叠1。这不是CUDA执行、生产容量或GPU归属证明。

客户端收首段、网关解析backend首段、后端HTTP首body块分开记录；只在各自clock_domain内减monotonic时间。17交付混有7缓存命中/不同长度/排队，不拿混合延迟推断网关开销或SLO。没有teacher forcing、通用答案质量或速度收益结论。

## 历史诊断分列

[CPU诊断重放](exp25/legacy-replay-v1/summary.json)以[固定旧输入引用](exp25/preflight/legacy-diagnostics-input.json)核验来源hash。3个exp11旧误命中分数组在0.88阈值仍选错，不是新embedding/实际缓存交付；旧摘要缺逐句ID/hash，不能给三句问题配造分数，现存默认改写输入与旧摘要计数不一致也照实保留。

exp13保留真实分类漏判、判对但异步已交付等反例；当前marker规则在三条旧风险句子probe中均不拦截，证明它不是通用审核器，未新增审核模型调用。独立样例/历史记录/本轮GPU三类分母不相加。

## 复核与清理

[31项本地检查](exp25/tests.txt)通过；TDD证据在preflight/*red*.txt。初轮9项、补充请求体/失败收尾、时钟、账本无效证据与历史诊断后31项。失败/缺失/重复/身份/原始用量/流终态突变均应让对账失败，无法核对时不发布成功租户汇总。

[清理回读](exp25/cleanup.json)：backend PID124497不存在，8025/8125不监听，GPU664MiB used/7294MiB free/0%，四个模型文件hash前后相同；[正式网关finally清理](exp25/formal-v1/gateway-cleanup.json)PID124988退出。未改动旧8000服务。后端环境与原始证据保留。

原正式code/和summary-execution.json完整保留。审校修复了冲突完成帧、删除生成记录少计成本、客户端SSE字段与重复ID漏检；8个回归RED→GREEN，最终31项通过。analysis-revision1保存修复后源码；12条原生SSE仅CPU重放，内容/finish/usage全部一致，原始与修订摘要字节相同，不新增GPU请求。复跑入口的backend PID改可选/缺省null，避免沿用历史PID。

[独立整体审校](exp25/independent-review.json)覆盖代码、证据和图文；如有修复见[修复记录](exp25/review-resolution.json)。没有二次审校，以回归和原始流CPU重放验证修复。本地正文/封面/图卡/移动端完成，未上传公众号草稿箱，未群发。下一步exp26/P5·8取消、断流、排空与安全重试。
