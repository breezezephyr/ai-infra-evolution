# exp19：请求转换与编码合约

2026-10-23完成。实际执行 `deepseek-recipe==0.2.0` macOS ARM64原生wheel，使用固定源码内V4/V4.1 tokenizer；无模型推理、工具执行或在线API服务。

正式结果：[formal-v2](../results/exp19/formal-v2/summary.json)，36条输入，27条转换接受、9条按预期拒绝，211项声明检查通过，失败/未知均为0。检查点存在重复，不代表211种独立能力。详见[实验结论](../results/exp19-结论.md)。

## 复现

在系列根目录执行。依赖安装进独立环境，不修改旧网关或语音实验环境：

```bash
python3.12 -m venv phase5/.venv-exp19
phase5/.venv-exp19/bin/python -m pip install 'deepseek-recipe==0.2.0' 'pytest==8.4.2'
phase5/.venv-exp19/bin/python -B -m unittest discover -s phase5/exp19 -p 'test_*.py'
phase5/.venv-exp19/bin/python -B phase5/exp19/run.py \
  --tokenizer-root phase5/vendor/minimal/static/tokenizers \
  --out phase5/results/exp19/replay-01
phase5/.venv-exp19/bin/python -B phase5/exp19/analyze.py phase5/results/exp19/replay-01
```

输出目录必须尚不存在；每次运行单独保留。`analyze.py`会更新总摘要及CSV，原始运行目录不变。tokenizer下载身份见[provenance（第三方依赖需恢复，未随仓库收录）](../../docs/THIRD_PARTY.md)，加载前逐份核对SHA256；缺失/错误不会伪装成转换器拒绝。官方wheel及原生扩展身份见[environment.json](../results/exp19/environment.json)。

源文件固定到 `935817c66f5d6e64838f419692545f06787e485f`，选取文件及Git blob/文件哈希在[source-metadata.json（第三方依赖需恢复，未随仓库收录）](../../docs/THIRD_PARTY.md)。本地保留的是所选源码和tokenizer，未取得完整源码归档。阅读commit与发行wheel分别记录，未证明native二进制的构建commit。

上游测试复现命令（48项均运行，包括该文件内的本地临时图像服务测试；不是整个上游测试仓库）：

```bash
phase5/.venv-exp19/bin/python -B -m pytest -q \
  phase5/vendor/minimal/deepseek-recipe-python/tests/test_bindings.py \
  --junitxml=phase5/results/exp19/upstream-bindings-replay.xml
```

## 文件与记录

- `cases.json`：36条冻结用例、预期值与声明检查；[fixture-notes.md](fixture-notes.md)解释依据。
- [源码笔记](源码笔记.md)：从三协议请求到ConversationRequest、编码和预算函数的真实接口链。
- `run.py`：真实转换、序列化快照、prompt/区间、token IDs、上下文探针和同族比较。
- `audit.py`：绑定完整用例合约摘要，统计通过/失败/未知，拒绝重复ID与检查名。
- `test_*.py`：16项回归检查，包括未记录、契约变化、探针异常和版本错误等失败路径。
- `analyze.py`：重核来源快照，生成[CSV矩阵](../results/exp19/capability-matrix.csv)与[总摘要](../results/exp19-summary.json)。
- `plot.py`：导出文章配图；仅展示输入组成与本轮观察，不统计服务吞吐。

`formal-v2/provenance/`保存运行时代码和输入快照；逐用例记录含完整case合约摘要。错误按转换、导出/观测、编码与预算阶段保留。记录器回归检查与正式211项检查使用不同分母。

历史目录保留：`conversion-probe-v1`为枚举序列化失败；`conversion-probe-v2`缺tokenizer、后续项未知；`formal-v1`为首轮成功结果。最终文章和矩阵采用修补记录器后的`formal-v2`。这些运行不混合累加为更多样本。

## 能证明什么

证明本次库与固定输入的转换、编码和预算函数行为。未执行DeepInfer，没有模型回答、约束采样、联网搜索、实际工具、SSE传输、GPU容量或线上服务兼容结论。正式主实验无常驻服务，上游bindings测试的本地临时服务已随测试退出。
