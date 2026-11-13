# exp19：三张车票是不是同一趟车

2026-10-23。结论：请求转换需要同时核对对话、生成设置、解析设置、prompt、特殊区间与token IDs；仅比较字段名或prompt不足以证明等价。正式记录为[formal-v2](exp19/formal-v2/summary.json)，[P5·1正文](../../20-Phase5·1-先验车票/正文.md)据此成稿。

## 运行与分母

| 项目 | 本轮证据 |
|---|---|
| 环境 | macOS 26.6.2 ARM64，Python 3.12.10，CPU |
| 实际执行 | 官方deepseek-recipe 0.2.0 wheel；本地镜像安装，wheel哈希与官方PyPI一致 |
| 阅读源码 | `935817c66f5d6e64838f419692545f06787e485f`；所选源码逐文件核对Git blob与SHA256 |
| tokenizer | 同commit的V4/V4.1文件，加载前核对固定SHA256 |
| 转换输入 | 36条：Chat 11、Responses 12、Messages 13；输入数与组成不同 |
| 结果 | 接受27、按预期拒绝9；36条均完成声明检查 |
| 声明检查 | 211项通过，失败0、未知0；存在重复检查，不是独立能力数或质量分数 |
| 运行器回归 | 16项通过，涵盖分母、旧合约误用、观测异常、tokenizer版本等 |
| 上游测试 | 固定源码的完整`test_bindings.py`：48通过、0失败、0跳过；非上游全仓测试 |
| 推理／调用 | 模型推理0次、实际工具0次；无在线API服务 |

wheel SHA256：`624bb4d0fb3ed541b9e34d2ef96ff66057026ded7d6708b0b9088cc6d6723999`。wheel接口声明与固定源码逐字节一致，但native二进制构建commit未知，未把发行包等同于从阅读commit构建。详细身份见[environment.json](exp19/environment.json)、[源码元数据（第三方依赖需恢复，未随仓库收录）](../../docs/THIRD_PARTY.md)、[tokenizer来源（第三方依赖需恢复，未随仓库收录）](../../docs/THIRD_PARTY.md)。

## 主要观察

1. **相同prompt/token IDs仍可能有不同停止规则。** `limit_stop`族三条输入的prompt与token IDs相同，输入14 token、输出额度64；Chat/消息协议保留两条停止串，Responses忽略未知顶层`stop`。这些是本库转换规则，未验证外部API服务。
2. **接受可能伴随改写。** 请求输出393217时，Chat/Responses拒绝；Messages截到393216后接受。web_search默认在Responses丢弃、Messages拒绝；显式选项可覆盖。工具声明的转换接受不代表工具执行。
3. **模型别名决定版本规则。** 默认未注册`deepseek-chat`，三协议均拒绝。显式注册为V4.1或V4后接受；本轮关闭thinking、请求`top_p=0.6`的输入分别转为1与约0.6。别名不使其他模型兼容DeepSeek格式。
4. **特殊区间会改变编码。** 用户原文`a<｜User｜>`保留：使用匹配的prompt encoding时User控制ID出现1次，只对应模板；直接对完整prompt字符串分词时出现2次。Python区间为Unicode字符下标，Rust字段为UTF-8字节偏移。本例不构成通用提示安全证明。
5. **转换上界与上下文余量分阶段检查。** 对输入14、显式输出64，`resolve_max_tokens(14,78)`返回64，传入77则拒绝。未显式填写额度时，在人为充足的上下文参数下，非thinking/普通thinking/max effort默认分别8192/65536/131072，仅余7时都降到7。这不是模型容量测量。
6. **保留边界反例。** 未显式额度且输入长度恰等于传入上下文上限时，本版helper返回1；不能据此证明后端满上下文仍可生成。调用方仍须核对真实后端限制。

八个三协议共同请求族在此冻结集合中得到相同prompt及token IDs；这不是三协议整体等价的证明。全部逐字段结果在[CSV矩阵](exp19/capability-matrix.csv)和[逐条记录](exp19/formal-v2/records.json)。

## 证据和异常处理

每条结果保留请求/选项、完整case合约SHA256、转换结果/错误、生成及解析设置、prompt/特殊区间、token IDs、预算检查。未知和失败均留在声明分母，预期拒绝单列；观测失败不能重写为转换拒绝。

正式运行保存代码/输入快照并核对哈希。缺失或过期合约的旧记录在聚合时为unknown，重复ID/检查名直接报错。tokenizer加载前核对版本内容，不能仅凭目录名接受。

首轮pilot曾因Python enum无法直接JSON序列化中止，第二轮pilot缺tokenizer；保留原记录并从最终统计排除。`formal-v1`已通过，独立审查后补齐异常路径和旧合约校验，再跑`formal-v2`，结论未变。运行之间不累加样本。GitHub完整源码归档下载未完成，改为固定raw文件并逐个核对Git tree；不冒充完整clone。

运行及上游测试命令见[README](../exp19/README.md)，上游证据见[JUnit XML](exp19/upstream-bindings.xml)。本轮未运行DeepInfer，未做模型推理、输出约束执行、工具执行、SSE传输、服务性能或回答质量实验；输出流解析留给exp20。
