# exp15 执行记录

2026-10-22。用户授权继续 P4·2。既定大纲下实施有界传输与会话实验；设计见 `设计.md`。

- 当前：实验、分析、正文、图卡与微信排版均已完成，独立事实核对通过；本地成稿，尚未上传。
- 边界：本篇固定回放已生成音频，新增 GPU 推理次数为 0；实测传输与会话，不重测模型响应。
- 原始运行目录使用新名称；不覆盖 exp14 或旧实验结果。

- 本机 /tmp/exp15-env 与远端 /root/exp15-env 独立安装 aiortc 1.15.0 / av 17.1.0 / aiohttp 3.14.5 / numpy 2.5.4；首次CDN下载慢，改TUNA完成。远端原voice-env的av19不兼容aiortc约束，最终不复用其site-packages，未改原环境。
- DARYU SSH已通，WSL私网172段，原gpu-router active，整卡342/8188MiB，新增GPU推理0。
- 固定载荷：原GPU输出短2.4s/长14.95s，统一48kPCM16并增加首尾探针，最终3.12s/15.68s；manifest保留原文件及PCM/WAV哈希。
- 会话模块12项测试通过（RED/GREEN见session-tdd.log）。HTTP/WS正式4场景56断言、639帧逐字节验证；Python ACK为合成控制，不当音频播放。
- 真实浏览器排空：AudioWorklet消费149760样本，producer_done时最近报告仍有35456样本未确认；约654.7ms后finished，再release→a drained。35456为最近报告差额，不当作瞬时精确队列长度。
- 媒体pilot2/3/4保留为诊断：WS完整消费；WebRTC ICE/DTLS/DC与RTP收包成功，但渲染未产生，当前排查。离线Opus编码/解码已验证非零音频。去掉mute-audio未修复，不能将其写成根因。
- 首次服务探测早于就绪，空目录browser-pilot为启动失败诊断；runner异常时已补齐浏览器关闭。
- 观察到初次AudioWorklet启动时AudioContext时钟可能漏计真实等待，正式指标改为主线程收到首非静音渲染通知的performance时间差，包含消息派发；AudioContext差值仅留诊断。
- 远端SSH可达性：WS正常收发/播放；仅转发信令的WebRTC未完成ICE/DC，另存browser-remote-v1，不能与本机UDP组成协议公平速度对照。

- 定位媒体观测接线：加入AudioElement后RTP解码已正常，但MediaElementSource读取srcObject时观察为零；最后使用AudioElement激活播放+直接MediaStreamSource→Worklet，pilot5/6两路径均首/尾探针完成。正式辅助元素volume=1e-6；不是mute-audio修复。
- 首轮正式24条（browser-formal-v1）尾探针完成，但2条RTC source_pause/short在producer_done控制到来前即关闭，源供应样本总数均完整。补齐媒体完成与源完成双barrier，重跑全矩阵至browser-formal-v2，旧数据不混入最终分布。
- 原正式源代码快照source-media-formal、最终快照source-media-final分别保留；服务原始事件通过run_id关联，未覆盖。
- 远端可达性最终browser-remote-v2：WS完整播放；RTC没有完成ICE/DC，未配置STUN/TURN，不能归因成WebRTC通用不可用或协议速度失败。远端服务已停、GPU350MiB、gpu-router active，专用18147转发已停。
- 最终v2全24条完成：12WS源/接收/渲染样本一致，12RTC源完整、尾探针+guard与源结束控制全部到达；开始快照无inbound-rtp的区间统计保留null。最终统计/图仅使用v2。
- 正文与结论经独立事实核对：收窄实际HTTP/WS验证的轮次描述，修正35456为受报告滞后影响的未确认差额，明确654.7ms在浏览器观察producer_done→finished之间计时。
- 封面、一页纸、实验图及390px微信排版核对通过；4张表无溢出，2图正常加载。P4·2已成稿，尚未上传。
- 本地18145/18146/18147/18148及远端18145独立TCP探测均关闭，媒体peer/websocket均0再停进程；证据见results/exp15/cleanup-verification.json、completion-verification.json。
