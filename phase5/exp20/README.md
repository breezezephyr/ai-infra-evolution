# exp20：分段、终态和工具调用

2026-10-23。实际调用recipe 0.2.0原生StreamProcessor及三协议generator/response；后端输出是固定fixture，本地SSE重放不启动HTTP服务。

## 复现

在系列根目录执行，复用exp19独立环境；无需GPU、权重或API密钥：

```bash
phase5/.venv-exp19/bin/python -B -m unittest discover -s phase5/exp20 -p 'test_*.py'
phase5/.venv-exp19/bin/python -B phase5/exp20/execute.py --out phase5/results/exp20/replay-01
phase5/.venv-exp19/bin/python -B phase5/exp20/analyze.py phase5/results/exp20/replay-01
```

输出目录必须尚不存在，禁止覆盖旧运行。首次环境安装与固定源码/tokenizer来源见[exp19 README](../exp19/README.md)。本轮加载前核对V4.1 tokenizer SHA256；正式运行保存代码/输入快照。wheel与源码commit分别登记，二进制构建commit未知。

上游单文件测试命令：

```bash
phase5/.venv-exp19/bin/python -B -m pytest -q \
  phase5/vendor/minimal/deepseek-recipe-python/tests/test_bindings.py \
  --junitxml=phase5/results/exp20/upstream-bindings-replay.xml
```

图形导出使用已有matplotlib环境：

```bash
/tmp/exp14-local-env/bin/python -B phase5/exp20/plot.py phase5/results/exp20/formal-v1
```

## 产物与分母

- [设计](设计.md)、[源码笔记](源码笔记.md)：固定调用链、来源和12组候选不变量；候选中未执行的子条件不计入本轮通过结论。
- `cases.json`：19个输入定义，11组主要语义输入＋2个usage对照＋6个生命周期/错误输入；展开为222条配置流。Text/Tokens各自切整体、单单元和混合大小；异常/usage额外行只使用所声明的模式。
- `stream_run.py`：真实原生流记录；Finish、EOF flush、close、parser stop与错误分别保留。错误只在指定原生探针调用中归为预期；观察/序列化/记录错误独立失败。
- `execute.py`：冻结计划合约、逐行验收、SSE重放、完整分母和来源快照。
- `transport.py`：本地UTF-8/SSE子集。严格UTF-8，不实现EventSource重连；不能将它的通过当作浏览器/代理/网络实测。
- `analyze.py`：原始usage和来源分列、工具参数增量与最终值并存，生成[CSV](../results/exp20/capability-matrix.csv)及[总摘要](../results/exp20-summary.json)。
- [正式结果](../results/exp20/formal-v1/summary.json)、[结论](../results/exp20-结论.md)、[P5·2正文](../../21-Phase5·2-广播分几段/正文.md)。

正式222条均符合冻结预期，2004项重复声明检查通过；666次字节重放复用这些流的事件。它们不是独立能力数、模型调用次数、成功回答率或服务性能测量。完整块与多块共用原生解析器及accumulate，不作为两个独立oracle。

程序的48项回归检查（25项记录器＋23项字节层）和上游bindings单文件48项测试使用独立分母，均0失败/跳过。上游测试包含本地临时图像HTTP服务；测试结束退出，无常驻服务。不能说上游全仓测试通过。

## 主要范围限制

没有执行工具、模型、DeepInfer、真实HTTP网关或取消传播。当前数据没有覆盖源码笔记里所有特殊token身份反例、未解完token尾部、重叠stop、JSON外围空格与全部continuation初态。参数schema是否执行留给exp21；网络/后端取消传播留给后续集成。

探索目录与`pilot-v1`保留，最终采用`formal-v1`，不累加为额外样本。程序异常、预期错误、主动放弃和未证实EOF均在原分母里，未当作模型自然完成。
