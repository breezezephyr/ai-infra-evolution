# exp13 · 审完再发，还是先发后审

2026-10-22。首轮保留CPU对照与受控HTTP回放；随后按用户授权停止Windows ComfyUI，补齐GPU独立审核和同卡真实生成＋真实审核。

## 资源操作

ComfyUI是Windows原生实例，路径 `E:\ComfyUI-NoctQ\python_embeded\python.exe`、端口8189。停止前队列running/pending均0，PID14920与路径/命令/端口匹配；调用有守卫的 `E:\ComfyUI-NoctQ\stop_noctq.ps1`，显存6203→342MiB。未终止其他Python进程，未改WSL原有服务状态。操作记录 `gpu-resource-change.json`。ComfyUI按用户要求保持停止。

## 三层证据，分别保存

1. `reviewers-cpu.json` / `reviewers-gpu.json`：审核器独立实测。12条手写虚构文档保密规则样例，6应拦/6允许。3个违规参考含一条与测试句相同，无独立训练/测试划分；不是泛化基准。CPU四线程FP32与GPU BF16是不同运行配置。嵌入36次、分类24次；重复仅扩大测时样本，质量按每题首轮计。
2. `http-replay.json`：首轮受控HTTP/SSE，每12ms一个Unicode字符，已知标签＋CPU实测耗时回放；30条，用于隔离放行机制。主结论不能把它改名为真实审核性能。旧图 `../img/exp13-cpu-controlled.png`。
3. `gpu-live.json`：实际Qwen3-0.6B生成＋实际逐句Embedding-0.6B或0.6B分类；3份BF16权重同卡，按模式选一个审核器，无oracle、无延迟sleep。安全/标记流每模式各3轮，共30条。生成采用给定文字复制任务，便于标记偏移；不是广泛自然生成质量评估。独立临时loopback服务，未改现网router/vLLM。

## 计时与判定

- 独立嵌入：分词＋CPU/GPU forward＋池化归一化。GPU权重BF16，池化、归一化和相似度转FP32，避免低精度归一化令余弦超过1；CPU原数据保留。
- 独立分类：模型generate，含提示词prefill与输出，不含分词；均不含模型加载和HTTP。
- GPU独立计时前后CUDA同步。同卡真实路径调用耗时还包含分词、任务调度及同期GPU工作等待，不能把两者差额都解释成纯GPU争抢。
- 标记句漏出按**实际生成文本**定位，再校验门的blocked_start/end覆盖该句。标记句未完整观察时记null另计；不以误拦前面安全句伪造“正确拦截零漏出”。单位是Unicode code point，不是token或有害事实数。
- 客户端首段、可见批次间隔不称模型TPOT。模型也可能一次增量有多个字符。

## 代码和复现

```bash
# 从仓库根目录
python3 -m unittest discover -s phase3b/exp13 -p 'test_*.py'
# DARYU /opt/p2/exp13；只写该目录，无systemd实验服务
CUDA_VISIBLE_DEVICES='' /root/vllm-env/bin/python measure_reviewers.py --out reviewers-cpu.json
/root/vllm-env/bin/python measure_reviewers.py --device cuda --out reviewers-gpu.json
/root/vllm-env/bin/python run_gpu_live.py --out gpu-live.json --repeats 3
# 可独立复现首轮受控回放
/root/vllm-env/bin/python run_http.py --reviewers reviewers-cpu.json --out http-replay.json --interval-ms 12 --repeats 3
# 拉回JSON后
python3 phase3b/exp13/analyze.py
phase2/.venv/bin/python phase3b/exp13/plot.py
phase2/.venv/bin/python phase3b/exp13/plot_cpu_controlled.py
```

`gate.py`：完整窗口审核后发，或异步先发后审。上游文本队列、审核任务数有界；超时/异常/积压明确终止，最后无标点尾句也审。默认每窗口最多64字符，独立窗口仍可能拆散关键词或跨句语义；审核记录随总输入增长，不宣称总内存恒定。

`transport.py`：按UTF-8/SSE空行边界解析正文，支持跨任意网络字节拆包；无[DONE]的EOF报错；透传上游length等终止原因。

`async_threads.py`：GPU审核to_thread工作用shield循环收拢，取消或重复取消也等真实worker结束再退出锁。

`run_gpu_live.py`：模型在GPU实际生成，经SSE适配送门控；逐句实际审核。客户端断开后用停止事件和join等待生成线程，记录生成stop/length/cancelled、生成ID计数（含EOS）。SSE发送前保留真实上游终止原因，不把长度截断叫自然完成。生成线程退出不等于供应商停止计费，也不替代vLLM abort证据。

`analyze.py`：结果 `../results/exp13-summary.json` 保存CPU、GPU、受控回放、真实GPU分组与输入SHA-256。旧受控字段 `observed_including_cleanup_ms` 含约36ms收拢等待，不当作端到端响应时长汇总。

## 验证与边界

17项单测：跨增量拒绝、尾句、窗口上限、审核超时/异常/积压、异步命中、取消、客户端断开、字节拆包、上游EOF、自行取消、关闭异常、突发多句、真实线程取消及重复取消、length透传。DARYU与本机均通过。另有受控HTTP客户端断开smoke。

真实GPU的30条记录检查客户端可见文本为实际生成前缀、线程均退出、拦截偏移与标记句吻合。只验证本组单流生成与审核交错，不推导生产多租户容量。滥用画像仍全为合成，旧日志缺可信Key/tenant/request_id，不回填真实归因。

## 资料

- [WHATWG SSE](https://html.spec.whatwg.org/multipage/server-sent-events.html#parsing-an-event-stream)
- [Azure流式审核](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/content-streaming)
