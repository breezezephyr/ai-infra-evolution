# exp17 · 增量输入的调度

2026-10-23。真实CUDA前缀ASR+LLM草稿，与合成视频队列分开。设计见[设计](设计.md)，结果见[结论](../results/exp17-结论.md)。本轮不运行麦克风、VAD、TTS、播放、视觉模型或外部工具。

## 文件

- `revision.py`：规范化转写revision、草稿隔离、final提交、一个待处理ASR快照槽。
- `run_gpu.py`：冻结16kHz音频20ms节奏供给、800ms前缀重识别、实际LLM线程、原始事件/环境/资源；复用exp14的CUDA模型适配器。
- `launch.sh`：仅给本次DARYU进程设置已有NVIDIA共享库目录，启动voice-env；不输出环境、不改系统服务。
- `frame_queue.py`、`run_frame_queue.py`：确定性整数虚拟时钟，6组合成队列，不加载模型。
- `test_*.py`：26项机制测试，测试模型为受控夹具，不混GPU分母。
- `analyze.py`：从本轮固定最终目录重算、检查事件/输入哈希/线程/提交/计数并画图。

## GPU复现

需要相邻`/opt/p4/exp14/{models.py,logic.py,cases.json,audio/}`、已有`/opt/models/{faster-whisper-small,Qwen3-0.6B}`和`/root/voice-env`。原GPU服务保持运行；先只读检查资源。输出目录必须新建，所有输入WAV对照原manifest校验哈希。

```sh
cd /opt/p4/exp17
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 bash launch.sh --output /opt/p4/exp17/results/formal-new --repeat 3 --warmup 1
```

默认4输入：`short_03 pause_02 pause_03 long_02`；3策略：`endpoint eager stable2`，每格3次，共36条。策略顺序按case/repeat交替。独立热身为每条完整输入1次，共4次ASR+LLM，不混最终矩阵。其他参数：`--cadence-ms 800 --cases ... --policies ...`。任何失败保留对应JSON并停止，不补0或覆盖旧目录。

`endpoint`名称只作代码标签：本轮的明确gate是冻结文件供给完成，并未运行在线VAD。文件保留原约800ms尾静音，离线能量标注不参与source/commit调度。输入到达是同进程20ms供给，无网络或麦克风抖动。

- ASR：faster-whisper-small CUDA int8_float16，beam1、zh、condition_on_previous_text=False、vad_filter=False。
- LLM：Qwen3-0.6B CUDA BF16，关闭思考、贪心、上限96新token、输入上限1024，原exp14系统提示。
- 前缀ASR调用只处理当时已供给的PCM；已有调用不抢占，pending只留最新。full final快照不可丢。
- 文本键NFKC+lower+去空白/标点，不做繁简转换。仅用于当前受控文本，不能当通用语义相等。
- `eager`每次规范化转写变化就作废旧稿、stop+join后起新稿；`stable2`须两个完整观察相等才预生成，final则直接生成。不是LocalAgreement算法。
- 所有draft文字先缓冲，最终ASR键与当前draft键相同才提交；之后只提交选中draft。固定系统提示/上下文，没验证工具状态或历史变化。

GPU任务为一次性CLI进程，完成后退出，无新常驻HTTP服务或SSH转发。原始数据在远端新目录。取回到本机`phase4/results/exp17/gpu-formal-v1/`后，独立检查任务进程退出及原gpu-router状态，不以命令返回码代替。

## 合成队列与机制测试

```sh
python3 -B -m unittest discover -s phase4/exp17 -p 'test_*.py'
python3 -B phase4/exp17/run_frame_queue.py --output phase4/results/exp17/frame-queue-new
```

默认30fps、10s、300帧，固定100ms/按源帧ID增加250ms慢服务，FIFO待处理容量30满丢新、latest只保留1个pending且running不可抢占、200ms采样+latest。同刻顺序为完成running→捕获/替换→dispatch→输入结束快照。输入停止后完整drain。帧龄p95只算完成帧，最近秩法；各策略完成的快慢帧组合可不同。视觉理解/编码/覆盖质量未测，不推导真实GPU容量。

## 分析

```sh
/tmp/exp14-local-env/bin/python phase4/exp17/analyze.py
```

当前脚本固定读取`gpu-formal-v1`与`frame-queue-v1`，后续重跑需显式修改分析输入路径，不能误混版本。最终文件：`../results/exp17-summary.json`、`../img/exp17.png`，每格n=3；队列为6组单次确定性计算，不作重复统计。

文字延迟：文件供给结束→第一段通过最终转写核对的LLM文字提交；同server monotonic。最终ASR返回→提交另算。不是首声，不与800ms语音目标比较。累计送入ASR样本比不是GPU FLOPs；未采用草稿token不是GPU活跃时间，token含generate返回的终止token。ASR时长含CPU/调度/原生GPU调用，ASR与LLM有重叠，阶段分位数不能相加或当作单一因果收益。

当时源码：`../results/exp17/provenance/source-formal-v1/`；pilot、4热身独立保留。完整性/排版/测试/清理汇总在`../results/exp17/completion-verification.json`。正文和图卡见`../../18-Phase4·4-边听边开/`；未自动上传公众号。
