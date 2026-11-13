# exp24：数据放进Store，离可用KV还差什么

2026-10-26。真实Mooncake non-CUDA 0.3.13.post1；DARYU Linux x86_64 / Python3.12 / 配置TCP。无模型/GPU/真实P/D运行。

- [设计](设计.md)、[源码笔记](源码笔记.md)、[执行记录](执行记录.md)、[结论](../results/exp24-结论.md)、[P5·6正文](../../25-Phase5·6-行李不跟车走/正文.md)。
- 最终[formal-v3摘要](../results/exp24/formal-v3/summary.json)、[冻结计划](../results/exp24/formal-v3/plan.json)、[原始逐调用记录](../results/exp24/formal-v3/records.jsonl)、[独立逐项审计](../results/exp24/formal-v3/audit.json)、[清理](../results/exp24/formal-v3/cleanup.json)。
- [二进制身份](../results/exp24/preflight/binary-identity.json)、[固定源码清单（第三方依赖需恢复，未随仓库收录）](../../docs/THIRD_PARTY.md)、[12个身份合约案例](../results/exp24/identity-v1/summary.json)、[P3预算复核](../results/exp24/preflight/p3-budget-recheck.json)。
- [原始记录器审校](../results/exp24/recorder-review.json)及[修复记录](../results/exp24/review-resolution.json)单列，不以原始审校替代修复后的复核。

## 复核现有记录

系列根目录运行，无需连接DARYU或安装Mooncake：

```bash
phase5/.venv-exp19/bin/python -B -m pytest -q phase5/exp24/test_audit.py phase5/exp24/test_identity.py
phase5/.venv-exp19/bin/python -B phase5/results/exp24/formal-v3/code/summarize.py --out phase5/results/exp24/formal-v3
phase5/.venv-exp19/bin/python -B phase5/exp24/run_identity.py
/tmp/exp14-local-env/bin/python -B phase5/exp24/plot.py
```

摘要命令仅从冻结计划和原始记录重建summary；不新增实验样本。先保留现有文件即可用独立目录复核。测试覆盖字节检查、失败/缺失分母、请求/进程/计划关联、计时无效值、失败退出，以及严格身份字段和复用门禁。

## 新做一次真实Store运行

需要Linux、Python3.12、足够内存及可加载的原生依赖。不要改动已有vLLM环境。`verify_install.py`根据[wheel身份输入](wheel-identity-input.json)核对官方wheel和已安装原生文件；源码commit不当作wheel构建身份。DARYU的依赖解包在独立runtime目录。

在新的隔离目录准备venv、固定wheel与依赖，复制本目录的freeze.py / runner.py / worker.py / audit.py / summarize.py，然后使用该venv：

```bash
python -B freeze.py --out /absolute/new-output-directory
```

输出目录必须不存在；预检50240、9024及50241–50243，拒绝抢占。plan.json写出后读回，实际运行code/快照并核对SHA256。master与client在finally收拢；25秒操作超时保留为失败，验收失败退出非零。force删除只用于本轮串行清理，不验证租约并发安全。

主对象为1B、4KiB、64KiB、1MiB各10个。A贡献128MiB存储段；B贡献0、使用32MiB本地缓冲区。A写、B读，逐个核对长度/hash；C用于重启后的新client观察。配置TCP且跨进程，但没有逐次载荷分支/socket字节跟踪，不能报告纯TCP带宽。每档仅10个串行时延样本，描述中位/最小/最大，不报告稳定p99或容量。

formal-v1为同进程预跑，put计时含生成payload；formal-v2改为跨进程，计时范围修正。formal-v3补齐请求摘要、worker PID/计划/代码绑定、失败退出与统一计时过滤，是本篇最终引用版本。旧记录完整保留，不能把三轮对象数合并为本篇120个样本。

身份合约独立于Store实验：精确全前缀相等、合成版本/租户/布局等元数据；两个布尔门禁是调用方声明，不是已运行的KV导入器、认证或Store ACL。
