# Phase 0 · 从 Langfuse span 反推服务端

## 脚本

`langfuse_span_breakdown.py` — 拉 generation span，拆 TTFT / decode / TPOT，按 span 名与模型汇总，做 TTFT~input 线性拟合、按小时分组、prefix cache 命中统计。

```bash
python3 langfuse_span_breakdown.py --env ~/.keep/.calorie.env --prefix KEEP_LANGFUSE_ --limit 400 --csv spans_pre.csv
# 线上：--prefix KEEP_LANGFUSE_ONLINE_
# 通用 Langfuse：LANGFUSE_HOST/PUBLIC_KEY/SECRET_KEY 环境变量，不带 --env
```

Langfuse v4 适配要点（踩过的坑）：
- `/api/public/observations`、`/traces` 已 410，只有 `/api/public/v2/observations` 能用，cursor 分页
- 不带 `fields` 只给 id/latency/timeToFirstToken；要 `fields=core,basic,usage,model,metadata`（`basic` 才带 name）
- `v2/observations/{id}`、`v2/traces/*` 在 Keep PRE 返回 Next.js 404 页面，单条详情走不通

## 2026-09-16 PRE 第一次跑的结论（400 条）

| span | n | e2e p50 | p95 | 输入 p50 | 输出 p50 | 模型 |
|---|---|---|---|---|---|---|
| s2s.trace.turn | 270 | 937 ms | 1707 ms | 10355（其中 68% 命中缓存） | 147 | s2s-realtime |
| training.audio.ai.intent.llm.call | 128 | 411 ms | 831 ms | 3608 | 11 | doubao ep-…6467t |

**三个发现**

1. **TTFT 一条都没有。** Java OTel SDK 只打了 start/end，没有 completion_start_time。所以现在只能算端到端，拆不出 prefill / decode。这是 Phase 0 最重要的产出：先补数据，再谈拆解。
2. **prefix cache 的 block 粒度 = 256。** 222/270 条 realtime 回合命中缓存，命中 token 数全部是 256 的整数倍（5120 / 3840 / 10240 / 1280…）。03 篇讲的「只缓存完整 block」，在自家线上数据里直接看到了。
3. **intent 识别的耗时与输入长度无关。** 3.6K 输入、11 token 输出，e2e 稳在 285–830 ms，对 input_tokens 拟合斜率 ≈ 0。要么 prefix 全命中（这条 usage 没给 cached 字段，看不见），要么 prefill 成本被固定开销淹没。411 ms 里多数是「地板」：网络 + 网关 + 排队 + 首 token。s2s 回合的拟合 R² 只有 0.2——输入长度解释不了耗时，排队与 batch 邻居才是主因。

## 下一步（p0-2 补数据）

在 running-s2s / training.audio 的流式回调里，收到首个 delta 时补一个 OTel 属性，Langfuse 会映射成 `timeToFirstToken`：

```java
// 首个 chunk 到达时
span.setAttribute("langfuse.observation.completion_start_time", Instant.now().toString());
// 可选：每个 chunk 到达的相对 ms，脚本会算 chunk 间隔与「周期性顿」
span.setAttribute("langfuse.observation.metadata.chunk_times", chunkOffsetsJson);
```

补上后重跑脚本，就能拿到 Phase 0 要的三个数：网络地板、prefill 斜率、高峰排队增量。

## 2026-09-16 线上 agamotto-host-llm（AI 教练主项目，Langfuse v3.120，1268 万条 generation）

600 条最近 span，同样一条 TTFT 都没有。但这里有一个 PRE 没有的条件：**同一个豆包 endpoint（ep-…ncnfc）被 PlannerNode 和 SupervisorNode 两个 span 共用**，输入都在 6.4K 左右，输出一个 28、一个 108。于是不用 TTFT 也能拆：

```
e2e ≈ 100–150 ms + 18–29 µs × input_tokens + 6.3–6.6 ms × output_tokens     (n≈450, R²=0.75–0.88，两次抽样)
```

- **地板 ~100–150 ms**：网络 + 网关 + 排队 + 首 token 固定开销
- **prefill ~18–29 µs/token**：6.4K 输入约 110–180 ms
- **TPOT ~6.3–6.6 ms/token ≈ 150–160 tok/s**：这就是豆包这个 endpoint 的 decode 速度，两次抽样最稳的一个系数

对照 02 篇算的 H100 / 70B / TP=8 理论地板 6.34 ms/token——线上测出来的 6.3–6.6 ms 落在同一量级。不能据此断言背后硬件，但这是 Phase 0 第一次「客户端反推的数」和「文章里算的数」对上。

其余 span：
- ContextAssemblyNode（ep-…l7tg6）：1.9K 输入、105 输出却要 2.3 s——105 个可见 token 解释不了，大概率有隐藏 reasoning tokens。usage 没暴露 reasoning 字段，是数据缺口之二
- host.chat.kaka（Doubao-Seed-2.0-mini via higress）：68 输出 4.1 s，同样可疑；且 `.reply.stream` 这类 span 没有 usage

脚本已把这个「三参数拟合」做成默认输出：任何模型只要 ≥30 条带 in/out 的 span 就会给地板 / prefill / TPOT 三个数，R² < 0.6 时标红提醒别信。

## 项目覆盖

PK/SK 是项目级的。手里只有两把：PRE `training-audio-ai 端到端模型`、线上 `agamotto-host-llm`。其他项目要各自的 key，或 Langfuse 浏览器 cookie 走 tRPC。
