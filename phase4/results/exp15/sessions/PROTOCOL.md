# exp15 独立会话服务协议

此服务仅验证单进程逻辑 worker a/b 的会话状态和真实回环 HTTP/WS 传输；不加载 GPU，不导入 aiortc。常规媒体 server/client 不依赖它。

## 启动与自动实验

```sh
/tmp/exp14-local-env/bin/python -B phase4/exp15/run_sessions.py
```

脚本先检查 18146 未被占用，再启动自己的服务子进程，运行场景，并在 finally 中停止该子进程、TCP 回读确认端口关闭。若端口原本被占用则拒绝运行，不结束其他服务。默认输出到 `phase4/results/exp15/sessions/run-<UTC>/`。各次实验独立目录，不覆盖失败分母。

主 agent 需要接入浏览器时，单独启动一个新服务实例（worker 的 drain/forced 不可恢复为 active）：

```sh
/tmp/exp14-local-env/bin/python -B phase4/exp15/session_http.py --port 18146 --events phase4/results/exp15/sessions/browser-server-events.jsonl
```

绑定固定为 `127.0.0.1`。此手动实例由启动者关闭。

## HTTP

所有请求和响应为 JSON。错误为 `{"error":"<SessionError.code>"}`；未知 session 为 404，无效参数为 400，状态冲突为 409。

| 方法 | 路径 | 请求/响应 |
| --- | --- | --- |
| GET | `/health` | ready 和固定音频元数据、WAV/PCM SHA-256 |
| POST | `/sessions` | `{session_id, preferred_owner?}` → session 副本 |
| GET | `/sessions/{session_id}` | session 副本 |
| GET | `/state` | `{workers: {a:..., b:...}, sessions: {id:...}}` |
| POST | `/workers/{owner}/drain` | `{}` 或 `{deadline_ms:200}` → worker 副本 |

deadline 是服务端 event loop 的真实 call_later 定时器，必须在 (0,60000] ms 内。正常排空时取消 deadline；触发时仅对仍 draining 的 worker 调用 force_drain。计时只在同一服务器 monotonic 时钟内相减。

## WebSocket

地址：`ws://127.0.0.1:18146/session-ws?session_id=ID&owner=a`。

先通过 HTTP 创建 session。错 owner / 并发第二连接在升级前返回 HTTP 409。成功后收到：

```json
{"type":"attached","session":{"epoch":1,"owner":"a"},"audio":{"sample_rate":48000,"total_samples":149760,"frame_samples":960}}
```

以上示例省略其他状态字段。客户端控制消息：

```json
{"type":"begin","epoch":1,"generation":"turn-1"}
{"type":"ack","epoch":1,"generation":"turn-1","played_samples_cumulative":24000}
{"type":"release","epoch":1}
```

begin 可带 total_samples，但必须与固定 WAV 一致。generation 为非空字符串或非负整数。所有控制都必须携带连接绑定的 epoch；旧 epoch ACK 返回 `{"type":"error","error":"stale_epoch","epoch":2}`，不能改变播放进度。

服务消息：`begun`、`producer_done`、`acknowledged`、`released`、`forced` 带 session 副本；释放/强制消息同时带 worker 状态。其他状态拒绝返回 `type:error`。正常释放后 WS 关闭；deadline force 发送终态并以 4001 关闭。

### 二进制音频

每帧头为 12 bytes：三个大端 uint32，依次为 seq、sample_offset、sample_count；后接 `sample_count * 2` bytes 的单声道小端 PCM16。seq 每次 begin/resume 从 0 开始，offset 是原 generation 中的绝对样本偏移。48kHz 下每帧最多 960 samples，即 20ms；最后一帧可以短于 20ms。发送按真实单调时钟 cadence 调度，不模拟丢包或播放。

重连：attach 得到新 epoch，再用相同 generation 发 begin。begun.session.resume_from 等于保留的 played_samples。第一个重发帧的 offset 必须等于该值；ACK 继续使用原 generation 的绝对累计样本数。历史 sent_samples 保留，但新连接必须有对应的 epoch_sent_samples，才能接受新的播放 ACK。服务器不保存音频队列副本；固定 WAV 用于重放。

producer_done 仅说明固定载荷发送完毕。正常 release 仍要求有效 ACK 达到 total。所有 session 均 release 后 worker 才 drained。force 保留 played，不补 ACK，记录 total-played 和 sent-played，不宣称正常排空。

## 浏览器 AudioWorklet 复验入口

新增 `session-client.js` 复用原 worklet.js，不修改主媒体文件。模块通过本服务提供，支持主媒体页面跨端口调用（CORS）。在浏览器按钮等用户手势中执行：

```js
// 可提前加载模块；playSession 本身必须从用户手势调用。
const {playSession} = await import('http://127.0.0.1:18146/session-client.js');
button.onclick = async () => {
  const playback = await playSession({
    sessionId: 'browser-drain-a', owner: 'a', generation: 'browser-turn-1',
    initialBufferMs: 600, drainOnProducerDone: true, autoRelease: true,
    onEvent: event => console.log(JSON.stringify(event)),
  });
  const rendering = await playback.played;
  const terminal = await playback.done;
  console.log({rendering, terminal}); // 保存 events，关联同名 session 的服务端事件。
};
```

适配器在主线程至少累计 600ms PCM 后才交给 worklet；保留 worklet 原有 2880-sample 阈值，不要求 main 修改配置。worklet 的 progress/finished consumed 才发送 ACK，重连时累加 resume_from。producer_done 到达时记录最新 consumed，并请求正常 drain；只有 worklet finished 后才 ACK 完整样本并 release。

主 agent 复验应保存 `initial_buffer_released`、`producer_done_observed`、worklet `finished` 和最终 worker drained 事件。producer_done 时应仍有未渲染样本；期间 worker 必须 draining。只比较浏览器自己的 performance_ms/音频帧时钟；不要与服务器 monotonic_ns 交叉相减。consumed 是渲染计数，不是声学回环或可闻确认。

**此适配器尚未完成实际浏览器验证。** Python 自动实验仅发送合成 ACK，不创建声卡输出，不声称声音已播放，也不提供浏览器播放延迟。

## 证据

每次运行保存 summary.json（逐场景断言和清理结果）、client-events.jsonl、server-events.jsonl、server-stdout.log，以及接收到的真实 PCM/重发后缀。每帧含序号、offset、样本数和 PCM SHA-256；客户端逐帧与 WAV 对照，防止仅以成功消息作为传输证据。
