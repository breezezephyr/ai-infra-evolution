# exp19 fixture 合约与源码预期

固定源码：`935817c66f5d6e64838f419692545f06787e485f`。36 条原始请求，27 条预期转换成功、9 条预期转换拒绝；Chat 11、Responses 12、Messages 13。这里只冻结输入和源码支持的预期，未声称 wheel 已实测通过。源码本轮通过固定 GitHub revision 只读核对；PyPI 0.2.0 与该 commit 的二进制对应关系由主代理另行记录。无模型推理、工具执行、流解析或依赖安装。

## 执行与字段约定

- 每条从 `input` 原样构造相应的 `ChatCompletionRequest / ResponsesRequest / MessagesRequest`，不补字段、不改模型名。构造及 `convert` 同属请求接收/转换阶段；任何失败均保留原文与阶段。
- 每条新建 `ConversionOptions()`，禁止把前一条的 alias 或 web_search 设置泄漏到下一条。`options.alias` 通过 `with_model_alias` 只加入该名称：`v41 -> ModelVersion.DeepseekV41Flash`，`v4 -> ModelVersion.DeepseekV4Pro`。同一合理名称 `deepseek-chat` 未注册时拒绝，显式注册后接受。
- `options.web_search: default` 表示保持库默认；`reject/drop` 分别作用于当前协议的 `responses_web_search / messages_web_search`。这不是请求 body 字段。
- `expect.conversion` 仅描述请求接收/转换。成功后按实际 `model_version` 选择 encoding 及固定源码内匹配的 tokenizer；tokenizer 缺失及上下文超界是后续检查，不改变 conversion 的预期。
- `contains_text` 检查渲染 prompt 包含所列原文；不据此宣称模型会输出该文本。
- `not_contains_control` 只指“该拼写在用户原文中的出现不能被标成控制 token”；**不是**要求整个 prompt 不包含该字符串或不包含模板本身的同名控制 token。需要结合特殊区间和编码计数验收。
- `facts` 为可验收的规范化观测值；未列出的字段没有预设。浮点属性用绝对误差 `1e-6`。`null` 是断言值，不能当缺测跳过。字段差异的解释在本文件，不通过重写实际结果来消除。

## 三协议字段与最小输入差异

| 项目 | Chat Completions | Responses | Messages |
|---|---|---|---|
| 固定源码要求 | `model`、`messages`；messages 不能为空 | `model`；input 可省略，但省略/null 时必须有非空 instructions | `model`、`messages`；messages 不能为空 |
| 用户文本 | messages 的 user.content | input 字符串，或 input 消息项 | messages 的 user.content |
| 系统指令 | messages 的 system.content | 顶层 instructions，或输入 system 项 | 顶层 system |
| 历史思考 | assistant.reasoning_content | reasoning 项的 content[].text；summary/encrypted_content 不作恢复 | assistant.content 的 thinking 块；signature 不参与转换 |
| 思考开关/努力 | thinking.type 优先于 reasoning_effort | reasoning.effort；无 thinking 设置 | thinking.type 优先于 output_config.effort；budget_tokens 不参与推理预算解析 |
| 工具声明 | tools[].function 内 name/parameters | tools[] 直接 name/parameters | tools[] 直接 name/input_schema，不带 type |
| 显式输出上限 | max_tokens | max_output_tokens | max_tokens |
| 停止串 | stop（字符串或数组） | 没有 stop 字段；未知顶层 stop 忽略 | stop_sequences 数组 |

三个适配器的输出上限字段在本库 schema 中均为可选项，Messages fixture 省略 max_tokens 是有意验证库接受面，不能据此推断外部 API 服务也允许省略。

源码：[Chat schema](https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/deepseek-recipe/src/protocol/openai/chat_completion/request/schema.rs#L7-L60)、[Responses schema](https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/deepseek-recipe/src/protocol/openai/responses/request/schema.rs#L7-L35)、[Messages schema](https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/deepseek-recipe/src/protocol/anthropic/messages/request/schema.rs#L7-L35)；[Chat 空消息](https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/deepseek-recipe/src/protocol/openai/chat_completion/request/convert.rs#L415-L422)、[Responses input/instructions](https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/deepseek-recipe/src/protocol/openai/responses/request/convert.rs#L761-L787)、[Messages 空消息](https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/deepseek-recipe/src/protocol/anthropic/messages/request/convert.rs#L426-L447)。

## 预期矩阵

| family | 条数 | Chat | Responses | Messages | 验收重点 |
|---|---:|---|---|---|---|
| text_default | 3 | ok | ok | ok | 默认 thinking=true、effort=high、max_tokens=null；后续默认预算 65536 |
| multi_disabled | 3 | ok | ok | ok | 系统/用户/助手/用户角色保留，历史思考清空；Chat/Messages disabled 覆盖 max effort；后续默认预算 8192 |
| thinking_max | 3 | ok | ok | ok | max effort、temperature 0.25 -> 1、V4.1 top_p 0.5 -> 0.95；历史思考分隔符保留协议差异；后续默认预算 131072 |
| tool_declaration | 3 | ok | ok | ok | 相同 get_weather schema 与 tool_call 约束；Messages any 实际转 auto；只检查声明，不执行 |
| limit_stop | 3 | ok，保留 stop | ok，忽略 stop | ok，保留 stop_sequences | 显式上限 64；检查解析选项，不执行 stop 匹配 |
| max_tokens_upper_bound | 3 | error | error | ok，截为 393216 | 393217 超默认转换上界；不是上下文检查 |
| model_unregistered | 3 | error | error | error | deepseek-chat 并非内置名，不自动猜测模型版本 |
| alias_v41 | 3 | ok | ok | ok | 显式 alias -> v41；关闭思考时 top_p 0.6 -> 1 |
| alias_v4 | 3 | ok | ok | ok | 同名 alias -> v4；关闭思考时保留 top_p 0.6，选 V4 tokenizer/encoding |
| special_user_literal | 3 | ok | ok | ok | 原文 a<｜User｜> 保留；只有模板 User 为控制 token |
| web_search_default | 2 | — | ok，丢弃工具 | error | 库默认策略不等价 |
| web_search_override | 2 | — | reject -> error | drop -> ok | 显式策略改变接收结果 |
| empty_stop_rejected | 2 | error，空字符串 | — | error，数组有空项 | 分别保留 stop 与 stop[0] 的错误原文 |

family 是对照分组，不是全字段/全 prompt/token ID 相等的断言。允许的正常族差异：thinking_max 中 Chat/Responses reasoning 用单换行，Messages 两个 thinking 块用双换行；tool_declaration 中 Messages any 转 auto；limit_stop 中 Responses 的 stop 被忽略。alias_v41 与 alias_v4 必须跨族比较版本、top_p 和 encoding 选择，不能合并成同一 prompt 预期。

## facts 与 checks 的验收映射

facts 的平面键对应真实对象属性，统一规范化枚举后比较：

| facts 键 | 观测位置/语义 |
|---|---|
| model_version | request.model_version -> v41 / v4 |
| thinking_mode、reasoning_effort、tool_choice | request.conversation 对应属性；effort 用 low/high/xhigh/max/null |
| roles、message_contents | conversation.messages 的 role / content，保持转换后顺序 |
| assistant_reasoning_contents | 仅筛选 role=assistant 的 reasoning_content 数组，保留 null 与空字符串差异 |
| tool_names、tool_parameter_schemas | conversation.tools 的 name / parameters，保持顺序；JSON 结构比较 |
| max_tokens、temperature、top_p | request.inference_options 对应属性；max_tokens=null 是转换尚未解析默认预算 |
| output_constraint_kind | inference_options.output_constraint.kind；无约束为 null；不代表后端执行了约束 |
| stop_sequences、parse_tool_calls、starts_in_tool_calls | request.parsing_options 对应属性 |
| error_status_code、error_contains | ConversionError.status_code；所列子串应在错误正文或解码后的 message 中逐项存在 |
| special_control_counts | 专用于下面的 special-token 检查，不能当普通 request 属性 |

checks 字符串标签的执行合约：

- `convert / assert_facts / assert_conversion_error / render / encode_with_matching_tokenizer`：执行相应阶段并核对 facts；记录完整结果。预期拒绝后停止该条后续 render/encode。
- `family_compare`：比较族中共同列明的 facts；本文件明确允许的差异单列报告，禁止默认比较全量 prompt/token IDs。
- `historical_reasoning_cleared`：助手 reasoning_content 必须为 null；`reasoning_join_protocol_difference`：按各条 assistant_reasoning_contents 精确检查单/双换行，不要求历史思考必然出现在渲染 prompt。
- `tool_declaration_only`：核对工具名/schema、output_constraint.kind=tool_call、parse_tool_calls=true、starts_in_tool_calls=false；不执行工具或约束解码。
- `stop_sequences_preserved / unknown_stop_field_ignored / max_tokens_clamped / alias_resolves_version / web_search_dropped`：按对应 facts 验收；drop 后 tools 为空、output_constraint=null，不以请求被接受解释为已联网搜索。
- `encode_without_tokenizer_raises_runtime_error`：同一条 conversion 成功后，另建**未附加 tokenizer**的匹配 encoding；render 可进行，encode 必须抛 RuntimeError，消息含 `no tokenizer`。随后用已附加匹配 tokenizer 的 encoding 正常编码，不把这个预期错误计为 conversion 错误。
- `resolve_default_thinking_65536 / resolve_default_non_thinking_8192 / resolve_default_max_effort_131072`：先真实编码得 P=len(token_ids)，调用 resolve_max_tokens(P, P+262144)，分别应得 65536 / 8192 / 131072；同时调用 resolve_max_tokens(P, P+7)，应截为 7。
- `resolve_explicit_max_tokens`：真实编码得 P，以转换后 M=inference_options.max_tokens 调 resolve_max_tokens(P, P+M)，必须返回 M。Messages 上界案例的 M 是截断后的 393216。
- `resolve_context_prompt_overflow`：真实编码得 P，调用 resolve_max_tokens(P, P-1)，必须抛 ConversionError，status_code=400，正文包含 `maximum context length`；P 必须大于 0。
- `resolve_context_requested_output_overflow`：显式 M=64 的 limit_stop 族，真实编码得 P，调用 resolve_max_tokens(P, P+M-1)，必须抛同类上下文错误；conversion 仍为 ok。
- `resolve_context_at_limit_returns_one`：无显式 max_tokens 的 text_default 族，调用 resolve_max_tokens(P, P)，固定源码返回 1；如实保留这个边界行为，不能改成自行推断的错误。
- `literal_special_ranges_excluded`：special_user_literal 族中定位完整原文 `a<｜User｜>`；其中 token 拼写的区间不应与任何 rendered.special_ranges 相交。Python 区间为 Unicode code point 下标、半开区间，不能用 Rust UTF-8 byte offset 来切 Python 字符串。
- `literal_control_token_counts`：使用匹配 v41 tokenizer 确认 Tokenizer.encode(`<｜User｜>`) 是单一 ID；匹配 encoding.encode(conversation) 中该 ID 恰 1 次，仅对应模板 User 边界。
- `full_vocabulary_encoding_differs`：Tokenizer.encode(rendered.prompt) 中同一 User ID 恰 2 次，且与 prompt encoding 的 token_ids 不同。原文拼写必须仍存在；不能通过删除、转义原文伪造安全性。

检查阶段的失败/缺测必须单列。匹配 tokenizer 未就绪时，先保留 conversion/render 结果，把 encode、计数和上下文检查标记未执行，不能假报通过或把失败丢出分母。上下文参数是本地 API 边界探针，不宣称测得模型真实服务上下文容量。

## 核心源码依据

- [Python 默认选项、模型 alias 与每协议上界行为](https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/deepseek-recipe-python/python/deepseek_recipe/_native.pyi#L406-L498)；[官方模型映射测试](https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/deepseek-recipe-python/tests/test_bindings.py#L308-L344)。
- [共享 thinking 优先级与 effort 映射](https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/deepseek-recipe/src/protocol/reasoning.rs#L1-L88)；[历史 reasoning 清空/保留](https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/deepseek-recipe/src/protocol/reasoning_content.rs#L14-L91)。
- [版本决定 top_p](https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/deepseek-recipe/src/request/options.rs#L79-L96)；[采样验证、thinking 强制 temperature=1 与 max_tokens 校验/截断](https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/deepseek-recipe/src/protocol/validation.rs#L29-L125)；[官方上界拒绝/截断测试](https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/deepseek-recipe-python/tests/test_bindings.py#L385-L407)。
- [Responses reasoning.content 单换行拼接](https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/deepseek-recipe/src/protocol/openai/responses/request/convert.rs#L492-L527)；[Messages thinking 块双换行拼接](https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/deepseek-recipe/src/protocol/anthropic/messages/request/convert.rs#L690-L696)；[Messages any 转 auto](https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/deepseek-recipe/src/protocol/anthropic/messages/request/convert.rs#L223-L250)。
- [Chat stop 进入 parsing_options](https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/deepseek-recipe/src/protocol/openai/chat_completion/request/convert.rs#L150-L161)；[Responses parsing_options 没有 stop 输入](https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/deepseek-recipe/src/protocol/openai/responses/request/convert.rs#L815-L836)；[Messages stop_sequences 与 clamp 分支](https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/deepseek-recipe/src/protocol/anthropic/messages/request/convert.rs#L93-L118)；[空 stop 验证](https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/deepseek-recipe/src/protocol/validation.rs#L155-L185)。
- [官方 web_search 默认与覆盖测试](https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/deepseek-recipe-python/tests/test_bindings.py#L225-L262)；[Messages 服务端工具判定](https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/deepseek-recipe/src/protocol/anthropic/messages/request/convert.rs#L165-L193)。
- [官方无 tokenizer 与特殊拼写对照测试](https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/deepseek-recipe-python/tests/test_bindings.py#L137-L167)；[Python special_ranges 单位及安全编码界限](https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/deepseek-recipe-python/python/deepseek_recipe/_native.pyi#L313-L375)。
- [Python resolve_max_tokens 合约](https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/deepseek-recipe-python/python/deepseek_recipe/_native.pyi#L521-L534)；[共享实现与等于上限时的 min(remaining).max(1)](https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/deepseek-recipe/src/request/mod.rs#L181-L235)；[官方上下文错误测试](https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/deepseek-recipe-python/tests/test_bindings.py#L377-L382)。
