# exp29：Qwen3-4B 在独立 Kaggle Notebook 上的接口证据

2026-11-10，run ID：`exp29-kaggle-20261110-a74160a0`。

本轮已经完成真实 GPU 推理和本地原始证据回读。用户要求把首轮模型调大后，采用 **Qwen/Qwen3-4B、FP16**，没有继续用 0.6B。它独立于旧图像 Notebook 和 exp28 的 404 失败记录；旧实验没有被重写成成功。

## 实际运行环境

| 项目 | 实际记录 |
|---|---|
| Notebook | [P5 Infra - Qwen3 GPU Evidence](https://www.kaggle.com/code/example/experiment-notebook)，Quick Save Version #1 |
| 模型 | Qwen/Qwen3-4B，4,022,468,096 参数 |
| 模型 revision | `1cfa9a7208912126459214e8b04321603b3df60c`，10 个文件逐一记录 SHA256 |
| GPU | 平台分配 2×Tesla T4；模型全部参数仅在 cuda:0，FP16 |
| 后端 | Transformers 4.51.3 `generate`，eager attention；Torch 2.11.0+cu130 / CUDA 13.0 |
| 模板 | Qwen 原生 chat template，`enable_thinking=False`；输入实际为 26 token |
| 采样 | greedy，seed=29，串行，无自动重试 |
| HTTP | 自建 FastAPI/Uvicorn 环回服务，`127.0.0.1:8765`；没有公网接口 |
| 显存 | 模型加载后 allocated 7.545 GiB；本进程 peak allocated 7.561 GiB，peak reserved 7.576 GiB |

显存数据来自 PyTorch 本进程 allocator，不等于整张卡的全部占用，也不是连续采样的系统级峰值。[环境记录](exp29/exp29-kaggle-20261110-a74160a0/environment.json)保留具体字节数、设备空闲内存、参数设备与数据类型，以及运行库、模型文件和实现源码的 hash。

## 5 个用例，3 次生成

| 用例 | HTTP | 原生输出 token | 结果 |
|---|---:|---:|---|
| 不存在的模型别名 | 404 | 0 | 拒绝；没有进入 `generate` |
| `max_tokens=65`，超出接口单次上限 64 | 422 | 0 | 拒绝；没有进入 `generate` |
| 普通响应，max_tokens=32 | 200 | 20 | finish=stop，正文与原生序列解码一致 |
| 相同提示词的流式响应，max_tokens=32 | 200 | 20 | 正文、finish、usage、`[DONE]` 均完整 |
| max_tokens=1 | 200 | 1 | finish=length，返回“天空”；只证明上限生效 |

共 5 次 POST、3 次完成的生成，预留输出上限 32+32+1=65，实际输出 **41 token**；三次输入共 78 token，总原生 usage 为 119 token，输出计数包含 EOS。计数直接取 `generate.sequences` 的输入/输出 ID，没有通过重新编码返回正文估算。[预算账本](exp29/exp29-kaggle-20261110-a74160a0/budget.json)与[逐请求摘要](exp29/exp29-kaggle-20261110-a74160a0/summary.json)一致。

两次普通/流式回答在本轮中的输入 ID、输出 ID、解码正文完全一致：

> 天空呈现蓝色是因为阳光中的蓝光被大气中的分子散射到了我们的视线中。

这是两个串行请求的观测，不是跨机器或任意请求的确定性保证，也没有开展回答质量评测。

## 时间数据应怎样读

| 用例 | 客户端首个非空内容 | 客户端完成 | 服务端首次 token 回调 | 服务端 generate 完成 |
|---|---:|---:|---:|---:|
| 普通响应 | 2079.08 ms | 2079.18 ms | 1005.72 ms | 2070.61 ms |
| 流式响应 | 117.42 ms | 1126.44 ms | 112.16 ms | 1119.37 ms |
| 1-token 上限 | 61.85 ms | 61.95 ms | 54.81 ms | 55.61 ms |

普通响应的“首个内容”是客户端收齐 JSON 并解析正文时的观测；流式响应是解析出首个非空 content delta 时的观测，不能把两者统一写成模型 TTFT。服务端回调属于 CPU 侧 streamer 观测，不是 CUDA kernel 时间。两边分别使用自己的 monotonic 时钟，不相减。

普通请求先执行、流式请求后执行，存在首次推理与后续推理的顺序差异。没有做配对随机化或重复测量，不能据此报告“流式使模型提速多少”，也不报告 P95 或生产 SLO。流式响应本轮被读为 23 个 HTTP entity 片段；片段不是 TCP 包，更不是一片一 token。

## 已留存的证据与收尾

- 原始归档：[ZIP（未收录：原始归档）](../../docs/REPRODUCIBILITY.md)，SHA256 `65e781eeb6c7b5e6bc5943f9c6f5cf73e27e37fddae282d35afde74a78a1d1f1`。
- [已执行 Notebook](exp29/exp29-kaggle-version1-executed.ipynb)含执行计数与输出；源码与本地最终脚本一致，输出包含同一份 summary 和归档 hash。
- [本地回读](exp29/local-readback.json)核验 44 个归档文件的长度/hash，逐片拼回原始 HTTP body，核对请求身份、原生 token ID、HTTP usage、正文和 SSE 结束标记。
- 6 项 CPU SSE 检查覆盖 Unicode 跨片、CR/LF、多行 data、错误帧及终态顺序。CPU 检查不是额外 GPU 样本。
- 自建推理子进程 PID 155 已正常退出，exitcode=0；Notebook 最终会话状态记录在 [active-run.json](../exp29/active-run.json)。旧 Notebook 未被启动、重置或停止。

## 可补充到系列的内容

P5·7 可增加“先证明真实模型请求路径”：同一个 request ID 串起请求字节、入口拒绝、生成调用和原生 usage。这轮使用自建最小服务，不代表原有网关或真实多租户集成已经在 Kaggle 重跑。

P5·8 可增加“收到正文还不算流式完成”：正文拼接、finish、usage、`[DONE]` 必须一起对账。本轮没有故障注入，没有证明断流重试、取消传播或故障转移。

P5·9 可增加“模型变大后仍按证据交班”：权重版本和 hash、实际设备放置、计数来源、全部计划分母、下载回读和资源收尾同时留存。单次成功不能替代质量、并发容量或成本评测。

本轮未执行 DeepInfer、deepseek-recipe、vLLM 连续批处理、真实 KV 转移、并发压测、货币计费或语音任务；也没有重跑 P5 原有端到端网关验收。实验执行阶段没有自动改动公众号正文、配图或草稿箱。

模型与模板选项的官方说明见 [Qwen3-4B 模型卡](https://huggingface.co/Qwen/Qwen3-4B)。本页所有实测数字以以上本轮原始记录为准。

## 后续草稿修改（2026-11-10）

随后按用户要求，已将上述三组补充分别写入P5·7、P5·8、P5·9正文，并通过 `draft/update` 更新原公众号草稿。原media_id和旧正文保留，每篇只插入一段补验；封面、正文图片、摘要及评论设置未变。三篇已回读核对，未群发。见[发布更新回执（未收录：发布或账号材料）](../../docs/PRIVACY.md)。该步骤没有重新启动GPU，也没有新增实验样本。
