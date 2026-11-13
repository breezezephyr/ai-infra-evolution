# exp29：独立 Kaggle 文本模型接口验证

本轮使用新 Notebook：[P5 Infra - Qwen3 GPU Evidence](https://www.kaggle.com/code/example/experiment-notebook)。目标模型由 Qwen3-0.6B 调整为 **Qwen/Qwen3-4B，FP16**。旧 Qwen Image Notebook 和 exp28 的失败记录保留。

## 设计边界

- Transformers `generate`，单 GPU0 明确放置；平台配置为 T4 x2，第二块卡不代表模型自动跨卡。
- 本机环回 HTTP 服务，不建立公网隧道。
- 串行执行 5 个 HTTP 用例，最多 3 次生成，输出 token 上限合计 65。
- 用例依次为模型名拒绝、参数上限拒绝、普通生成、同提示词流式生成、单 token 上限生成。
- 保存请求和响应原文、SSE 接收字节及时间、模型原生 token ID、实际依赖与模型版本、GPU 内存观测。
- 客户端首个非空内容延迟与服务端生成耗时分开统计；不把 HTTP 响应头时间当作首 token 时间。
- 不从这一轮推导生产吞吐、并发容量、质量、计费精度、KV Cache、连续批处理或高可用结论。

`bootstrap.py` 只安装依赖、下载并校验模型，不触发生成。实验是否完成，以结果目录中的真实请求记录和总结为准。

## 文件与执行

- `active-run.json`：本轮标识和 Notebook 地址。
- `bootstrap.py`：Kaggle 首个准备单元。
- `experiment.py`：实验服务端、客户端和采集器。
- `test_sse.py`：CPU 增量 SSE 协议测试；通过不等于 GPU 实验通过。

原始结果归档目录：`phase5/results/exp29/exp29-kaggle-20261110-a74160a0/`。

此实验不会自动更新公众号草稿或进行群发。

## 本轮结果（2026-11-10）

已完成 5/5 用例、3 次真实 GPU 生成，原生输出共 41 token。模型实际全部放在 GPU0，FP16；加载后 allocated 7.545 GiB，本进程观测峰值 7.561 GiB。两条拒绝请求均没有进入生成。普通/流式正文及原生输出 ID 在本轮相同，流式 finish、usage 和 `[DONE]` 完整。

原始归档 44 个文件的 hash、本地 HTTP 分片拼回及 token 对账通过；Kaggle Quick Save Version #1 成功。详见[补充结论](../results/exp29-补充结论.md)和[本地回读](../results/exp29/local-readback.json)。这不是质量或容量基准。

`p5-qwen3-4b-exp29.ipynb` 为自包含复现文件；`package_notebook.py` 从本地源码生成该文件。执行单元使用持久标记防止同一结果目录重复生成；即便失败也不会自动删除标记重跑。

本地证据核验：`python3 phase5/exp29/verify_readback.py phase5/results/exp29/exp29-kaggle-20261110-a74160a0`。该步骤只读已下载的结果，不调用 GPU 或网络。

## 公众号草稿跟进

2026-11-10随后按用户要求，P5·7～P5·9各增加一段独立补验并原位更新草稿，未群发。分别解释入口拒绝与原生计量、正常流收尾、跨环境交班；没有改写exp25～27的旧数字或合并样本。见[更新回执（未收录：发布或账号材料）](../../docs/PRIVACY.md)。实验阶段的 `active-run.json` 和原始归档保留当时的状态；草稿修改另行记录。
