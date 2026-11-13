# exp16 · 插话与取消

真实 CUDA LLM / TTS + 浏览器 AudioWorklet。设计见 [设计.md](设计.md)，结果在 `../results/exp16-结论.md`。

- Qwen3-0.6B BF16、Kokoro-82M-v1.1-zh FP32 / zf_001，复用 exp14 已有固定本地权重和 `voice-env`，不修改旧实验代码或生产 gpu-router。
- 本轮不运行ASR/VAD，输入是固定识别后文字；触发为播放位置控制。无麦克风/AEC或声学回环结论。
- 贪心生成，首轮上限256 token，下一轮64 token，输入上限1024；最多12字符TTS段、24kHz PCM16LE、20ms包，不额外设置起播缓冲门槛，首帧入队后即可消费。服务端未确认样本上限48000（2秒）。不是WS与RTC对照。
- `server_only`仅停止上游与服务端普通音频；`full`再清本地queue并拒绝旧generation。已进入设备的音频不可由本实验声称收回。
- 最终计划：两策略×200/1000/4000ms播放点×3重复=18条，每条接第二轮实际生成/播放。另LLM文字可用/TTS调用开始后50ms各3次真实GPU取消探针。pilot不混最终统计。

## 运行

本地机制测试（假模型只用于测试，不记GPU数据）：

```sh
python3 -B -m unittest discover -s phase4/exp16 -p 'test_*.py'
node phase4/exp16/test_worklet.cjs
```

DARYU：只绑定loopback，新输出目录不得存在。

```sh
cd /opt/p4/exp16
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 /root/voice-env/bin/python -u server.py --port 18149 --output /opt/p4/exp16/results/formal-v1
```

代码需要相邻的 `/opt/p4/exp14/models.py` 和 `logic.py`。环境不新增依赖；无需ASR用的CTranslate2共享库设置。专用SSH隧道把本地18149转发到远端loopback18149，使用既有DARYU连接配置，不在文章写访问凭据。

```sh
python3 phase4/exp16/run_probes.py --output phase4/results/exp16/probes-formal-v1 --repeat 3
node phase4/exp16/run_browser.cjs --url http://127.0.0.1:18149 --output phase4/results/exp16/browser-smoke-v1 --mode smoke
node phase4/exp16/run_browser.cjs --url http://127.0.0.1:18149 --output phase4/results/exp16/browser-formal-v1 --mode formal --repeat 3
```

浏览器runner使用项目已安装的Playwright和本机Chrome；音频图确实运行，headless渲染不当作物理扬声器听感。保留每次失败及raw事件，输出目录不覆盖。

## 口径

- 浏览器停止：触发AudioWorklet帧→最后一个旧generation消费样本的结束帧，同一渲染时钟；主线程通知延迟另算。不是人声起音→听觉停止。
- 服务端停止：stop signal→真实线程join，同一server monotonic；最后普通音频发送不得晚于cancel。普通PCM和受控旧帧探针分开。
- TTS是调用返回后的合作式取消，不能中断当前CUDA kernel。调用开始50ms是调度边界，不保证已经进入GPU计算。
- 全部TTS波形计入computed_samples，取消后返回的波形计入discarded_after_stop_samples；已算出但未送出的队列还需单独看。
- 历史按segment音频end<=最终played保留整段文字；没有词级对齐，部分段保守舍弃。裁剪后的messages真正传给第二轮模型，提示与状态保留原始记录。
- GPU采样是整卡已用显存与利用率，不等于本进程峰值、活跃CUDA时间或精确成本。
- `stale_probe`在cancel后人为延后30ms发送480样本，只验证版本拒绝，不混入正常流、不冒充网络丢包。server_only忽略此控制探针；full经相同worklet入队通道拒绝。
