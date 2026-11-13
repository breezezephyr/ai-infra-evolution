# exp18：一分钟怎么算

2026-10-23。重算 exp14～17 的原始事件，给出测量字段合约，并补一段 ASR+LLM CUDA 常驻观测。不是生产联合 SLO、并发容量或实际账单测试。

## 本地重放

在 essay 根目录：

```bash
python3 -B -m unittest discover -s phase4/exp18 -p 'test_*.py'
python3 -B phase4/exp18/analyze.py
/tmp/exp14-local-env/bin/python phase4/exp18/plot.py
```

离线账本只用 Python 标准库；绘图需要 matplotlib 和本机 Heiti TC 字体。`analyze.py` 读取原始记录并记录 SHA256，不调用旧 summary 复制指标，不发模型请求。

- `experience.py`：exp14/15，完整端点、首 PCM、浏览器渲染、媒体统计、排空。
- `interruption.py`：exp16，浏览器帧位置、服务端停止到 join、旧轮隔离、新轮完整播放。
- `accounting.py`：exp17，输入/回合/常驻分钟、累计 ASR 前缀、选用与废弃 token；校验冻结 WAV 和插入静音。
- `metric-contract.json`：每项的适用分母、起终点、时钟、单位和未知项；生产目标比例、窗口及联合实测均未填。
- `plot.py`：独立可导出的 `phase4/img/exp18.png`，复制到正文图片并核对哈希。

## 新增 GPU 补测

已完成路径：DARYU `/opt/p4/exp18/results/idle-v1/idle.json`，本地 `phase4/results/exp18/idle-v1/idle.json`。

只在已经存在的 `/root/voice-env` 中运行；使用冻结 faster-whisper-small CUDA INT8/FP16、Qwen3-0.6B CUDA BF16。没有安装依赖、启动服务或建立隧道。

```bash
# 如需人工重跑，必须用全新的 --out 目录；脚本拒绝覆盖已有结果。
bash /opt/p4/exp18/launch.sh --out /opt/p4/exp18/results/NEW_RUN_NAME --seconds 10
```

新增 ASR、LLM 热身各一次；同步后本实验不再提交新请求。37 次采样覆盖实际 10.389 秒窗口，全卡显存均为 1933 MiB；首个利用率读数 40%，其后 36 次 0%。逐次记录 nvidia-smi 命令的开始/结束，末次查询跨越计划截止点，因此真实窗口略长于 10 秒。利用率不是精确 CUDA kernel 时间；也没有排除其他进程使用 GPU。

结束后另一次 SSH 核对：本脚本精确 argv 的进程为 0，gpu-router active，全卡显存 342/8188 MiB、利用率 0%。见 `cleanup.json`。原始模型/venv 保留。没有新增后台任务需清理。

## 输出及边界

三个 audit JSON 及输入哈希位于 `phase4/results/exp18/`，总汇位于 `phase4/results/exp18-summary.json`，中文结论在 `phase4/results/exp18-结论.md`。

所有百分位使用线性插值，并保留测量数。小样本、受控回放、不同试验路径不能拼成生产会话成功率。首包不是声学首声；渲染尾巴不是人耳停止；生成 EOS 也在 token 计数内；采用的 generation 没有自动通过语义质量验收。

GPU 常驻按同卡区间并集计。正式批次 232.190973 秒，仅覆盖正式回合，载入/热身/窗口外等待均不含。36 个回合窗口合计 230.781056 秒；输入音频 205.38 秒，其中明确插入的全零静音 42.57 秒，不能视作无请求时长。

真实会话分钟、声学输出、精确 GPU 活跃秒数、其他资源成本、实际账单均为未知。R=2 元／GPU·小时只是自定演算费率，0.03354 元／实验回合分钟不是实际上线价格。
