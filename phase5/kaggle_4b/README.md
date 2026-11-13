# Kaggle Qwen3-4B：exp25 / exp26 / exp27 完整场景移植

只包含代码与合成 CPU 测试，不含旧结果、凭据或模型权重。bootstrap.py 单独准备环境和模型，不发起生成。原 exp25/26/27 不修改。这里的 CPU 通过不是新 GPU 实验数据；不能据此替换公众号数字。

## Kaggle 用法

主流程先通过 uv 管理的 Python 3.11 准备 venv311 与本地模型；不使用 Kaggle base Python 3.13。要求 vLLM **0.8.5 V0**、GPU0 为 T4、原生 Qwen3-4B 三分片、FP16。模型架构检查为 Qwen3 / hidden_size=2560 / 36层，版本固定为 `1cfa9a7208912126459214e8b04321603b3df60c`。GPU1 不使用，tensor parallel=1，GPU utilization 默认 .85。

假设代码解包到 `/kaggle/working/kaggle_4b`，主 bootstrap 已写 `/kaggle/working/p5-4b-20261113/model-prepared.json`：

```bash
/kaggle/temp/p5-4b/venv311/bin/python -B /kaggle/working/kaggle_4b/run_suite.py \
  --out /kaggle/working/p5-4b-20261113/validation \
  --prepared /kaggle/working/p5-4b-20261113/model-prepared.json \
  --python /kaggle/temp/p5-4b/venv311/bin/python \
  --vllm-bin /kaggle/temp/p5-4b/venv311/bin/vllm
```

**OUT 必须不存在**。父目录可以由 bootstrap 创建；每次重跑换全新 OUT，例如 `validation-v2`。不用覆盖或清空旧运行。`--prepared` 读取 `repo,revision,model_path,files[{path,bytes,sha256}],packages`，离线检查全部列出的文件、权重 index 与三分片，然后把准备记录复制到本次 OUT。

也支持 `--model-path /actual/local/snapshot --model-revision REVISION`（`--model` 为别名）；这条路径仍检查实际模型配置与三分片，但没有 prepared 下载来源对账。默认模型路径为 `/kaggle/working/models/Qwen3-4B`，默认 HF_HOME 由主 bootstrap 配置为 `/kaggle/temp/p5-4b/hf`。代码设置模型离线加载；不联网补文件。

`--python` 在导入 torch/vLLM 前切换到指定解释器；`--vllm-bin` 指定实际 venv 可执行文件。可选 `--gpu-util`，默认 `.85`。底层配置为 `P5_MODEL_PATH`、`P5_MODEL_REVISION`、`P5_GPU_UTIL`、`P5_DTYPE`（只允许 float16/half）、`P5_VLLM_BIN`，以及 `P5_EXP25_ALIAS` / `P5_EXP26_ALIAS` / `P5_EXP27_ALIAS`。默认别名分别为 `exp25-qwen3-4b` 等。端口固定保留 8025/8125、8026/8126、8027/8127。

## 执行与证据

1. 冻结本次 `suite-source/`、源码 hash 和不含凭据的配置。
2. 顺序运行 exp25 的42请求、exp26 的17故障请求、exp27 的42联合验收请求。各轮 `formal/code/`、`plan.json`、`freeze.json` 在派发请求前冻结。
3. 原运行器保留逐请求客户端字节/SSE、网关账本、后端原始 HTTP、原生 usage 与未知项。exp26/27 的 `backend_audit.py` 与原版逐字节相同，仍钩住真实 vLLM V0 engine / RequestTracker / scheduler / abort。exp25 原版只做 HTTP 审计，保持这一证据边界。
4. 每套运行器调用其独立 analyzer；suite 在清理后再调用冻结的 analyzer，显式要求 `accepted=true`。exp26 仍是默认 `formal_native`，不使用 `http_fixture` 降级。exp27 的质量/SLO失败照实保留，不能把 evidence accepted 当作42条回答合格。
5. 失败立即停止，不进入下一实验；保留失败记录。只向本轮 Popen 所创建、尚未回收的进程/进程组发信号，不按端口或历史 PID 杀进程。SIGTERM/KeyboardInterrupt 走 finally 回收。已有端口占用直接拒绝运行。

exp25/26 的 backend 启动、全量原始日志、模型身份与最终 cleanup 在 `OUT/exp25/`、`OUT/exp26/`；正式计划与筛选/复制后的审计证据在其 `formal/`。exp27 的 backend、资源 wait4 统计与 cleanup 均在 `OUT/exp27/formal/`。总状态为 `OUT/suite-summary.json`。运行器日志和最终分析日志单列。

权重身份是**真实文件**的 `{path,bytes,sha256}` 有序 manifest；聚合 hash 为 canonical JSON(shards) 的 SHA256。模型 index 和 tokenizer/config 同时按真实文件留 hash。没有制造 `model.safetensors`，聚合值单列 `weights_sha256`，不冒充任意一个分片 hash。结束时重新读取实际文件验证未变化。

场景、预期终态、质量判据与跑前 SLO 沿用原实验；4B 不满足预期时本轮应失败，不能改阈值或复用旧测量。尤其原 exp25 含固定回答/门控预期，换模型后的行为需要实际验收。

## 本地 static / CPU checks

```bash
PYTHONDONTWRITEBYTECODE=1 python -B phase5/kaggle_4b/check_cpu.py
```

基础检查只需 stdlib 与 httpx（计划构造导入）；检查语法、无旧模型/系统路径、三套公共代码一致、原生 hooks 原样保留、分片损坏/缺失、prepared版本与文件 hash、默认 FP16/V0/GPU0/端口、旧 OUT 拒绝，以及 owned 子进程清理。运行 exp26 27项与 exp27 12项独立审计器 CPU 反例。若有 FastAPI，则额外执行 exp25 网关的10项 CPU检查；缺依赖明确 SKIP。

原 pytest 测试也保留（exp25 中依赖旧结果的测试未复制）：

```bash
# 在已具备 pytest/httpx/FastAPI 的环境中，各目录必须独立启动 pytest，避免同名模块冲突。
python -B -m pytest -q -p no:cacheprovider phase5/kaggle_4b/runtime/exp25
python -B -m pytest -q -p no:cacheprovider phase5/kaggle_4b/runtime/exp26
python -B -m pytest -q -p no:cacheprovider phase5/kaggle_4b/runtime/exp27
```

CPU fixture 的合成 token/hash 只用于破坏性审计测试，不是 GPU 测量。没有在本地执行安装、模型下载或 GPU 请求。

## 打包

```bash
python -B phase5/kaggle_4b/package.py
```

生成 `dist/kaggle_4b.tar.gz` 与 SHA256，包内有逐文件 manifest。显式白名单只打包 runtime Python、测试和本说明；不打包 bootstrap、checks临时目录、dist自身、结果或其他临时文件。已存在同名归档时拒绝覆盖。主流程可独立发布该目录并整合 bootstrap。

## 公开代码包

公开仓库提供 `code-bundle.json`，其中每个条目带相对路径、源码和 SHA-256；
Notebook 按固定 Git commit 下载并校验代码包后恢复到本地目录。
本机 dist 归档不随 Git 分发。

本地移植回归：三个独立 pytest 进程分别通过23、53、22项检查；
另有静态及分片、计划、进程清理、审计反例检查。CPU 结果不代替GPU验证。
