# exp21：格式受约束，答案仍要核对

2026-10-26。CPU真实recipe0.2.0转换与DARYU Qwen3-0.6B原生模板GPU对照分开运行，未直接集成recipe→Qwen，未运行DeepInfer或执行工具。

## CPU与源码

126/126配置符合核对后的冻结预期：90接受、36预期拒绝，未知/意外异常0。另有18条真实parser合成探针；它们是观测后冻结的characterization，不能写成独立模型预测。最初两条Responses预期已据固定源码校正，历史保留，未从分母删除。

非法regex `[`被转换接受；strict schema不合格文本可被parser转发；Messages格式字段有忽略样例。声明/转换不等于编译/采样/实例验证。tool_call*与json空sentinel不直接透传DeepInfer，候选json/regex映射未执行。详情见[CPU摘要](exp21/cpu/结果摘要.md)、[矩阵](exp21/cpu/formal-v1/mapping-matrix.csv)、[源码笔记](../exp21/源码笔记.md)。

recipe源码固定`935817c66f5d6e64838f419692545f06787e485f`，DeepInfer源码固定`9bd9cf243fc53ef9afbf8f04d391d989117d6ab9`；native二进制构建commit未知。来源字节/本地blob可校验，但本轮部分Git tree API因403未独立核对，不把本地blob摘要写成已通过远端tree认证。

## GPU正式对照

RTX4060 Laptop 8188MiB；Qwen3-0.6B，vLLM0.8.5、torch2.6.0+cu124、xgrammar0.1.18。模型/权重/tokenizer/native template SHA256及已安装源码身份在[后端笔记](../exp21/backend-source-notes.md)、[身份JSON](../exp21/backend-source-notes.json)。服务上下文2048，输出上限192，关闭thinking，temperature0.6/top_p0.9、seed17/29；单并发。20合成任务×2seed×3组=120，不是120个独立任务。

三组任务及schema文字完全相同，仅改变API约束字段；schema只给结构、enum和范围，不含业务答案。实际结果：

| 组别 | 计划 | 接收 | JSON合法 | schema合格 | 正确且完整 |
|---|---:|---:|---:|---:|---:|
| prompt_only | 40 | 40 | 7 | 7 | 7 |
| json_object | 40 | 40 | 40 | 30 | 17 |
| json_schema | 40 | 30 | 30 | 30 | 17 |

10条拒绝均为原schema中array minItems/maxItems在no-fallback下不支持，HTTP400；不删限制、不隐藏拒绝。所有110个接受响应均Stop；无运输异常、缺行或旧合约行。拒绝后的JSON/schema/业务测量为null，仍保留40计划分母。

提示组33条解析失败全部以代码围栏开头。严格解析整个输出，不剥围栏、不提取子串；7/40是完整输出合约指标，不表示33条围栏内业务内容均错误。

共同支持的30配置中，JSON/schema约束组各30条结构合格，正确且完整均17；不能宣称schema提高了答案正确率。schema组13条结构合格但业务错误；代表记录intent-1/seed17把“不着急”输出为urgent=true。JSON、类型、字段合法仍不足以证明业务值正确。

冻结题面calc-4写“打75折”，oracle解释为按原价75%支付，有歧义。保留全部原记录；共同支持子集剔除该题后每组28条，prompt结构/可交付7/7，两约束组均28/17，不以该题支撑核心反例。结果受这组有限任务、prompt、原生模板、采样参数和校验口径限制，不外推一般正确率或生产SLO。

## 执行证据

控制请求只在API schema给出CONSTRAINED21枚举，prompt要求FREE，实际生成CONSTRAINED21；prompt_only生成FREE、json_object生成{}，非法schema type→400。另有整数范围接受与数组限制400两次预检。共6条，独立于正式120分母。

[API入口日志对账](exp21/api-reconciliation.json)120/120 body SHA256与HTTP状态相符。[安装源码调用链](../exp21/backend-source-notes.md)核对response_format→GuidedDecodingParams→xgrammar编译/logits processor→mask→sampler。入口证据不等于每token mask执行trace；本轮将源码/配置、控制生成与逐请求入口分别保留。

CLI后缀启动曾被拒，正确用法是服务器xgrammar，请求级xgrammar:no-fallback。no-fallback只禁止更换backend，不修复编译器所有语义缺陷；额外native CPU matcher探针仅附录，不冒充GPU生成。

当前源码/评估器46项最终测试见[JUnit](exp21/local-tests-final.xml)，[36项初轮证据](exp21/local-tests.xml)保留。新增记录器回归修复未触发本轮原始120记录，不改执行时快照；独立重评及入口对账一致。原始结果、汇总、CSV及复现入口见[README](../exp21/README.md)、[GPU摘要](exp21/gpu-summary.json)、[完整记录](exp21/gpu-formal-v1/records.json)。

## 清理

仅停止本实验PID119959和本地SSH隧道。回读PID不存在、8021关闭；GPU667MiB占用、7291MiB空闲、利用率0%。未停止ComfyUI或其他服务。见[清理JSON](exp21/cleanup.json)。
