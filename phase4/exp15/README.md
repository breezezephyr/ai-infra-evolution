# exp15 · 传输与会话

设计与执行：[设计](设计.md)、[记录](progress.md)。本轮固定回放 exp14 真实 GPU 输出，新增模型推理为 0，验证媒体与会话控制；不把音频回放称为完整 ASR→LLM→TTS 回合。

## 模块

| 文件 | 边界 |
|---|---|
| `prepare_audio.py`、`audio/manifest.json` | 原输出 24kHz→固定 48kHz PCM16，首尾增加探针；保存原始和新载荷哈希 |
| `server.py` | aiohttp WS/PCM 与 aiortc WebRTC/Opus；默认只绑定回环，无 SFU、无 GPU |
| `client.js`、`worklet.js` | 真实 Chrome 播放观察、PCM 完整性、RTP stats、首尾探针；不是声学回环 |
| `run_browser.cjs` | 新 Chrome 进程的有界媒体回放，按样例/模式轮换；pilot 与正式批次分开 |
| `session.py` | 单进程逻辑 worker a/b 的 owner、epoch、generation、进度和 drain/force；不实现历史/KV 迁移 |
| `session_http.py`、`run_sessions.py` | 实际 HTTP/WS 控制实验，逐帧校验；Python 播放 ACK 明确为合成控制 |
| `session-client.js`、`run_session_browser.cjs` | 实际 AudioWorklet 消费后 ACK 的正常排空复验 |
| `analyze.py`、`plot.py` | 最终媒体、会话控制、浏览器排空证据与图表 |

## 环境与运行

本机 `/tmp/exp15-env`、DARYU `/root/exp15-env` 为独立 venv：aiortc 1.15.0、av 17.1.0、aiohttp 3.14.5、numpy 2.5.4。版本锁与源码快照在 `../results/exp15/provenance/`。不复用/覆盖原 voice-env 的 av 19；原 router/vLLM 配置没有修改。

本机生成固定载荷：

```sh
/tmp/exp15-env/bin/python phase4/exp15/prepare_audio.py \
  --short phase4/results/exp14/live-final-v1/live-final-v1-pause_02-r0-A-69.wav \
  --long phase4/results/exp14/live-final-v1/live-final-v1-long_01-r2-C-91.wav
```

媒体服务与回放分开运行。输出目录必须是新目录，不能覆盖历史数据：

```sh
/tmp/exp15-env/bin/python -u phase4/exp15/server.py --port 18148 --output phase4/results/exp15/media-server-new
node phase4/exp15/run_browser.cjs --mode formal --repeat 3 --url http://127.0.0.1:18148 --output phase4/results/exp15/browser-new
```

需已安装 Chrome 与 Playwright；本仓库脚本指向 Codex bundled Playwright。默认 headless，移除默认 mute 参数，且显式记录版本。音频元素用于激活 WebRTC 原生播放，观察节点直接接 MediaStream；辅助元素近静音，观察路径仍实际处理完整 PCM。最终配置使用主线程首非静音 AudioWorklet 通知，不以 `play()` 成功代替音频。

会话控制实验自启动/停止服务并独立回读端口：

```sh
/tmp/exp14-local-env/bin/python -B phase4/exp15/run_sessions.py
python3 -B -m unittest discover -s phase4/exp15 -p test_session.py -v
```

真实浏览器排空需要另外启动 `session_http.py` 的新实例，因为已经 drained/forced 的 worker 不重新开放；步骤和协议见 `../results/exp15/sessions/PROTOCOL.md`。`run_session_browser.cjs` 使用实际点击创建 AudioContext，再通过 worklet 消费量报告 ACK。

## 口径

- 两条规范化载荷为 3.12s / 15.68s，含人为首尾探针与零尾，不是两段真人通话；独立媒体内容只有 2 条。
- 正式矩阵：2 条载荷 × 2 条路径 × 正常/源暂停 200ms × 3 次重复。源暂停是供给中断，**不是注入网络丢包**。没有运行 netem、没有测公网弱网容量。
- WS 为 20ms PCM 包，应用初始缓冲 2880 samples=60ms。WebRTC 为 Opus、48kHz、原生媒体缓冲，编码和缓冲策略不同；同机两种实现的观测不能叫纯协议性能排名。
- `connect_ms` 包含信令、连接与播放器准备（包括观察节点热身），不等于纯握手 RTT。`start_to_first_render_ms` 是媒体开始控制发送到主线程收到首非静音 AudioWorklet 通知的 performance 差，含消息派发。输入为已经就绪的 WAV，不是用户说完到首声。
- `audio_clock_start_to_first_render_ms` 与历史 `connect_to_first_render_ms` 为 AudioContext 时钟诊断，不作为正式首声指标；首次图启动时该时钟可能漏计实际等待。主线程 performance 与服务器 monotonic 不直接相减。
- WS 的 received/consumed 与源样本数逐条相等；欠载排除起播等待和正常末尾静音。WebRTC 以尾探针渲染 + 250ms guard **以及**源结束控制消息确认内容结束，不能用有损解码后的样本总数冒充 bit-exact 源 ACK。
- WebRTC concealment 与 WS 欠载定义不同，分栏报告；RTP 丢包、jitter、累计抖动缓冲等只按实际 stats 填，缺失为 null。
- Python 会话 ACK 是合成控制；浏览器 ACK 来自 AudioWorklet 渲染消费，仍不是扬声器声学证明。单进程两个逻辑 owner 不代表两台机器或两张 GPU；没有测历史、KV 或故障迁移。
- DARYU 经公网 SSH/TCP 转发做独立可达性检查。信令可达但 RTC 没建立媒体/控制，不与本机 UDP 对照组成速度排名；没有为该路径设置 STUN/TURN 或改系统防火墙。

## 数据版本

- `browser-pilot*`：播放器接线、启动时钟与就绪诊断，保留失败，不混入正式分布。
- `browser-formal-v1`：首次 24 条，尾探针均观察到；2 条 RTC 短载荷先结束媒体观察，未等到源结束控制，按旧完成定义保存，**不用作最终统计**。
- `browser-formal-v2`：双完成条件修复后的最终 24 条；源/媒体结束分别核对。
- `media-server-formal`：两版的服务事件按唯一 run_id 保存，不覆盖；通过最终浏览器 run_id 关联。
- `browser-remote-v2`、`remote-server`：SSH 远端可达性证据；v1 为前次诊断。
- `sessions/http-ws-final`：4 场景/56 断言的真实控制验证；`sessions/browser-playback` 为独立实际渲染排空。

实验服务与专用隧道结束后关闭，保留独立环境、载荷与原始数据，清理回读另存。
