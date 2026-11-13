# 实验复现与结果索引

[仓库首页](../README.md) · [28篇阅读路线](../00-系列大纲.md)

本表覆盖 exp1–exp29，并单列 exp8b。链接保留原 phase 结构：说明用于准备环境，代码是操作入口，结论用于理解留存结果。**这里没有统一的“全部运行”命令**；数据复核、单元检查和新一轮模型执行有不同的依赖与副作用。

## 选择执行方式

| 方式 | 做什么 | 能支持的结论 |
|---|---|---|
| 源码与机制阅读 | 阅读固定版本笔记、公式或控制流 | 说明该实现或假设；不能替代运行时性能验证 |
| CPU 教学/合成回放 | 运行账本、队列、窗口、fixture 或故障控制 | 验证明确的规则与合成输入；不产生模型 GPU 样本 |
| 真实原生 CPU/API 调用 | recipe 原生转换/流处理、非 CUDA Store API | 验证该库或 API 的实际行为；不自动证明模型推理 |
| 真实 GPU 请求 | 在指定模型、硬件和运行库上执行 | 仅在本组负载与判据内比较；与其他环境分母分开 |
| 失败/未执行留证 | 保存入口拒绝、健康失败、缺失观测 | 说明已观察的失败和未完成项；不能改写为成功 |

## exp1–exp29（含 exp8b）

下表的“结果”链接指向结论文件，不链接私人运行配置、业务原始数据或重复归档。说明和代码如依赖未随公开副本提供的输入，须先准备替代输入或固定版本依赖；结果入口存在并不表示无需这些前置条件。

| ID / 主题 | 对应篇号 | 复现说明与代码入口 | 结果入口 | 执行类别与边界 |
|---|---|---|---|
| exp1 · 并发 | [05](../05-Phase2上-把一辆车开起来/正文.md) | [说明](../phase2/README.md)<br>[exp1_concurrency.sh](../phase2/bench/exp1_concurrency.sh) | [结论](../phase2/results/exp1-结论.md) | **真实 GPU**；单卡并发压测；吞吐平台后的额外请求主要表现为排队。 |
| exp2 · 输入长度 | [06](../06-Phase2下-拨那个参数/正文.md) | [说明](../phase2/README.md)<br>[exp2_prompt_len.sh](../phase2/bench/exp2_prompt_len.sh) | [结论](../phase2/results/exp2-exp3-结论.md) | **真实 GPU**；输入长度与每轮 token 预算对照，不能只用吞吐判断等待体验。 |
| exp3 · 前缀缓存 | [06](../06-Phase2下-拨那个参数/正文.md) | [说明](../phase2/README.md)<br>[exp3_prefix.sh](../phase2/bench/exp3_prefix.sh) | [结论](../phase2/results/exp2-exp3-结论.md) | **真实 GPU**；前缀缓存测量；省下 prefill 不等于消除 decode 或排队。 |
| exp4 · 抢占 | [06](../06-Phase2下-拨那个参数/正文.md) | [说明](../phase2/README.md)<br>[exp4_preempt.sh](../phase2/bench/exp4_preempt.sh) | [结论](../phase2/results/exp4-结论.md) | **真实 GPU**；KV 约束与抢占测量；限定模型和负载。 |
| exp5 · 准入与限流 | [07](../07-Phase3·1-站台限流/正文.md) | [说明](../phase3/README.md)<br>[exp5_admission.sh](../phase3/bench/exp5_admission.sh) | [结论](../phase3/results/exp5-结论.md) | **真实 GPU＋网关**；改变准入与等待位置，不将拒绝或队列控制当作引擎吞吐提升。 |
| exp6 · 优先级 | [08](../08-Phase3·2-谁先出首字/正文.md) | [说明](../phase3/README.md)<br>[exp6_priority.sh](../phase3/bench/exp6_priority.sh) | [结论](../phase3/results/exp6-结论.md) | **真实 GPU＋网关**；混合交互/批处理优先级；入口安排不等于任意引擎内抢占。 |
| exp7 · 缓存路由 | [09](../09-Phase3·3-寄存箱在哪辆车上/正文.md) | [说明](../phase3/README.md)<br>[exp7_routing.sh](../phase3/bench/exp7_routing.sh) | [结论](../phase3/results/exp7-结论.md) | **真实 GPU＋双逻辑引擎**；两份 Qwen3-0.6B 共用一张 GPU；不代表双卡容量或独立故障域。 |
| exp8 · 冷启动（含exp8b graph6变体） | [11](../11-Phase3b·1-出一辆新车要多久/正文.md) | [说明](../phase3b/README.md)<br>[exp8_coldstart.sh](../phase3b/bench/exp8_coldstart.sh) | [结论](../phase3b/results/exp8-结论.md) | **真实启动/GPU 测量**；模型启动阶段与缓存状态分组；不是任意机器的冷启动常数。 |
| exp8b · graph6 启动变体 | [11](../11-Phase3b·1-出一辆新车要多久/正文.md) | [阶段说明](../phase3b/README.md)<br>[exp8b_graph6.sh](../phase3b/bench/exp8b_graph6.sh) | [合并见 exp8 结论](../phase3b/results/exp8-结论.md) | **真实启动/GPU 测量**；exp8 的 CUDA graph 配置对照，结果随 exp8 分组阅读。 |
| exp9 · 扩容信号 | [11](../11-Phase3b·1-出一辆新车要多久/正文.md) | [说明](../phase3b/README.md)<br>[exp9_10.sh](../phase3b/bench/exp9_10.sh) | [结论](../phase3b/results/exp9-结论.md) | **真实 GPU 负载＋信号分析**；比较报警提前量与已有启动时间；未以此证明新增实例可及时接流。 |
| exp10 · 排空与切流 | [11](../11-Phase3b·1-出一辆新车要多久/正文.md) | [说明](../phase3b/README.md)<br>[exp9_10.sh](../phase3b/bench/exp9_10.sh) | [结论](../phase3b/results/exp10-结论.md) | **真实 GPU＋受控排空**；比较期限与在途收尾；续传仅讨论，未执行恢复生成。 |
| exp11 · 语义缓存 | [12](../12-Phase3b·2-不上车的答案/正文.md) | [说明](../phase3b/README.md)<br>[sweep.py](../phase3b/exp11/sweep.py) | [结论](../phase3b/results/exp11-结论.md) | **真实模型/嵌入测量**；虚构问答及同义/最小对立查询；阈值效果不能外推到任意知识域。 |
| exp12 · 离线账本与排队回放 | [13](../13-Phase3b·3-一趟车记在谁头上/正文.md) | [说明](../phase3b/exp12/README.md)<br>[analyze.py](../phase3b/exp12/analyze.py) | [结论](../phase3b/results/exp12-结论.md) | **CPU 离线分析**；回放历史日志；示例点数和估算卡秒不是实付账单，没有新增 GPU 请求。 |
| exp13 · 流式审核 | [14](../14-Phase3b·4-车上说错话/正文.md) | [说明](../phase3b/exp13/README.md)<br>[run_http.py](../phase3b/exp13/run_http.py)、[run_gpu_live.py](../phase3b/exp13/run_gpu_live.py)、[analyze.py](../phase3b/exp13/analyze.py) | [结论](../phase3b/results/exp13-结论.md) | **受控回放＋原生 CPU/GPU 分层**；实际生成/逐句审核与受控延迟回放分开；有限任务不代表广泛审核准确率。 |
| exp14 · GPU语音接力 | [15](../15-Phase4·1-一句话经过几辆车/正文.md) | [说明](../phase4/exp14/README.md)<br>[analyze.py](../phase4/exp14/analyze.py)、[run.py](../phase4/exp14/run.py) | [结论](../phase4/results/exp14-结论.md) | **真实 GPU＋浏览器**；ASR/LLM/TTS 接力；播放消费确认不是扬声器声学证据。 |
| exp15 · 传输与会话 | [16](../16-Phase4·2-这位乘客还没下车/正文.md) | [说明](../phase4/exp15/README.md)<br>[analyze.py](../phase4/exp15/analyze.py)、[run_sessions.py](../phase4/exp15/run_sessions.py) | [结论](../phase4/results/exp15-结论.md) | **真实媒体传输＋合成会话控制**；回放已有音频，无新增模型推理结论；逻辑 owner 不代表跨机迁移。 |
| exp16 · 插话与取消 | [17](../17-Phase4·3-乘客插话/正文.md) | [说明](../phase4/exp16/README.md)<br>[analyze.py](../phase4/exp16/analyze.py)、[run_probes.py](../phase4/exp16/run_probes.py) | [结论](../phase4/results/exp16-结论.md) | **真实 GPU＋浏览器取消**；核对生成、发送、渲染与历史；CPU 侧停止记录不证明 CUDA kernel 已停止。 |
| exp17 · 增量输入调度 | [18](../18-Phase4·4-边听边开/正文.md) | [说明](../phase4/exp17/README.md)<br>[analyze.py](../phase4/exp17/analyze.py)、[launch.sh](../phase4/exp17/launch.sh) | [结论](../phase4/results/exp17-结论.md) | **真实 GPU＋独立合成队列**；前缀识别/回答草稿与帧队列教学分列，不合并为同一模型样本。 |
| exp18 · 体验与分钟账本 | [19](../19-Phase4·5-一分钟怎么算/正文.md) | [说明](../phase4/exp18/README.md)<br>[analyze.py](../phase4/exp18/analyze.py)、[launch.sh](../phase4/exp18/launch.sh) | [结论](../phase4/results/exp18-结论.md) | **CPU 离线账本＋独立 GPU 补测**；重算历史记录，另做常驻/中断观测；资源估算不是货币账单。 |
| exp19 · 请求转换与编码合约 | [20](../20-Phase5·1-先验车票/正文.md) | [说明](../phase5/exp19/README.md)<br>[analyze.py](../phase5/exp19/analyze.py)、[run.py](../phase5/exp19/run.py) | [结论](../phase5/results/exp19-结论.md) | **真实 recipe 原生 CPU**；请求转换、编码与上下文检查；未运行模型或 DeepInfer。 |
| exp20 · 流式分段与终态 | [21](../21-Phase5·2-广播分几段/正文.md) | [说明](../phase5/exp20/README.md)<br>[analyze.py](../phase5/exp20/analyze.py)、[execute.py](../phase5/exp20/execute.py) | [结论](../phase5/results/exp20-结论.md) | **真实 recipe 原生 CPU＋合成后端**；流处理器与本地 SSE 字节回放；无真实模型、HTTP 网络或工具执行结论。 |
| exp21 · 结构化输出声明与验收 | [22](../22-Phase5·3-按格式报站/正文.md) | [说明](../phase5/exp21/README.md)<br>[gpu_run.py](../phase5/exp21/gpu_run.py) | [结论](../phase5/results/exp21-结论.md) | **独立 recipe CPU / Qwen GPU**；两条实验线分开；不是 recipe → Qwen 或 DeepInfer 端到端集成。 |
| exp22 · 调度循环与确定性 | [23](../23-Phase5·4-班次表藏在哪里/正文.md) | [说明](../phase5/exp22/README.md)<br>[analyze.py](../phase5/exp22/analyze.py)、[gpu_run.py](../phase5/exp22/gpu_run.py) | [结论](../phase5/results/exp22-结论.md) | **真实 HTTP/GPU＋源码阅读**；比较实际输出 token；DeepInfer 仅源码阅读，不报告其运行性能。 |
| exp23 · 草稿与窗口教学回放 | [24](../24-Phase5·5-少跑几圈/正文.md) | [说明](../phase5/exp23/README.md)<br>[run.py](../phase5/exp23/run.py) | [结论](../phase5/results/exp23-结论.md) | **CPU 教学回放＋源码探针**；草稿/窗口机制教学；不是 DSpark 推理、attention 实测或模型速度/质量结果。 |
| exp24 · Mooncake Store与KV身份 | [25](../25-Phase5·6-行李不跟车走/正文.md) | [说明](../phase5/exp24/README.md)<br>[freeze.py](../phase5/exp24/freeze.py)、[run_identity.py](../phase5/exp24/run_identity.py) | [结论](../phase5/results/exp24-结论.md) | **真实非 CUDA Store API＋CPU 身份合约**；单机跨进程已知字节读写；未执行模型 KV 导入、RDMA、GPU 或真实 P/D。 |
| exp25 · 纵向网关 | [26](../26-Phase5·7-把站台接起来/正文.md) | [说明](../phase5/exp25/README.md)<br>[analyze.py](../phase5/exp25/analyze.py)、[run.py](../phase5/exp25/run.py) | [结论](../phase5/results/exp25-结论.md) | **真实 GPU＋实验网关**；单卡、合成租户、精确响应缓存；不是 KV 缓存或生产 HA。 |
| exp26 · 取消排空与安全重试 | [27](../27-Phase5·8-半路抛锚/正文.md) | [说明](../phase5/exp26/README.md)<br>[analyze.py](../phase5/exp26/analyze.py)、[run.py](../phase5/exp26/run.py) | [结论](../phase5/results/exp26-结论.md) | **受控故障＋真实 GPU 分层**；取消/排空/安全重试；CPU tracker 收尾不证明 CUDA 停止，无跨重启事务保证。 |
| exp27 · 联合验收与贡献候选 | [28](../28-Phase5·9-交班时拿什么说话/正文.md) | [说明](../phase5/exp27/README.md)<br>[analyze.py](../phase5/exp27/analyze.py)、[run.py](../phase5/exp27/run.py) | [结论](../phase5/results/exp27-结论.md) | **真实 GPU 联合验收＋独立 CPU 贡献验证**；体验/质量/SLO/usage 分母分列；贡献候选不表示已获上游接受。 |
| exp28 · Kaggle图片接口失败记录 | 独立补验 | [说明](../phase5/exp28/README.md)<br>[run.py](../phase5/exp28/run.py) | [结论](../phase5/results/exp28-补充结论.md) | **入口失败观测＋CPU 记录器检查**；健康返回 404 后停止；本轮生成提交 0、新图片 0、新增 GPU 样本 0，诊断未获执行证据。 |
| exp29 · Kaggle文本接口补验 | 独立补验；补充26–28 | [说明](../phase5/exp29/README.md)<br>[bootstrap.py](../phase5/exp29/bootstrap.py)、[experiment.py](../phase5/exp29/experiment.py)、[package_notebook.py](../phase5/exp29/package_notebook.py) | [结论](../phase5/results/exp29-补充结论.md) | **独立真实 GPU / Transformers**；Qwen3-4B FP16 单卡；5 例中 3 次生成/41 输出 token；非旧网关重跑、故障注入或质量评测。 |

## 结果版本与关键目标

有些分析脚本会读取留存的源码快照或旧版本原始记录。代码引用的相对路径保持不变；音频字节不随仓库分发，vendor文件需按固定清单恢复。仅有最终摘要不足以完整复算，缺失输入需按下文的收录限制准备。下面列出正文使用的关键版本，历史失败/预检/修订记录不能混入最终样本。

| 实验 | 正式结果目标 | 阅读方式 |
|---|---|---|
| exp14 | [结果摘要](../phase4/results/exp14-summary.json) | 由历史语音/组件/浏览器记录分析；测量与哈希保留，音频需自备授权音色重建，第三方源码按清单恢复。 |
| exp20 | [结果摘要](../phase5/results/exp20/formal-v1/summary.json) | 原生 CPU＋合成后端的正式摘要。 |
| exp21 | [结果摘要](../phase5/results/exp21/gpu-summary.json) | GPU汇总；CPU结果独立，不合并为端到端样本。 |
| exp22 | [结果摘要](../phase5/results/exp22/formal-v1/summary.json) | 正式GPU请求；预检单列，后端审计输入按说明准备。 |
| exp23 | [结果摘要](../phase5/results/exp23/formal-v2/summary.json) | 教学回放最终版本；源码探针与之分列。 |
| exp24 | [结果摘要](../phase5/results/exp24/formal-v3/summary.json) | Store API最终版本；v1/v2历史结果保留但不并入v3分母。 |
| exp25 | [结果摘要](../phase5/results/exp25/formal-v1/summary.json) | 正式网关结果；分析修订不新增GPU样本。 |
| exp26 | [结果摘要](../phase5/results/exp26/formal-v1/summary.json) | 原执行摘要；原生收尾分析修订另列。 |
| exp26 | [结果摘要](../phase5/results/exp26/formal-v1/analysis-revision2/summary.json) | 修订 CPU 侧收尾分析，不新增GPU请求。 |
| exp27 | [结果摘要](../phase5/results/exp27/formal-v2/summary.json) | 最终联合验收版本；formal-v1失败记录单列。 |
| exp29 | [结果摘要](../phase5/results/exp29/exp29-kaggle-20261110-a74160a0/summary.json) | 独立4B文本接口逐请求汇总。 |

## 依赖与阶段间复用

| 阶段 | 需要准备的依赖 | 结构依赖 |
|---|---|---|
| Phase 0 / 1 | Python观测分析按需准备；概念/源码阅读无需GPU | 原始业务CSV不提供公共下载，需使用自有授权数据或合成输入；Phase1无独立实验入口 |
| Phase 2 | CUDA GPU、Qwen3-1.7B、vLLM 0.8.5；绘图/监控按阶段说明准备 | `bench/`、`daryu/`配置示例、`img/`及`results/`保留位置；机器配置须自行适配 |
| Phase 3 | Phase2运行时与网关依赖；exp7使用两份Qwen3-0.6B | [gateway/gw.py](../phase3/gateway/gw.py)与阶段bench共用；不把双逻辑实例当双卡 |
| Phase 3b | Phase3网关；exp11嵌入模型；exp13生成/审核模型；exp12离线标准库，绘图另需依赖 | 保留前序实验日志格式和引用；嵌入服务需自行部署或配置 |
| Phase 4 | Python3.12、Torch/CUDA、ASR/LLM/TTS权重；浏览器/Node媒体工具；exp15有独立媒体依赖 | exp16/17复用exp14模块和音频输入，exp15回放音频；仓库不含音频字节，须自备授权音色重建。exp18离线复核历史测量 |
| Phase 5 | recipe0.2.0原生CPU包；pytest/jsonschema；GPU组vLLM/Qwen；exp24非CUDA Mooncake；exp29独立Transformers运行时 | 固定源码、tokenizer、模型身份及运行锁需按说明恢复；原虚拟环境和第三方整包不视为可移植安装方式 |

[Phase4说明](../phase4/README.md)和[Phase5说明](../phase5/README.md)汇总了各组环境。依赖锁、模型文件 hash 与源码快照用于识别运行身份；源码 commit 不能自动代表 wheel 的构建身份。特定机器验证通过不等于其他平台支持。

## 收录限制：音频与第三方文件

正式112张配图、58份HTML源图及绘图脚本保留；phase实验代码和结果经去敏后提供。测量文件描述的是历史执行，不代表本次重新执行或完整附件均已随仓库分发。

445个合成音频文件（435 WAV＋10 PCM）虽有provenance，但macOS/Kokoro音色输出的分发条款尚未单独核对，**此次不随CC BY仓库分发音频字节**。保留所有输入文本、测量、文件哈希、来源记录和生成脚本。exp14–17及其他依赖音频文件的步骤，需要读者自备授权音色重建相应输入；历史音频的直接播放、解码和按原字节重算，不能仅靠此仓库完成。exp18中仅依赖已公开测量的离线分析，与需要重建音频或重新运行模型的步骤分开。

历史文件哈希用于标识当时输入或输出，不是所有重建运行必须达到的哈希。替换音色、模型或环境可能改变波形、时长和实验结果；重建后应记录新的哈希和参数，并以新的运行目录留证，不覆盖历史测量或声称逐字节复现。

exp29的10个`.bin`文件是文本HTTP请求/响应记录，不是音频，继续保留。音频未收录范围包括`phase4/results/exp15/`中的10个PCM文件。

vendor源码、词表与wheel暂不打包，避免将第三方内容混同为仓库原创许可范围。使用[恢复脚本](../tools/restore_upstream.py)与[固定来源/SHA清单](../tools/upstream-sources.json)恢复实验所需文件：默认dry-run，只有显式传入`--download`才下载，按固定SHA校验并恢复原相对路径。恢复第三方文件不改变原有许可。需要这些源码或tokenizer的测试，在恢复前不能视为可直接执行。

`deepseek-recipe==0.2.0`的原wheel构建commit未知，仍保留这一边界。清单中源码commit和发行文件SHA分别标识各自对象，不能把下载文件校验通过写成已证明wheel由该源码commit构建。

## 三个容易误读的实验

### exp12：账本是离线回放

[说明](../phase3b/exp12/README.md)中的分析读取历史记录，核对 token、租户分配和队列位置。token 数据来自旧实验，示例点数与资源分摊模型单列。回放、审计和绘图都不构成新的GPU请求；点数不是供应商账单，队列的右删失样本也不能当作已完成时延。

### exp28：没有新的生成

[失败结论](../phase5/results/exp28-补充结论.md)记录健康检查返回404并停止。本轮生成提交为0，没有新图片，没有新增GPU样本；本地记录器测试属于CPU合成检查。会话显示存在或显存有占用，不能证明接口可生成；未观察到诊断单元执行结果，故障根因保持未确认。后续重试必须产生独立运行记录，不能覆盖这次失败。

### exp29：独立4B文本接口

[补验结论](../phase5/results/exp29-补充结论.md)采用Qwen3-4B FP16、Transformers4.51.3；平台分配两张T4，但模型只使用一张。5个串行HTTP用例中两条在入口拒绝，三条实际生成，共41个原生输出token；CPU SSE检查不增加GPU样本。

这轮是自建环回服务的请求/响应、SSE终态与原生usage对账。未执行DeepInfer/recipe，没有把原网关搬过去重跑，也没有故障注入、质量评测或生产并发结论。普通响应与流式响应的首内容定义和执行顺序不同，不能将一次时延差写成模型提速比例。

## 开始前与结束后

1. 先阅读对应说明，确认是读取现有数据、运行CPU检查，还是启动模型/服务。文中历史状态不能代替当前环境检查。
2. 只在自己控制的环境准备依赖和模型；使用新的输出目录，自行适配设备和配置。这里不提供真实连接或认证材料。
3. 保留模型/运行库身份、输入、原始响应、失败项和关联键。新执行与历史留存结果分开，不用旧摘要冒充新结果。
4. 对需要服务或GPU的实验，按说明收拢本次拥有的资源；留存的进程状态不构成当前清理指令。

CPU测试通过、结果文件存在、HTTP200或流式结束，各自只能证明对应环节。质量、SLO、取消传播、计量完整性与资源回收需要各自证据，未知项保持未知。
