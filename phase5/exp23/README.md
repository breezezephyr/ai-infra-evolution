# exp23：草稿和回放到底少了什么工作

2026-10-26，CPU教学重放＋固定源码配置/参考函数隔离。未执行DeepInfer引擎、模型推理或GPU。

- [设计](设计.md)、[源码对应](源码笔记.md)、[结论](../results/exp23-结论.md)、[P5·5正文](../../24-Phase5·5-少跑几圈/正文.md)。
- [240条教学重放摘要](../results/exp23/formal-v2/summary.json)、[冻结计划](../results/exp23/formal-v2/plan.json)、[完整逐轮账本](../results/exp23/formal-v2/replays.json)、[99窗口案例](../results/exp23/formal-v2/window-cases.json)。
- [源码探针摘要](../results/exp23/source-probes-v1/summary.json)、[16配置记录](../results/exp23/source-probes-v1/config-records.json)、[5216参考可见域行](../results/exp23/source-probes-v1/reference-visible.json)、[3次pivot展开](../results/exp23/source-probes-v1/pivot-reference.json)。
- [DSpark固定文件清单（第三方依赖需恢复，未随仓库收录）](../../docs/THIRD_PARTY.md)、[SWA固定文件清单（第三方依赖需恢复，未随仓库收录）](../../docs/THIRD_PARTY.md)、[独立审校](../results/exp23/independent-review.json)。两份清单有重合，不能相加当唯一文件数。

## 复核

在系列根目录执行，Python3.12；无新增依赖、网络或GPU需求：

```bash
phase5/.venv-exp19/bin/python -B -m pytest -q phase5/exp23/test_replay.py phase5/exp23/test_window.py phase5/exp23/test_source.py phase5/exp23/test_audit.py
/tmp/exp14-local-env/bin/python -B phase5/exp23/plot.py
```

本轮初轮54项、最终62项通过。正式目录已有证据，不可覆盖；新重放必须选择不存在的目录：

```bash
phase5/.venv-exp19/bin/python -B phase5/exp23/run.py --out phase5/results/exp23/replay-unique
phase5/.venv-exp19/bin/python -B phase5/exp23/source_probes.py --out phase5/results/exp23/source-probes-unique
```

两条命令写各自plan与执行代码SHA256后开始探针；重放是同一合成数据的确定性重算，不形成新的模型样本。图像使用正式formal-v2，另列16整数教学例由单测覆盖、不混入99分母。

## 验收分层

A：8类轨迹×2长度×3成本×5策略240条，最终提交均等于oracle目标；最终1920项重复声明检查。候选策略为本实验固定product阈值0.8，不是DSpark全批验证预算算法。教学草稿成本按选定起草长度计，不能套给最大D生成的DFlash。无实际p/q采样、真实时延或质量评价。

B源码：原样执行environ解析器，替换其os引用为受控getenv；每例新模块。AST只提取load_model的局部断言块和官方示例参考函数，不调用模型加载，不导入DeepInfer/Torch或编译扩展。16配置7通过/5断言拒绝/4解析拒绝，10形状5216参考行、3pivot和1缓存控制。没有执行完整L1、C++metadata或真实模型等价验证。

B教学：99个分层整数求和案例，裁剪两表示99相同、完整历史54相同、18单窗已覆盖仍不同。不是attention或DeepInfer仿真，不把玩具依赖公式写成真实模型条件。源码的K≥W+B来自固定版本，B=max(raw_B,nextn+1)；所有其他运行前提另列。

没有远端资源启动或清理动作，没有公众号上传。P5·4、P5·5均本地稿；前三篇此前已上传草稿箱并回读，未群发。

独立审校发现记录器门禁与失败汇总不足，已补齐读回计划、快照执行、逐轮独立计费/策略校验和有效配对分母。原formal-v1完整保留，formal-v2使用同一冻结科学输入，240条输出/轮次/成本一致，不增加独立样本数；原始审校与修复证据分别保留，未宣称审校者重审修复代码。见[审校修复](../results/exp23/review-resolution.json)。
