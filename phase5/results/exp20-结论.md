# exp20：分块可以变，完成依据不能含糊

2026-10-23。正式结果为[formal-v1](exp20/formal-v1/summary.json)。真实recipe 0.2.0原生库，CPU；固定V4.1 tokenizer与合成后端输出。没有模型推理或实际工具执行；流实验未启动模型API或HTTP网关，未验证后端取消传播。

## 分母与检查

19个fixture定义：11组主要语义输出、2组usage和6组生命周期/错误。按所声明协议、Text/Tokens与切分展开222条配置流，222通过、失败0、未知0。2004项声明检查存在重复，不代表独立能力数；666次本地字节重放复用这些事件，不是额外模型调用。

结束来源按实际记录分为：后端Finish 159、解析器停止18、未证实EOF 18、客户端close 21、流错误6。另有完成后继续push等预期API错误，它们不会抹去已经确认的结束来源。全部留在分母，不将“222通过”解释为222条自然成功输出。

记录器/字节层48项回归通过；固定源码完整`test_bindings.py`本轮48通过、0失败、0跳过，证据见[JUnit XML](exp20/upstream-bindings.xml)。上游图片测试会启动本地临时HTTP服务，随测试退出；这不是整个上游仓库的测试结果。

## 本轮实际观察

1. **切分对照成立，有明确前提。** 整块、逐Unicode字符/逐ID、混合大小的选定内容、reasoning、工具名/参数和终态符合冻结预期。Tokens先编码完整原文，再切同一ID序列；不预设普通ID拼出的同名特殊标记也等价。跨切分比较不包含usage、随机工具ID和时间。
2. **EOF收尾不证明后端自然结束。** 未收到后端Finish，随后调用processor.finish()，三协议仍映射为stop/completed/end_turn；native finished为真。账本另记unconfirmed_eof。本地close只保留部分响应，没有新增成功终态。两条路径都没有验证真实客户端断线传播。
3. **stop可先结束本地解析。** 命中停止串后不再提交剩余输入，记录未提交单位；whole模式可能已交来整段尾部。解析结束不是后端停止计算，也不保证不同切分具有相同计量范围。
4. **工具终态不保证参数完整。** 完整单/双工具调用还原名称、参数和顺序；截断参数时Chat/Responses保留`{"city": "杭州`，Messages最终input回退为`{}`。三者原始参数delta仍为同一段不完整JSON。终态分别为tool_calls/completed/tool_use；没有实际执行工具。
5. **usage的0/缺项必须附来源。** 同一thinking→answer原文，Chat Text默认输出总数0、reasoning缺项；Text附tokenizer总数仍0、reasoning为4；Tokens附tokenizer总数10、reasoning为4。Responses未计量reasoning时为默认0，Messages无同样分项。合成PromptUsage总13/缓存3和Text显式7仅验证传递，不是模型实测成本。
6. **SSE framing分协议。** Chat的DONE为传输层追加data；Responses/Messages无额外DONE。原生事件本地包装后，整体、逐字节、混合切分均读回一致；去掉末尾空行时最后未终止事件不派发。辅助器只实现SSE行/字段子集，严格UTF-8，不等同完整EventSource或网络验证。

完整响应来自同一原生事件流的accumulate，与流式结果不是两个独立oracle。Responses终态可带最终快照，因此保留全部中间事件与工具参数增量；不能仅靠最终对象掩盖中间丢失或参数回退。

## 版本、来源和复现

源码阅读commit `935817c66f5d6e64838f419692545f06787e485f`；执行官方0.2.0 wheel，构建commit未知。来源、SHA256、Git blob与边界见[源码笔记](../exp20/源码笔记.md)、[固定源码元数据（第三方依赖需恢复，未随仓库收录）](../../docs/THIRD_PARTY.md)，原wheel身份见[exp19环境](exp19/environment.json)。

命令见[README](../exp20/README.md)，逐行记录保留请求、原始后端输出/输入单位、切分、事件、完整或部分响应、结束来源、后端Finish、异常阶段、usage来源。每行绑定完整输入/预期摘要；缺行、过期合约或必需检查缺失为unknown，记录器异常不能当作预期原生错误。

CSV在[能力矩阵](exp20/capability-matrix.csv)，主要证据在[摘要](exp20-summary.json)。pilot与正式运行不合并。源码笔记的候选不变量比本轮集合更广；未执行的特殊token身份反例、token截断、重叠stop、JSON外围空格、全部continuation初态不在本轮通过范围。约束执行留给exp21；网络与取消传播留给后续集成。
