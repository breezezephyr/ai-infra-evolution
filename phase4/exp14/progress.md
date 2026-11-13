# Execution ledger — plan: phase4/exp14/实施计划.md

2026-10-22：用户批准设计并授权继续实现与GPU实测。

- Ruling: 当前目录无Git仓库，直接在既有实验目录实现并保存哈希/回执；不创建无意义worktree或提交，不删除执行记录。代价：用文件哈希追溯，无法使用Git回滚。
- Ruling: 沿用用户对实现与实测的明确授权，主线当前会话执行、两个不相互写入的模块并行委派，完成后统一审阅；不再为同一授权设置额外计划确认。代价：常规实现选择由执行者负责。
- Task1 协议与功能测试：并行实现中。
- Task2 输入与音频生成：并行实现中。
- Task3 远端独立venv准备与依赖安装：进行中；既有环境包路径只读复用，安装写入新venv。
- 逻辑测试：端点/分句/CER/重复取消6项 RED→GREEN；音频边界3项 RED→GREEN。
- 依赖安装首轮失败：运行时torch.__version__=2.6.0+cu124，distribution元数据为2.6.0；约束改用元数据版本，保留原CUDA运行时，不升级Torch。
- Task1 complete：协议32项测试通过。Task2 complete：12条Tingting音频，15项功能测试通过，音频1.40–8.14秒。
- Task3：新venv依赖安装通过；两个新模型已下载固定revision并记录哈希；ASR/LLM/TTS分别CUDA实跑及三模型常驻通过。共驻加载2173MiB、固定组件样例观测峰值2711MiB；原始结果在远端 results/components/，待最终同步。
- 组件样例热身后的ASR约70ms、LLM首文本约40ms、TTS首PCM约60ms；不合并为回合时延。
- Task4 首轮3条真实回合失败，保留远端 results/live-smoke/ 与 results/server/。根因：TextIteratorStreamer自然结束时生成线程仍在收尾，finally误设共享停止事件并取消TTS。新增两项真实线程边界回归，RED→GREEN；仅放弃流时才设stop，正常耗尽先join。准备修复后重跑。
- Task5：浏览器播放器、分析/图表在独立写入范围并行开发。

- 修复后就绪探测再跑3条A/B/C，均stop且输出62400样本。此前有3条连接探测赶在服务就绪前，另存live-smoke-fixed，不混入正式数据。
- 正式运行：远端 /opt/p4/exp14/results/live-final-v1，3条热身+108条，开始前保存 source-manifest-live-v1.json。server PID72434，loopback18144；GPU采样gpu-samples-fixed.jsonl。
- 既有vLLM环境232个distribution名称/版本与安装前一致；固定revision下载和运行源代码快照已保存在远端。
- 分析口径补充：尾静音会影响ASR标点/后续回答，需按case+repeat检查配对文本一致性；分句会改变合成时长。中文前端默认缺English G2P，Latin片段可能被省略，原始回答保留，列为质量局限而非静默声称全部读出。
- Task4 正式完成108条+3热身，全部stop；A/B/C提前端点6/9/9，每模式分母36。111条输入输出hash全部一致、所有模型线程收拢。浏览器初次3条各62400样本均实际消费，无欠载；采集、渲染、设备估计不同，声学首声未知。
- Final review Important：消费端判空与生产者最后入队/完成标志存在EOF竞态。实际111条+3条浏览器逐条核对生成/接收样本数，均相等，无本批尾包丢失证据；原始运行代码快照保留。确定性交错回归复现960生成→480下发，修复为完成标志后再次确认队列为空，新增生成/下发总数一致性保护；回归RED→GREEN。修复后补跑3条GPU及3条浏览器，不覆盖或混入108条正式数据。
- Final minor (documented): 历史组件tts.total_ms含PCM转换/WAV落盘，保留原始值并在README/结论明确口径；主要指标first_pcm_ms不受影响，不将total称纯模型耗时。
- Ruling: 显存保护与观测采用整卡已用量，包含桌面/其他进程基线，不称精确进程峰值；可覆盖Torch allocator之外的CTranslate2分配，但不能做单进程归因。正式批次整卡观测峰值3191MiB，结束后342MiB。
- Task5 complete：当前代码83项Python测试、32项播放测试通过；EOF修复后3条GPU及3条浏览器均完整生成/下发/消费62400样本，B浏览器额外欠载32样本(1.3ms)，其余0；声学首声仍未知。最终浏览器仅使用server-eof-fixed，旧批次保留诊断。
- 资源清理：实验server PID79142已退出，监控随之结束，gpu-router active。已停止本机专用SSH转发PID28980，等待最终端口读回核验。
- Final verification：正式/复验数据、两版源码哈希、GPU/播放样本总数、截图、83+32测试日志核对通过；本机18144转发与远端18144实验端口均已实际探测关闭。完成回执见 results/exp14/completion-verification.json。
