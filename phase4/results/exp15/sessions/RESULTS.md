# exp15 会话 HTTP/WS 实验结果

最终运行：[summary.json](http-ws-final/summary.json)。共 4 个功能场景加启动检查，56 项断言全部通过。服务自启动、自停止，退出码 0；独立 TCP 回读 18146 关闭（connect_ex=61）。

| 场景 | 结论 |
| --- | --- |
| Sticky 多回合 / 错 owner / 双连接 | 同一 owner、epoch 连续两回合；错 owner 和双连接升级前 409 |
| 排空拒新 / withheld ACK | a 拒绝新建，新会话自动到 b；producer_done 后仍等待 ACK，提前 release 被拒绝 |
| 断线重连 / 旧 epoch ACK | epoch 1→2；从 played=9600 重发；旧 epoch ACK 拒绝；全部 ACK + release 后 a 正常 drained，取消 15s deadline |
| 真实 deadline force | b 的 200ms 定时器实际触发；服务器单调时钟间隔 201.265ms；明确 forced、drained=false |

固定音频 48000Hz 单声道 PCM16，149760 samples，3.12 秒。WAV SHA-256：`bfeaf719c18cb1bd2e7aff28c0fbeb01805f9b8b529fae53ba120f541f9863d6`。逐帧与原 WAV 比对，完整接收或精确接收重连后缀，保留 PCM 文件。

强制终态保留 played=24000、sent=149760、unplayed=125760，没有补 ACK 或伪装播放完成。

Python 客户端仅合成 ACK 验证控制逻辑，不发声；所有发送/定时器计时不作为浏览器播放延迟、可闻延迟或线上分位数。新增浏览器适配器仅完成语法和真实 HTTP 资源/CORS 验证，尚待主 agent 实际 AudioWorklet 复验。

## 证据入口

- [最终完整服务事件](http-ws-final/server-events.jsonl)：711 条，单调时钟及 sequence 连续，末条 server_stopped。
- [最终完整客户端事件](http-ws-final/client-events.jsonl)：754 条，含每场景断言、HTTP 响应、WS 控制与帧完整性。
- [证据一致性核验](evidence-audit.json)：服务发送与客户端验证各 639 帧。
- [清理独立回读](cleanup-recheck.json)。
- [协议与浏览器调用示例](PROTOCOL.md)。
- [初始 RED](red-no-http-service/summary.json)：服务尚未实现时运行失败，未丢弃失败分母。
- [首轮 GREEN](http-ws-run-1/summary.json)：51 断言通过。
- [文件指纹回读](file-scope-check.json)。

## 问题与范围

`session.py`、`server.py`、`worklet.js` 前后 SHA-256 一致。`client.js` 在本次实验窗口内哈希变化；本次工具调用没有写该文件，未覆盖该变化，保留前后指纹供主 agent 核对。早期把四个文件都要求 hash 不变的范围核验因此报过一次 AssertionError；这是文件观察冲突，不是 HTTP/WS 场景失败。

服务没有 GPU、远程或 aiortc 依赖。手动浏览器复验需重新启动服务，因为 drained/forced worker 不重新开放。
