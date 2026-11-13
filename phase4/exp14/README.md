# exp14 · GPU语音接力

设计和实施依据：[设计](设计.md)、[实施计划](实施计划.md)、[执行记录](progress.md)。

真实数据与结论在 [exp14结论](../results/exp14-结论.md)、[汇总JSON](../results/exp14-summary.json)、[实验图](../img/exp14.png)。主批次是108条真实级联回合，外加3条独立热身；CPU只用于VAD/前后处理与网络。

## 文件职责

| 文件 | 用途 |
|---|---|
| `prepare_audio.py`、`cases.json`、`audio/` | Tingting独立输入、受控停顿、参考区间和哈希 |
| `protocol.py` | 28字节包头、PCM16、序号/轮次/样本偏移、VAD窗口重组 |
| `logic.py` | 端点、分句、真实线程等待、字符错误率 |
| `models.py` | 显式CUDA的ASR/LLM/TTS和CPU VAD；本地固定权重 |
| `measure_components.py` | 组件独立/共驻固定样例与热身 |
| `pipeline.py` | 有界文本/音频队列、TTS线程、取消和EOF收拢 |
| `server.py` | 仅回环的WS服务、完整输入保留、播放ACK和回合事件 |
| `run.py` | 按采样节奏重放输入，Python只收流不冒充播放 |
| `client.html`、`playback.js` | AudioWorklet播放、采样率转换、同钟域时间、设备输出估计 |
| `analyze.py`、`plot.py` | 分母、提前端点、配对一致性、样本/哈希/线程证据及静态图 |

## DARYU环境

新venv `/root/voice-env` 通过 `.pth` 只读复用 `/root/vllm-env/lib/python3.12/site-packages`；新增依赖只安装到新venv。原有环境232个distribution名称/版本安装前后相同。包元数据Torch版本为2.6.0，实际CUDA运行时版本字符串为2.6.0+cu124，不能把两者差异当成CPU回退。

ASR/TTS权重固定到HF revision；Qwen3是已有本地文件，revision未知，另存每个文件的SHA-256。模型下载清单、版本锁与运行源码快照保留在实验结果的provenance目录。需要复现时同样检查CUDA、动态库路径、显存和现有任务，不根据旧快照判断当前资源。

代码同步到 `/opt/p4/exp14/`。CTranslate2需能加载CUDA12/cuDNN9；启动进程前令 `LD_LIBRARY_PATH`包含原环境 `site-packages/nvidia/*/lib` 的实际目录。这只作用于该实验进程，不修改系统服务。

## 复现

本机生成输入（生成后的WAV已随实验保留，不要求每次重新合成）：

```bash
python3 prepare_audio.py --output audio
```

DARYU上，先按上节配置该进程的动态库路径，再分别启动服务和采集端。正式结果目录必须是新目录，禁止覆盖旧JSONL。

```bash
/root/voice-env/bin/python server.py --port 18144 --output results/server-new
/root/voice-env/bin/python run.py --output results/live-new --warmup 1
```

组件实测：

```bash
/root/voice-env/bin/python measure_components.py --component asr --audio audio/short_01.wav --output results/components-new
/root/voice-env/bin/python measure_components.py --component llm --audio audio/short_01.wav --output results/components-new
/root/voice-env/bin/python measure_components.py --component tts --audio audio/short_01.wav --output results/components-new
/root/voice-env/bin/python measure_components.py --component resident --audio audio/short_01.wav --output results/components-new
```

浏览器：通过SSH只把远端127.0.0.1:18144转发到本机localhost，打开页面点击A/B/C。这是预制音频输入＋真实回答播放，不请求麦克风权限。每次完整播放后POST结果到同一实验服务，页面也可下载JSON。输出ACK按实际消耗的24k样本推进，服务器最多允许2秒未消费音频；收到terminal后继续播放队列尾部，直到实际排空。

分析（在系列根目录执行）：

```bash
python3 phase4/exp14/analyze.py --records phase4/results/exp14/live-final-v1/records.jsonl --components phase4/results/exp14/components --browser-dir phase4/results/exp14/server-eof-fixed --output phase4/results/exp14-summary.json
python3 phase4/exp14/plot.py --summary phase4/results/exp14-summary.json --output phase4/img/exp14.png
```

`analyze.py`只需标准库；`plot.py`需matplotlib。缺少播放或设备字段保持null，ASR/回答不一致的配对另报，绝不把分位数相加。

数据版本：`live-final-v1/`为108条正式记录+3热身；`live-eof-fixed-smoke/`是最终EOF修复后的3条GPU复验；`server-eof-fixed/`包含最终3条浏览器记录。`server-fixed/`的前次浏览器记录和其他smoke目录均为诊断，不混入主统计。`provenance/source-live-v1/`保存正式批次源码，`source-manifest-eof-fixed.json`指向当前复现版。两批数据逐条验证生成/发送/接收样本总量一致。

显存为整卡已用量采样，含基线/其他进程，不是精确每进程统计。组件原始 `tts.total_ms`含PCM转换与WAV落盘，报告的TTS首包指标采用`first_pcm_ms`；保留原始字段，不作纯模型耗时解释。

## 测试

本机功能测试环境为 `/tmp/exp14-local-env`（aiohttp、matplotlib）；DARYU使用 `/root/voice-env`。纯逻辑测试不加载GPU模型，组件/回合的真实CUDA证据另存。

```bash
/tmp/exp14-local-env/bin/python -m unittest discover -s phase4/exp14 -p 'test_*.py' -v
node --experimental-default-type=module --test phase4/exp14/test_playback.mjs
```

服务为临时实验进程，结束后停止服务、监控和SSH转发，保留权重/venv/数据，不改变ComfyUI与原有gpu-router服务配置。
