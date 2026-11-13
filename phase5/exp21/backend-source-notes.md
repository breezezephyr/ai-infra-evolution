# exp21 后端源码与模型身份交接

本轮只读；安装环境：`/root/vllm-env`，vLLM **0.8.5** / xgrammar **0.1.18**。限定读取已知安装包和 `/opt/models/Qwen3-0.6B`，没有启动/停止服务、HTTP 推理请求、CUDA 初始化、安装、模型下载或远端文件写入。详细源码片段、行号、SHA-256、CPU 探针和身份在 [backend-source-notes.json](backend-source-notes.json)。

## 必须纠正的 CLI / 请求字段

之前建议的 `--guided-decoding-backend xgrammar:no-fallback` **无效**。本轮用真实 `EngineArgs.add_cli_args(...).parse_args(...)` 复现 invalid choice，退出码 2；该参数实际 choices 是 auto / guidance / lm-format-enforcer / outlines / xgrammar。

服务器用：

```text
--guided-decoding-backend xgrammar
```

在需要约束的每条请求 **顶层** 带：

```json
{"guided_decoding_backend":"xgrammar:no-fallback"}
```

OpenAI SDK 对应 `extra_body={"guided_decoding_backend":"xgrammar:no-fallback"}`。已执行真实 `ChatCompletionRequest.model_validate → to_sampling_params → maybe_backend_fallback`：请求字符串保留；数组 minItems/maxItems 在 no-fallback 下抛 ValueError；普通 xgrammar 改成 outlines。EngineArgs parser 未发现独立禁用 fallback 的 CLI flag。旧 remote-preflight 中带后缀的候选 CLI 由本节更正，不应再使用。

主代理随后报告已在 **8021 实测请求级 no-fallback**：integer(minimum=0, maximum=100)→200；array maxItems→400，明确 item limits 不支持；原始证据据报保存为 bounds-probes.json。本代理没有读取或哈希该文件。此前四个控制也由主代理报告：FREE / {} / CONSTRAINED21，以及 invented type→400。它们不是本代理发送的请求。

主代理确认正式 `gpu-formal-v1` 保留 20 任务 × 2 seeds × 3 组，共计划 120 calls；schema 组数组 5×2=10 条预期 400，其余 30 条预计进入生成。本交接不删 schema、不改 cases，不宣称正式运行已完成。

## 支持子集与明确限制

| 关键字/组合 | 本轮明确判断 | 已安装 native CPU 证据 |
|---|---|---|
| integer minimum+maximum | **测试过的双边整数闭区间可用**，不是全面支持声明 | [2,4]、[0,100] 的上下界内外探针吻合；nested object 同样通过 |
| integer minimum 单边 | **存在实证缺陷，不能视为可靠支持** | minimum=2 仍接收 1；生成 grammar 为 `root ::= (([2-9]) \| ([1-9] [0-9]*))`，第二分支容许 1 |
| integer maximum 单边 | **测试子集通过** | maximum=4 接收 3/4，拒绝 5；未推广所有范围 |
| integer 非整数界限 | **编译拒绝** | minimum=1.5 抛 minimum must be an integer；这不能与 JSON Schema 自身的合法性混为一谈 |
| number minimum+maximum | **实现不可靠，不可写成完整支持** | [1.25,2.75] 接收 1.25/1.5/2.0/2.75，却拒绝合法 2；还接收非法 JSON `1a25`、`2x75` |
| array minItems / maxItems | **vLLM xgrammar 路径明确不支持** | recursive precheck 命中；真实 fallback 函数在 no-fallback 下抛错，普通 xgrammar 切 outlines；嵌套数组也命中 |
| 直接绕过 vLLM 编译 array | **不能据编译成功称支持** | native compiler 接收 minItems schema，却允许 []/[1]；它并未落实长度 |
| required / additionalProperties:false / enum | **基础探针子集通过** | 缺 x、额外 y 被拒；enum a/b 接收 a,b，拒 c |

复核用了两条 native CPU 路径：`Grammar.from_json_schema`＋库测试 matcher，以及实际生产同名 `GrammarCompiler.compile_json_schema`＋`GrammarMatcher` 全字符串匹配。后一条另与 `json.loads`、`jsonschema.Draft202012Validator` 对照。无 tokenizer 词表的字符匹配能验证语言语义，不能冒充 Qwen GPU 解码。

**no-fallback 只禁止切换后端，不会修复 compiler 的语义缺陷。** 独立的 JSON 解析、schema 校验、业务正确性三层结果仍必须保留。

当前安装版本 `vllm/model_executor/guided_decoding/utils.py:6–48` 的 xgrammar 不支持特性预检：

| 显式 type | 命中的关键字 |
|---|---|
| integer / number | multipleOf |
| array | uniqueItems, contains, minContains, maxContains, minItems, maxItems |
| string | minLength, maxLength, format |
| object | minProperties, maxProperties, propertyNames, patternProperties |

这张表是 vLLM 的递归预检政策，不是完整 xgrammar 能力清单。minimum/maximum 不在此表，并不等于其执行语义完全正确。

## response_format → 编译 → mask → 采样

所有下列路径相对于 `/root/vllm-env/lib/python3.12/site-packages/`；同名 JSON 保存完整文件 SHA-256 和选定源码原文。

1. `vllm/entrypoints/openai/serving_chat.py:221–224` 调用请求 `to_sampling_params`。在 `protocol.py:495–518,547`，json_object→bool，json_schema.schema→guided_json，连同请求级 guided_decoding_backend 进入 `GuidedDecodingParams` 和 `SamplingParams.guided_decoding`。strict 虽有字段声明，该映射不把它作为独立执行开关。
2. V0 `engine/multiprocessing/client.py:609–638` 经 `engine/async_llm_engine.py:538–578` 构建 processor。请求 backend 优先于服务器默认值；构造后放进 logits_processors，并清掉原 guided_decoding。processor 另经 cloudpickle 传入引擎，`engine/multiprocessing/engine.py:254–262` 恢复。
3. `model_executor/guided_decoding/__init__.py:23–96,111–129` 执行 fallback 预检；`sampling_params.py:72–99` 把冒号前后解析成 backend_name/options，识别 no-fallback 并在回退分支抛错。
4. `guided_decoding/xgrammar_decoding.py:37–47,158–211`：factory→GrammarConfig→`xgr.Grammar.from_json_schema` 先验证，RuntimeError 转 ValueError，再构造 XGrammarLogitsProcessor。
5. 同文件 `:122–143,293–345`：worker 首次调用时惰性取得按 tokenizer 身份缓存的 compiler，`compile_json_schema` 产生 compiled ctx。**仅 API 收到字段不证明已走到首次编译/采样。**
6. `worker/model_runner.py:1810–1820` 先 compute_logits 再 sampler；Qwen3 `models/qwen3.py:303–310` 调用共享 logits_processor。`layers/logits_processor.py:80–85,141–196` 调用每条序列的约束 processor。
7. `guided_decoding/xgrammar_decoding.py:347–401`：初始化 matcher；后续接收上次 sampled token；`fill_next_token_bitmask`；mask 移到 scores.device；`apply_token_bitmask_inplace`。若启用 reasoning parser 且 reasoning 未结束，源码会先跳过该约束处理。
8. `xgrammar/matcher.py:56–152` 根据设备分派；CUDA 的 `kernels/apply_token_bitmask_inplace_triton.py:72–77` 将不允许 token 的 logits 置为 -inf。随后 `vllm/model_executor/layers/sampler.py:269–294` 经温度/过滤、softmax/log_softmax 和 sample 选 token。

这是**安装源码调用链**。本轮执行了 CPU 请求转换/fallback/native compiler，不执行 CUDA mask。主代理 middleware bodyhash/settings 证明 HTTP 接收内容；对于每次真实生成，不能将这层证据单独称为 mask 执行追踪。

## 模型和二进制身份

路径：`/opt/models/Qwen3-0.6B`。以下均完整读取计算 SHA-256，读取前后 size/mtime 稳定。没有加载权重，revision/来源 commit 未确证。

| 文件 | bytes | SHA-256 |
|---|---:|---|
| config.json | 726 | `660db3b73d788119c04535e48cf9be5f55bc3100841a718637ae695b442f27dd` |
| tokenizer_config.json | 9732 | `d5d09f07b48c3086c508b30d1c9114bd1189145b74e982a265350c923acd8101` |
| tokenizer.json | 11422654 | `aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4` |
| model.safetensors 单 shard | 1503300328 | `f47f71177f32bcd101b7573ec9171e6a57f4f4d31148d38e382306f42996874b` |

native chat_template（从 tokenizer_config.json 字段提取 UTF-8）的 SHA-256：

```text
a55ee1b1660128b7098723e0abcd92caa0788061051c62d51cbe87d9cf1974d8
```

JSON 另保存原始 config、generation_config、完整 chat_template 文本，以及 vocab.json、merges.txt、configuration.json、generation_config.json 的文件身份。config 声明 Qwen3ForCausalLM / qwen3 / bfloat16、模型上下文 40960；tokenizer_config 声明 model_max_length=131072；两者都是文件声明，实际服务 max-model-len 由主代理启动配置决定。generation_config 含 do_sample=true、temperature=.6、top_k=20、top_p=.95；实际请求覆盖情况应从主代理 settings 记录核对。

已安装 native xgrammar binary：

```text
/root/vllm-env/lib/python3.12/site-packages/xgrammar/xgrammar_bindings.cpython-312-x86_64-linux-gnu.so
17258920 bytes
sha256 550ef2c43eff7030f0e9ea19d805bc35a9ba11bbb25e7ec9900bc360c89c072f
```

已保存 vLLM/xgrammar METADATA 身份；vLLM 元数据明确依赖 xgrammar==0.1.18。原生二进制身份与实测语义是本轮结论依据，不能仅凭版本号推断完整支持。

## 版本文档与证据层次

[vLLM 0.8.5 Structured Outputs](https://docs.vllm.ai/en/v0.8.5/features/structured_outputs.html) 说明 guided 请求参数和 backend 选择；本轮对 CLI 与请求字段的判断来自实际安装类执行，未照搬文档。

[xgrammar v0.1.18 JSON Schema converter](https://raw.githubusercontent.com/mlc-ai/xgrammar/v0.1.18/cpp/json_schema_converter.cc) 的整数/number 分支调用范围生成器，array 分支列出不支持的 item limits；只用作固定版本上游佐证。抓取内容 SHA-256：`f0f06abce1d8eb4bef669cb2848215647308bed584b4b14fe08cda2e360793ba`。本地内存抓取原文件行号为 VisitInteger 1550、VisitNumber 1609、VisitArray 1872；浏览工具文本解析行号与原文件不同，不混用。JSON 仅保存四行极短摘录和文件摘要，没有把上游 C++ 冒充 wheel 自带源码。tag 精确 commit 查询被 GitHub 403 限流，未进一步扩展查询。

vLLM 文档 HTML 抓取 SHA-256：`47906c1ab38868ccc0c9a821f07dcd97e0040313793dc8d014eab56533355351`。

证据依次标为：版本文档、当前安装源码、当前 CPU 函数/编译/匹配执行、主代理报告的 8021 实测。正式 120 calls 的完成状态和结果由主代理报告；本文件不推断其成功率。

