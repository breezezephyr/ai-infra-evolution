# exp16 进度

2026-10-22：完成。下一章节为P4·4 / exp17增量输入的调度。

- 实际CUDA LLM/TTS、固定文字输入、受控播放位置取消；不包含麦克风、ASR/VAD/AEC或声学测量。
- pilot验证当前TTS调用必须等返回，正式将小段上限收敛为12字符以同时覆盖完整段和部分段。迟到探针正式版采用合法payload，靠generation屏障拒绝。
- 最终6次GPU取消探针、18条双轮浏览器对照全部完成；9条受控迟到帧拒绝，18条下一轮完整播放。历史真实进入下一轮模型输入。
- 4项Python与12项worklet机制测试通过；原始WAV、发送/接收/消费、哈希、线程退出及源码快照核对通过。
- 正文、封面、图卡、实验图、微信预览与独立事实审查通过；尚未上传。三篇P4·1～3均保持未上传状态。
- 专用实验服务与SSH隧道已关闭，实验PID退出、本地/远端18149关闭，原gpu-router active，GPU回到342MiB。
- 结果见`../results/exp16-结论.md`与`../results/exp16-summary.json`；清理、测试、排版与哈希见`../results/exp16/completion-verification.json`。
