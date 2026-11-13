| 窗口 | 客户端完成/错误 | running 峰 | waiting 峰 | KV 峰 | 抢占 | 服务端完成(reason) | prompt tok | gen tok |
|---|---|---|---|---|---|---|---|---|
| exp5-pass-c32 | 256 / 0 | 12 | 23 | 100% | 60 | {'stop': 0, 'length': 258, 'abort': 0} | 277109 | 66019 |
| exp5-queue-c32 | 142 / 114 | 9 | 0 | 91% | 0 | {'stop': 0, 'length': 146, 'abort': 0} | 156769 | 37468 |
| exp5-reject-c32 | 9 / 247 | 9 | 0 | 84% | 0 | {'stop': 0, 'length': 11, 'abort': 0} | 11506 | 2774 |
| exp5-ttft5-c32 | 84 / 172 | 12 | 23 | 100% | 20 | {'stop': 0, 'length': 87, 'abort': 0} | 94855 | 22280 |
