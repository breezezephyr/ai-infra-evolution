# exp12 · 离线账本和叫号回放

这次不连接 DARYU，不启动或修改服务。历史测量为 2026-09-23 的 exp5/7、09-29 的 exp11；本次回放日期 2026-10-22。

## 重现

从仓库根目录运行：

```bash
python3 -m unittest discover -s phase3b/exp12 -p 'test_*.py'
python3 phase3b/exp12/analyze.py
phase2/.venv/bin/python phase3b/exp12/plot.py
```

输出 `phase3b/results/exp12-summary.json`、`exp12-groups.jsonl`、`exp12-queue.jsonl` 与 `phase3b/img/exp12.png`。summary 保存输入文件的 SHA-256，便于确认回放了哪份数据。`fixture` 是四条手写计费样例，不是观测记录。

## 计数合同

- exp7 引擎 `prompt_tok` 包含缓存前缀，是完整 prompt 长度累计。
- vLLM 0.8.5 **V1** 的 `gpu_prefix_cache_hits/queries` 按 block 计数。本地 `bench-pair@.service` 未显式改 block-size，本次按官方 CUDA 默认 **16 token** 换算：窗口 `cached = hits × 16`。历史环境文件可通过 EXTRA_ARGS 覆盖，日志未保存运行时 block_size，所以16是默认配置推断；四组后端的 `P−queries×16` 均落在每请求0..16 token的尾部范围内，与该推断一致。本次各窗口无抢占；不能把这套单位默认套给其他引擎/版本。
- 官方源码：[KV 命中累计](https://github.com/vllm-project/vllm/blob/v0.8.5/vllm/v1/core/kv_cache_manager.py#L147-L161)、[指标导出](https://github.com/vllm-project/vllm/blob/v0.8.5/vllm/v1/metrics/loggers.py#L376-L389)、[完整输入统计](https://github.com/vllm-project/vllm/blob/v0.8.5/vllm/v1/metrics/stats.py#L100-L109)。逐请求 cached 和 tenant 字段在旧日志中没有，不能反推出租户账。
- [CUDA 默认块大小源码](https://github.com/vllm-project/vllm/blob/v0.8.5/vllm/platforms/cuda.py#L141-L143)。
- 教学费率：每千 token 输入 1 点、缓存输入 0.2 点、输出 3 点；没有币种，不是任何提供商报价。费用模型 `(P-C)×1/1000 + C×0.2/1000 + O×3/1000`。缓存 C 是输入 P 的子集。
- `prefix_group` 保留实验的 0..7 组，不改名为真实租户。客户端 `n_out` 是 SSE 事件数；token 总账使用引擎 `gen_tok`。req/gw 无可靠 request_id，不按完成顺序强行拼表。

## 卡秒口径

仅取客户端首个事件到末个事件的重叠区间。同一张物理 GPU 上的全部流一起等分区间，不能每副本各算一张卡。没有活跃生成流的时段单列 `unassigned_s`，并检查所有分摊加未分配时间等于观测窗。它是生成流时间代理，包含网络/调度等待，不是实测 GPU 核函数时间；prefill 与启动开销不能从中拆出，未分配也不等于 GPU 空闲。

## 排队口径

成功行：`准入 = ts − total_ms`；`入队 = 准入 − queue_ms`。超时行：`离队 = ts`，`入队 = ts − queue_ms`，真实等到准入的时长未知（右删失）。全程毫秒级时间反推，有舍入与日志写入误差。

回放入队时还没离队的前序请求得到近似排位 Q，预测 `(Q+1)/μ`。μ 固定用更早 exp1-c32 的服务率 1.45478 req/s，不用当前窗口的未来完成数。预测不使用当前请求最终等待。仅在事后评分时，选择等到准入且等待>1ms的133条；113条超时另报，10条未明显排队不进这个误差分母。

这个队列有 token 预算、队首阻塞、批量放行和10秒后离队，Q 不等于前面必须完成的请求数。原始日志还缺少入队事件与 request_id，因此本次是历史近似回放，不能视为已验证的在线预测器。
