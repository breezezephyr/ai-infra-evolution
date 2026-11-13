# exp15 · 传输与会话：实验结论

日期：2026-10-22。对应 [P4·2正文](../../16-Phase4·2-这位乘客还没下车/正文.md)。设计、代码与复现：[exp15 README](../exp15/README.md)；机器可读汇总：[exp15-summary.json](exp15-summary.json)；[图](../img/exp15.png)。

## 1. 本轮测了什么

新增 GPU 推理 **0 次**。复用 exp14 的两段实际 GPU 输出（2.4s / 14.95s，24kHz PCM16），固定重采样为48kHz，增加首尾探针及零尾，最终载荷 **149760 / 752640 samples，3.12s / 15.68s**。原文件及规范化后的哈希在[载荷清单](../exp15/audio/manifest.json)；不是两段真人通话，只有2条独立媒体内容。

本机 Mac Chrome **155.0.8059.85** 的实际 headless 音频渲染，服务为独立venv中的 aiortc1.15.0、av17.1.0、aiohttp3.14.5、numpy2.5.4；WS/PCM 与 WebRTC/Opus 两种实现。WS20ms包、60ms初始缓冲；WebRTC用原生媒体接收链路，选中的12对候选均为 **UDP host/host、succeeded**，真实 codec 为 **audio/opus、48kHz**。

两条载荷 × 两种传输 × 正常/源端暂停200ms × 三次重复 = **24条最终回放**。最终仅用 `exp15/browser-formal-v2/records.json`，不是v1或pilot。

## 2. 正式回放与计时

24/24达到本实验完成条件，无客户端error。所有源供应样本总数与载荷一致。

- WS12/12：源样本数=接收样本数=AudioWorklet消费样本数。
- RTC12/12：源完整、尾探针渲染+250ms guard、源结束控制全部到达；这是有损音频与应用控制的联合检查，**不是逐样本源ACK**。
- 各次保留完整分母及所有原始事件。没有人工注入network loss、netem或公网弱网负载；200ms是生产者暂停。

正常供给，每路径n=6（两条载荷各三次），p50：

| 实现 | 连接与播放器就绪 | 开始供给→首非静音渲染通知 |
|---|---:|---:|
| WS/PCM | 94.00ms | 46.60ms |
| RTC/Opus | 292.25ms | 33.75ms |

前列包含信令、连接与观察节点准备（包括80ms热身），不是纯握手延迟；后列为浏览器主线程收到AudioWorklet通知的performance差，含消息派发。载荷已提前生成，首个声音为测试探针，不是“用户说完→回答首声”，也没有声学回环。

两套编码、缓冲和实现不同，本机两端没有CPU隔离，不把这些数当纯协议排名、容量或生产SLO。AudioContext时钟诊断字段未用于主指标，服务器monotonic也未与浏览器performance直接相减。

## 3. 欠载与掩盖分开记

每格n=3，p50：

| 场景/指标 | 短载荷 | 长载荷 |
|---|---:|---:|
| 正常供给：WS累计欠载ms | 0.00 | 0.00 |
| 源暂停：WS累计欠载ms | 185.33 | 264.00 |
| 正常供给：RTC结束快照掩盖样本 | 1311 | 8059 |
| 源暂停：RTC结束快照掩盖样本 | 13306 | 12814 |

WS的累计欠载排除起播等待与正常零尾；长载荷264ms包含本轮其他等待，不能用注入200ms直接解释全部欠载。

RTC12/12在开始供给前均没有 `inbound-rtp` 对象，**起止差分的包数、concealedSamples和平均抖动缓冲延迟为null**；结束快照不冒充区间增量。掩盖可含丢失或迟到替代样本，与WS欠载不同。基线也有掩盖，不能把所有掩盖归因于源暂停，更不能据此推断网络丢包/主观音质。

## 4. 实际会话控制

单进程两个逻辑owner a/b，不加载GPU，不做历史/KV或故障迁移。

- 12项状态模块功能测试通过，RED/GREEN在 `../exp15/session-tdd.log`。
- 实际HTTP/WS控制4场景56项断言通过，639帧真实PCM逐帧校验。证据 `exp15/sessions/http-ws-final/`，Python ACK全部标记为合成控制。
- 同连接多轮、错owner与并发连接409；a draining拒绝新会话，新会话路由b，已有会话保持a。
- 断线重连epoch1→2，从保留played=9600重发。旧epoch ACK拒绝；新epoch ACK也不得越过本连接已发送范围。
- producer_done后未获完整ACK仍不可正常release/drained；全部确认并release后才正常排空。
- 200ms真实deadline约201.265ms触发：sent149760、played24000、未获确认125760，终态forced、drained=false，不伪造ACK。此场景无实际播放，不能称测到音频丢失。

## 5. 独立真实浏览器排空

`exp15/sessions/browser-playback/`：n=1，刻意配置600ms起播缓冲。消费149760样本，ACK来自AudioWorklet，非合成控制。

浏览器观察到producer_done时，按最近一条消费报告计算仍有35456样本未确认；该差额受报告滞后影响，**不是瞬时精确队列长度**。从浏览器观察到producer_done起，约 **654.7ms** 后收到worklet finished，再完整ACK/release，worker a才drained。计时均为浏览器performance；无声学回环，不称可闻末声。

## 6. 独立远端可达性

`exp15/browser-remote-v2/records.json` 与 `exp15/remote-server/`：Mac经公网SSH/TCP转发到DARYU WSL私网，WS回放完整；WebRTC offer成功返回，但 **15秒观察窗口内ICE/DC没有连通**，不能证明媒体可达。

该路径未配置STUN/TURN或额外UDP映射，没有改防火墙。只用于说明信令与媒体需各验，不能与本机UDP拼成公平速度比较，也不推出所有WebRTC无法使用。

## 7. 版本与清理

- pilot保留所有接线/启动失败。独立Opus编解码已有非零样本；最终以媒体元素激活原生播放、MediaStreamSource直接接观察节点，辅助元素近静音。
- v1的24条尾探针完成，但2条RTC source_pause/short在源结束控制到达前关闭；源音频均完整供应。修复双barrier后整矩阵重跑v2，不混统计。
- 原/最终源码快照、哈希与两端版本锁在 `exp15/provenance/`。最终回放逐run关联 `exp15/media-server-formal/` 服务事件，保留了两版原始数据。
- 结束前媒体服务 peer_connections=0、websockets=0；本机18145/18146/18147/18148、远端18145均已关闭，专用SSH隧道已停。原gpu-router active，最后整卡已用350MiB（含桌面基线）；独立venv/载荷/原始数据保留。
- 清理证据：`exp15/cleanup-verification.json`。本轮无麦克风上行、AEC、SFU、多人、主观音质、声学回环或多GPU容量验证。
