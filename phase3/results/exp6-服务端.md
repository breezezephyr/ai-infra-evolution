| 窗口 | 客户端完成/错误 | running 峰 | waiting 峰 | KV 峰 | 抢占 | 服务端完成(reason) | prompt tok | gen tok |
|---|---|---|---|---|---|---|---|---|
| exp6-fcfs | 130 / 0 | 5 | 0 | 89% | 0 | {'stop': 0, 'length': 131, 'abort': 0} | 235537 | 28802 |
| exp6-pass | 145 / 0 | 6 | 3 | 92% | 0 | {'stop': 0, 'length': 146, 'abort': 0} | 268416 | 32674 |
| exp6-prio | 169 / 0 | 5 | 0 | 89% | 0 | {'stop': 0, 'length': 171, 'abort': 0} | 236692 | 30363 |
| exp6-reserve | 171 / 0 | 5 | 0 | 76% | 0 | {'stop': 0, 'length': 173, 'abort': 0} | 235337 | 30302 |
