# exp16 · 插话与取消：实验结论

2026-10-22。DARYU RTX 4060 Laptop 8188 MiB；实际 CUDA LLM/TTS，浏览器通过 SSH/TCP 隧道访问 WS。全部结论来自最终矩阵，不混入 pilot、热身或本地假模型测试。

## 结论

1. 只取消上游和服务端发送，已经进入客户端的旧音频仍继续消费约1.9秒。本轮服务端最多预发2秒未确认音频；这个量级依赖当前缓冲策略，不是通用协议常数。
2. 清本地队列并使旧generation失效，九次完整取消均停止旧音频进一步消费，并拒绝九条受控迟到旧帧。触发→最后旧音频消费为0或2.6667ms，源于固定触发点与128帧渲染块的位置；不是声学停止延迟，也不等于取消链路全部完成。
3. GPU收尾独立记账。LLM/TTS边界探针各3次，真实调用返回、工作线程join与队列清理都有事件。TTS仍需等当前调用返回，再丢弃波形，没有实现CUDA kernel抢占。
4. 历史只保留完整渲染的TTS段，部分段保守舍弃；确实将裁剪后的messages用于下一轮LLM。没有字词对齐，也不证明用户实际听见/理解，下一轮语义质量未评分。
5. 每条浏览器运行后接一轮新回答，18/18生成、发送与实际渲染样本数相等。源码哈希、原始WAV、计数和时序检查通过。

## 配置与分母

- Qwen3-0.6B BF16，Transformers4.51.3；Kokoro-82M-v1.1-zh FP32 / zf_001，kokoro0.9.4；Torch2.6.0+cu124、CUDA12.4、cuDNN9.1。两模型均CUDA，无CPU静默回退。
- 固定识别后的文字提示；不运行ASR/VAD/麦克风/AEC，不测用户起音或检测准确性。声学停止延迟为null。
- 首轮贪心最多256新token，下一轮64，输入上限1024。TTS最多12字符一段，24kHz单声道PCM16LE，20ms包。播放器不额外设置起播缓冲门槛，首帧入队后消费；服务端未确认样本上限48000（2s）。
- Chrome155.0.8059.85，headless但真实AudioContext/AudioWorklet，实际24000Hz、128帧quantum。工作线程/缓冲与物理设备输出分开。
- 浏览器正式18条：2策略×200/1000/4000ms播放位置×3次；每条包含旧轮及下一轮，36个实际generation任务。失败0/18，全部原始记录保留。
- 另外6个实际GPU取消任务：LLM首段文字可用后、TTS调用开始后目标50ms，各3次。探针起点不同，不作模型速度比较。
- 固定提示重复运行，不能看作18种内容；未测公网弱网、WebRTC、并发、多GPU、自然插话或语音质量。

## 播放结果

同AudioWorklet时钟：触发样本结束帧→最后一个旧音频消费样本结束帧。包含消费的零样本，不是最后非静音点。

| 触发已播位置 | 只停服务端p50 / 范围ms | 完整取消p50 / 范围ms | 每格n |
|---|---|---|---:|
| 200ms | 1920 / 1920–1940 | 2.6667 / 全部相同 | 3 |
| 1000ms | 1940 / 1920–1980 | 2.6667 / 全部相同 | 3 |
| 4000ms | 1890 / 1890–1910 | 0 / 全部相同 | 3 |

- 24kHz下128帧=5.3333ms。200/1000ms触发点在块中间，本轮均又消费64样本=2.6667ms；4000ms点正好在块尾，下一块未再消费旧音频。0不是物理听觉瞬时停止，不能包装成SLO。
- 主线程触发通知→flush确认通知另有performance时钟记录，不与server monotonic或音频时钟直接相减。
- full在清空后旧generation计数不再增加；每条受控旧帧480样本，cancel后延迟30ms注入，共9条由generation_fence拒绝。探针内容和正常帧走同一worklet入队入口；server_only显式忽略此探针，避免污染尾巴。
- 原始普通音频发送完成事件均早于停止信号，停止后普通旧音频发送事件0条。每代已发送PCM数量、客户端接收数量与保存WAV及SHA-256一致。

## 计算收尾

起点为服务端stop_signal_set，终点为LLM/TTS线程均join完成，server monotonic本地差值。

| 探针边界 | p50 ms | 最小–最大ms | n |
|---|---:|---:|---:|
| LLM文字可用后 | 22.5856 | 7.2720–145.0365 | 3 |
| TTS调用开始后目标50ms | 59.4249 | 49.6096–65.9261 | 3 |

- LLM三次finish_reason=cancelled，记录StoppingCriteria的每步检查与generate返回。检查发生在token发布之后，检查点token数量差不能直接认作停止后新计算的token数量。
- TTS三次各计算并丢弃92400样本（3.85秒音频），不入发送队列。3.85秒是波形播放长度，不是CUDA执行时间；调用开始50ms是调度边界，不保证GPU kernel已启动。
- 浏览器正式18条停止后join范围9.3473–230.9264ms；其中12条LLM取消，6条在cancel前已自然结束，不能都声称发生LLM抢占。
- 所有旧线程join且客户端播放终态到达之后才启动generation2；实际事件顺序逐条验证。

## 历史与下一轮

- full的200/1000ms共6条尚未完整播完第一TTS段，助手历史为空。
- full的4000ms共3条：第一段0–92400样本（3.85s）全部播完，最终played=96000（4s）；仅保留第一段，部分播放的第二段整体舍弃。
- 实际保留文字为“出门前先查好路线，带上相”。12字符上限会拆开“相机”，段完整不等于完整词句；这是机制实验的明确质量局限，需要更合适的分句或词级对齐。
- 状态中的text为应用已从LLM流里取出的文字前缀，不保证穷尽模型线程已生成但仍在streamer队列中的全部文字。
- generation2的prompt_messages逐条核对：助手内容恰好等于保留段；为空时没有助手项。新轮生成/发送/播放均为65400样本（2.725s），18条完整。此处只验证实际输入接续与播放，不评价回答质量。

## 资源、验证与复现

- 4项Python并发/历史测试，12项Node worklet机制测试通过。假模型测试不计入GPU样本。
- 568次整卡资源采样，观测显存最高2347MiB；含模型常驻和其他开销，0.5s采样不是精确瞬时/进程峰值或GPU活跃时长。
- 已停止专用实验服务并验证进程退出、远端18149关闭；专用SSH隧道关闭，本地18149关闭。原gpu-router保持active，GPU回到342MiB。模型/venv/代码/数据保留；没有修改原服务。
- `exp16-summary.json`由[analyze.py](../exp16/analyze.py)从原始文件重算并检查；运行方法见[README](../exp16/README.md)，设计见[设计](../exp16/设计.md)。
- 最终浏览器：`exp16/browser-formal-v1/records.json`；GPU探针：`exp16/probes-formal-v1/`；远端原始事件/WAV/环境/资源：`exp16/server/final-v1/`；当时源码：`exp16/provenance/source-final-v1/`。pilot-v1、runner-v1、smoke、warmup独立保留。
- 图：[exp16.png](../img/exp16.png)。官方依据：[LiveKit回合/打断](https://docs.livekit.io/agents/logic/turns/)、[Web Audio currentFrame](https://www.w3.org/TR/webaudio/#dom-audioworkletglobalscope-currentframe)、[Transformers4.51.3停止条件](https://huggingface.co/docs/transformers/v4.51.3/en/internal/generation_utils#transformers.StoppingCriteria)，查询2026-10-22。
