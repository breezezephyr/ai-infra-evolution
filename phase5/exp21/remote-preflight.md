# exp21 / P5·3 远端只读预检

观测时间：**2026-10-26 10:38:13–10:42:48（Asia/Shanghai）**。结论：**SSH 可达，GPU 有空闲，旧 vLLM 环境和 Qwen3 小模型在盘；推理后端当前未在线。** 这是预检完成，不能据此宣称 GPU 对照实验或约束执行完成。

## 立即交接

| 项目 | 本轮证据 |
|---|---|
| SSH | `ssh -p 22 researcher@SSH_HOST`，四次只读查询均退出 0；实际连接约 2.26 / 3.96 / 6.05 / 2.97 秒 |
| 限时 | BatchMode、ConnectTimeout=8、ConnectionAttempts=1、ServerAliveInterval=5、ServerAliveCountMax=2、StrictHostKeyChecking=yes；本地对子进程设 55/55/55/40 秒整体 timeout |
| GPU | RTX 4060 Laptop，8188 MiB 总量；驱动报告 used=675、free=7283 MiB，利用率 0% |
| 进程 | WSL compute-app 列表为空；图形进程 Xwayland PID 32、显存 N/A。Windows 筛选 python/comfy/llama/ollama/vllm 无结果。WSL 视野有限，不能把空计算列表当作全部 Windows GPU 占用证据 |
| GPU 工具 | **`/usr/lib/wsl/lib/nvidia-smi`**；非交互 SSH 默认 PATH 找不到裸命令 `nvidia-smi` |
| 当前服务 | `gpu-router.service` active、PID 232、`:8000`；`bench-vllm`、`qwen3-embedding`、`bonsai-llm` 均 inactive/dead |
| 实际推理入口 | `:8001/8002/8003` 的 health/version/models/openapi 均 connection refused；已知 8004/8005/8010/8080/11434/30000 也未监听 |
| 生成环境 | **`/root/vllm-env/bin/vllm`**；Python 3.12.3，已安装 vLLM **0.8.5**；没有当前在线 vLLM 的版本响应 |
| 小模型 | 首选 **`/opt/models/Qwen3-0.6B`**，备用 `/opt/models/Qwen3-1.7B`；没有发现 0.5B。权重文件及全部索引分片在盘，未加载 GPU 权重 |
| 备用环境 | `/root/voice-env/bin/python` 也可导入同一 vLLM/torch/transformers 包；`exp15-env` 没有这些包 |
| 模板 | 两个生成模型的 `tokenizer_config.json:chat_template` 均可用；已通过 AutoTokenizer 原生渲染/编码，`enable_thinking=false` 有效；未手写模板 |

free 是驱动直接报告值，不以 total-used 重新推算。没有停止 ComfyUI，也没有启停任何后端。

## 三组请求字段

20 个任务 / 2 seeds 由主代理冻结；本预检不改任务、seed、采样或校验器。共同使用 Qwen 原生模板，公共字段：

```json
{"model":"exp21-qwen3-0.6b","chat_template_kwargs":{"enable_thinking":false}}
```

| 组 | wire 字段差异 | 已有证据与边界 |
|---|---|---|
| 普通提示 | 省略 `response_format` 和所有 `guided_*` 约束字段 | 只在 prompt 中要求 JSON；不选解码约束 |
| JSON 模式 | `"response_format":{"type":"json_object"}` | 源码转为 `GuidedDecodingParams.json_object=True`，这是解码约束；并非只提示格式，也不绑定业务 schema |
| Schema 约束 | `"response_format":{"type":"json_schema","json_schema":{"name":"exp21","schema":SCHEMA,"strict":true}}` | SCHEMA 必须替换为冻结任务的原始对象；源码映射到 `guided_json`。不是 JSON 可解析率或答案正确率的保证 |

三组均省略 tools/tool_choice，避免工具 schema 优先级影响对照；不再叠加 `guided_json`、regex、choice、grammar。保留主代理冻结的消息和采样设置。

**证据等级：以上是当前安装源码支持与本机 CPU tokenizer 执行，尚无在线 HTTP 字段接收、compiler、logits mask 或 GPU 生成证据。**

## 最短命令与启动候选

已执行的只读 GPU 查询可重用：

```bash
ssh -T -o BatchMode=yes -o ConnectTimeout=8 -p 22 researcher@SSH_HOST '/usr/lib/wsl/lib/nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu --format=csv,noheader,nounits'
```

SSH 整体限时仍应由调用方的 `subprocess.run(..., timeout=55)` 保证；ConnectTimeout 只覆盖建连。

下面在远端 shell 使用的启动候选**没有执行**。已核验可执行环境、模型文件、所有列出参数的已安装声明及 native tokenizer；未核验启动成功、显存预算或约束推理。

```bash
PYTHONPATH=/opt/p2/stub VLLM_USE_V1=0 /root/vllm-env/bin/vllm serve /opt/models/Qwen3-0.6B --served-model-name exp21-qwen3-0.6b --host 127.0.0.1 --port 8021 --dtype bfloat16 --max-model-len 2048 --max-num-seqs 4 --gpu-memory-utilization 0.60 --enforce-eager --guided-decoding-backend xgrammar:no-fallback
```

未来入口：`http://127.0.0.1:8021/v1/chat/completions`，model=`exp21-qwen3-0.6b`。8021 在本轮 ss 全量 TCP 监听快照中空闲。2048 上下文、4 并发上限及 0.60 GPU 比例是保守候选，不是实测容量；启动前需按冻结输入检查上下文预算。

`VLLM_USE_V1=0` 显式选取本轮追踪的 V0 guided-decoding 路径；`xgrammar:no-fallback` 让该路径的后端回退分支抛错。普通提示组没有约束，不会因为服务器默认后端参数而自动获得 JSON mask。沿用已有 `/opt/p2/stub/flashinfer` 仅让旧 flashinfer 抛 ImportError，未修包或安装依赖。

**不要直接执行旧 `systemctl start bench-vllm` 作为这次独立入口。** 当前 unit 仍固定 1.7B、8003，并配置 `Conflicts=qwen3-embedding.service bonsai-llm.service`；其旧参数为 GPU_UTIL=.90、MAX_MODEL_LEN=8192、MAX_NUM_SEQS=256、MAX_BATCHED_TOKENS=8192，无 drop-in。这些是配置，当前未生效为在线推理。旧 `phase2/bench/lib.sh` 会改配置/启停服务/安装清理 trap，不可 source 来做只读预检。

## 结构约束能力证据

远端源码根目录：`/root/vllm-env/lib/python3.12/site-packages/vllm`。完整选择片段、文件 SHA-256、查询退出码和原始响应保存在同名 JSON；均不含完整环境或凭据。

| 能力 | 当前安装源码位置 | 结论 |
|---|---|---|
| OpenAPI 请求模型字段 | `entrypoints/openai/protocol.py:134–161,249,326–379` | response_format 支持 text/json_object/json_schema，另有 structural_tag union；native `chat_template_kwargs` 可传 |
| JSON Schema wire 结构 | `protocol.py:134–140` | name 必填；schema 是内部 json_schema 的 wire alias；strict 作为字段声明 |
| 格式要求传到采样 | `protocol.py:495–518,547` | json_object→bool；json_schema.schema→guided_json→GuidedDecodingParams→SamplingParams；该映射没有用 strict 作独立开关 |
| 旧版 guided 接口 | `protocol.py:343–379` | guided_json/regex/choice/grammar/decoding_backend/whitespace_pattern 存在；该版本字段描述漏提 xgrammar，实际 dispatcher 源码有分支 |
| 新字段陷阱 | `protocol.py:46–76`，本轮提取两个 Request 的字段清单 | **没有 `structured_outputs` 声明**；extra=allow，日志称未知字段 ignored。不能从未报错或字段被保留推断约束执行 |
| 约束互斥 | `sampling_params.py:101–110` | json、regex、choice、grammar、json_object 只能选一种 |
| 工具 schema 优先 | `protocol.py:510–518,550–601` | `_get_guided_json_from_tool() or guided_json`；named/required tool 可能覆盖 response-format schema |
| 回退与失败 | `model_executor/guided_decoding/__init__.py:23–96`；`sampling_params.py:73–99` | traced V0 分支可回退 outlines；no-fallback 使回退位置报 ValueError；没有进行 compiler 或生成验证 |
| 模式的默认后端 | `config.py:3143–3152` | 源码默认依赖 V1：auto 或 xgrammar；不能据此断言当前在线后端，因为没有引擎 |
| schema 特性限制 | `model_executor/guided_decoding/utils.py:6–48` | 见下表；这是安装版本的回退检测规则，不是完整编译器能力表 |

当前 vLLM 的 xgrammar 回退检测关键字：

| schema type | 会触发该检测的关键字 |
|---|---|
| integer / number | multipleOf |
| array | uniqueItems, contains, minContains, maxContains, minItems, maxItems |
| string | minLength, maxLength, format |
| object | minProperties, maxProperties, propertyNames, patternProperties |

若冻结任务含上述字段，候选 no-fallback 路径预计显式失败。记录不支持，或由主代理明确选择并验证已安装的其他后端；不可静默删关键字。已安装 xgrammar 0.1.18、outlines 0.1.11、lm-format-enforcer 0.10.12 只是包元数据证据，不代表导入、schema 编译或解码已成功。

## 模型与版本

| 项目 | 本轮读到的值 |
|---|---|
| Qwen3-0.6B 权重 | model.safetensors，1,503,300,328 bytes |
| Qwen3-1.7B 权重 | 两分片分别 3,441,185,608 / 622,329,984 bytes；索引引用文件均存在 |
| 生成模型配置 | Qwen3ForCausalLM / qwen3 / bfloat16；权重 revision 未核验 |
| 两个模板 SHA-256 | `a55ee1b1660128b7098723e0abcd92caa0788061051c62d51cbe87d9cf1974d8` |
| 两个 tokenizer_config SHA-256 | `d5d09f07b48c3086c508b30d1c9114bd1189145b74e982a265350c923acd8101` |
| CPU 模板检查 | Qwen2TokenizerFast，关闭 thinking 的同一测试消息 15 tokens，开启为 11；两模型结果一致 |
| torch | 包元数据 2.6.0；CPU 进程实际 import 为 **2.6.0+cu124**，build CUDA=12.4；CUDA 未初始化 |
| transformers / tokenizers | 4.51.3 / 0.21.4 |
| FastAPI / Pydantic | 0.136.3 / 2.13.5 |
| 驱动 / NVIDIA-SMI | 572.83 / 570.133.07；nvidia-smi 显示 CUDA 12.8 为驱动侧支持值，不能替代 torch build CUDA |
| Conda | 已查 /root/miniconda3、/root/anaconda3、/opt/conda 常用 Python 路径均不存在；不是全盘搜索。已验证 venv 可直接使用，无须激活 conda |
| 其他目录 | Qwen3-Embedding-0.6B、Ternary-Bonsai-2-27B、faster-whisper-small、Kokoro-82M-v1.1-zh；embedding 不作为本次生成模型 |

## 文档、配置与当前 runtime 的分界

- **历史文档/脚本**：phase2 README、phase2/daryu/bench-vllm.service/default、phase2/bench/lib.sh、phase3b/bench/exp8b_graph6.sh、phase3b/exp13、phase4/exp14 README/models.py、phase4/exp17/launch.sh 提供连接、启动和模板线索；都没有执行旧实验脚本。phase4 的 342 MiB 快照仅是旧值。
- **当前配置**：本轮只读核对远端 bench unit、允许列出的实验参数、drop-in 和 flashinfer stub；实际仍指向 1.7B/8003，没有改写。
- **当前 runtime**：systemctl、ss、GPU 查询、GET 及 CPU tokenizer 渲染均在本轮完成；后端的 12 次 GET 全部连接拒绝。router 的安全 GET 之前先查源码，之后再核对四个服务状态未变。
- **特别注意**：router `/health` 返回 200 / backend=embedding，`/v1/models` 返回 embedding 和 Bonsai，但 `proxy.py:62–82,318–331` 直接构造这些元数据；不证明模型在线。没有请求 router 的生成接口或会等待后端的 openapi passthrough。
- **仍缺的证据**：服务启动就绪、live /version/openapi、请求接收与实际选用后端、schema compiler、token mask、真实输出/finish_reason，以及主代理的独立 JSON/schema/业务三层校验。

本次仅写两份预检报告。未安装、下载、启停服务、改远端配置或写远端文件；没有 runner/cases 改动，也没有凭据、完整 env 或 SSH 私钥输出到报告。

