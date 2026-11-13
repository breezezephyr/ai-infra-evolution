# exp28：Kaggle 图片 API 的一张图片交付验证

日期：2026-11-09。目标是给既有 P5 系列增加独立、可复现的真实后端证据。继承的资源与用法见[本地交接材料（未收录：本地材料）](../../docs/PRIVACY.md)。

当前状态：公网健康检查实际返回 **404 / No interface is running**；本轮生成请求 **0**，新 GPU 生图样本 **0**。Notebook 诊断单元没有取得执行结果，不能据此声称本地 API 已恢复或硬件快照已采集。需要恢复分享入口后继续。

- [结论—验证项目—后端要求](结论映射与写作建议.md)
- [本轮结论与限制](../results/exp28-补充结论.md)
- [当前独立 run](../results/exp28/exp28-kaggle-20261109-ef35f831/)
- [本机验证脚本](run.py)、[CPU 记录器检查](test_evidence.py)
- [Notebook 诊断代码](notebook-diagnostic.py)：仅在新增单元中执行，不运行原模型加载单元。

## 实验边界

串行、最多一张 512×512 图片、8 步、seed 20261109，不改模型、不重启会话、不施加并发压力、不主动触发超时、不自动重试。四条合约请求分别为无鉴权、错误鉴权、steps=7、合法 steps=8。实际 HTTP 响应与后端执行数量分别保存，不根据状态码推算 GPU 尝试数。

密钥仅运行时从 `~/.config/qwen-image-kaggle/access.json` 读取，要求权限 0600；不放入命令行、日志、截图、文章或归档。脚本拒绝跨站重定向和带 userinfo/query 的 base URL。响应正文检测到密钥就拒绝归档，允许保存的响应头也进行遮蔽。

## 恢复后复现

在现有 Notebook 中先确认没有正在生成的任务，检查本地 `/health` 和 Gradio 分享隧道。优先只恢复 API 分享，保留已加载模型和同一密钥；不要直接 Run All、Stop session 或重新下载模型。浏览器执行通道此次报错，未能代替用户完成该步骤。

只更新私有连接配置中的 `base_url`，保留 `api_key` 和 0600 权限。不要通过聊天发送密钥。新地址先做只读检查：

```bash
cd .
/opt/homebrew/opt/python@3.12/bin/python3.12 phase5/exp28/run.py \
  --run-dir phase5/results/exp28/exp28-kaggle-20261109-ef35f831
```

确认健康且资源允许后执行四条受控用例：

```bash
/opt/homebrew/opt/python@3.12/bin/python3.12 phase5/exp28/run.py \
  --run-dir phase5/results/exp28/exp28-kaggle-20261109-ef35f831 --execute
```

`--execute`最多提交一次合法生成。提交前持久化防重复标记；发生超时或未知结果后，同一 run 拒绝再次提交。恢复之前的健康探测留在独立请求子目录，不删掉失败记录。

本机 Python 3.12.10 / Pillow 12.2.0 已验证。注意本机有多个 Python，不同终端工作目录的 `python3` 曾解析到缺少 Pillow 的 3.14；上面使用本次测试通过的解释器绝对路径。

## 核验与证据

原始请求体与 SHA256、无凭证的请求元数据、原始响应字节、响应哈希、允许保存的响应头和客户端阶段计时均按请求存储。成功时再严格解码 Base64，独立验证 PNG、完整加载、512×512尺寸、保存后字节及哈希相等。内容要求须查看图片后单列验收。

取得后端证据时，应补齐：实际 `nvidia-smi`、依赖/源码快照、模型 revision/放置、该次执行记录和原始 PNG/参数文件。现有 Notebook 的生成函数会打印保存路径，并把 PNG/JSON写到 `/kaggle/working/qwen-image-output`；按 prompt/seed/steps 与 PNG 哈希关联，不能用本机自建 request ID 冒充服务端关联。

客户端时间分为响应头、响应体读取、Base64解码、图片验证、文件写入与读回。服务端自报时长另列；纯 pipeline、排队、网络单独耗时没有打点就保留 unknown。模型已驻留不等于测过冷启动。

离线检查明确是 CPU 合成输入，不计入 GPU 样本：

```bash
/opt/homebrew/opt/python@3.12/bin/python3.12 -m unittest discover \
  -s phase5/exp28 -p test_evidence.py -v
```

15项检查覆盖错误图片、metadata不匹配、失效健康检查不得生成、禁止重复提交、禁止跨站重定向、密钥反射归档和旧失败摘要保留。已有九篇草稿和原始实验留在旧目录，本次没有重新上传或群发。
