# exp27：用同批记录验收体验与资源

[设计](设计.md)、[进度与决策](进度.md)、[能力与迁移清单](能力与迁移清单.md)、[结论](../results/exp27-结论.md)、[正式摘要](../results/exp27/formal-v2/summary.json)、[本地贡献候选](contribution/候选说明.md)。

本地CPU检查（不调用GPU）：

```bash
phase5/.venv-exp25/bin/python -m pytest phase5/exp27/test_gateway.py phase5/exp27/test_analyze.py phase5/exp27/test_run.py -q
phase5/.venv-exp19/bin/python -B phase5/exp27/contribution/verify.py
```

两组依赖环境分别保留。贡献验证会在自己的目录重建可丢弃patched-upstream副本，不修改旧vendor；原库编码与合成context参数、GPU实验是不同分母。

GPU复现需要Linux、已有vLLM0.8.5/Torch2.6/transformers4.51.3环境与`/opt/models/Qwen3-0.6B`文件；精确模型hash在正式model-identity.json。当前revision来源未知处为null。`/opt/p2/stub`是原环境兼容依赖，迁移者须先核对，不把本机可跑直接推定其他机器支持。

1. 检查GPU与8027/8127空闲，将本目录Python文件复制到新的隔离目录。
2. 执行运行器（新out必须不存在）：

```bash
/root/vllm-env/bin/python -B /opt/exp27-20261026-p5i/run.py --out /opt/exp27-20261026-p5i/reproduction-new
```

运行器先冻结计划和源码，再执行out/code/run.py；同一supervisor启动后端与网关，按42场景收集原始记录。finally只终止/回收自身进程组，保留cleanup/resources，独立审计失败以非0退出。首次失败formal-v1保留，最终只引用formal-v2，不能相加两轮样本。

模型服务进程区间、ready区间与wait4 CPU各自计量；精确权重/GPU kernel/货币实付未知。资源“并集”覆盖哪些组件在字段中声明，不把backend+gateway并集称模型独占时间。

离线审计：

```bash
phase5/.venv-exp25/bin/python phase5/exp27/analyze.py --out phase5/results/exp27/formal-v2
```

输入/计划/源码/模型身份、逐条客户端SSE、网关attempt和结算、独立原生HTTP与engine映射、资源清理均属验收必需。修改或缺失证据不自动降级通过。缓存来源的旧usage不重复记入当前生成；后端有计量而网关缺失时保留来源并拒绝成功汇总。

本接口只在loopback开放预定义实验场景和lab管理操作，合成Bearer不是真实鉴权产品。SLO是跑前冻结的实验门槛，固定整数题质量不能代表通用问答质量。

## 可移交材料包

[exp27复现包（未收录：原始归档）](../../docs/REPRODUCIBILITY.md)、[SHA256](../results/exp27/exp27-reproduce.tar.gz.sha256)、[逐文件清单](../results/exp27/bundle-manifest.json)。解包保留相对目录，从工作区根目录按本页步骤运行，另准备已列明的模型/环境依赖。包涵盖本轮源码、两轮冻结源/输入/raw、正文配图和贡献材料，不是整个系列的备份；没有附带模型权重或运行环境。

[运行清单](../results/exp27/运行清单.json)把失败首轮单列：25attempt的网关观测未完成独立对账，不能当零成本；最终770只是formal-v2已知小计，整个调试成本未知。


审校后离线修订在formal-v2/analysis-revision1：原生chunk重新拼接后与汇总对账，保留仍可见的usage；资源PID绑定实际服务启动及原生hook，缺启动证据拒绝通过。两重要项和Linux路径说明均修复，22项CPU通过，原正式指标未变。run.py支持EXP27_NVIDIA_SMI或PATH中的nvidia-smi，最后回退WSL路径；查询失败记null仍保存其他清理证据。此修改未新增GPU实跑，原执行code不改。

复现包解包CPU检查：`phase5/.venv-exp25/bin/python phase5/exp27/check_bundle.py`；[回读结果](../results/exp27/package-smoke.json)与归档SHA分开保存，避免自引用。Python解释器应保留venv启动路径，不把软链接解析成系统Python再运行。
