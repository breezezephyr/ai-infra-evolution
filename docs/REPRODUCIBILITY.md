# 复现与证据边界

本仓库是脱敏整理的公开副本。本次整理没有重跑 GPU 实验，没有执行上游代码，
也没有重新测量历史性能。历史结果仍对应当时记录的输入、环境和原始采集文件。
源码分析以恢复清单中核对的固定 commit 与文件 SHA-256 为准，不推断为 wheel 构建版本。

## 源码恢复

在仓库根目录运行，使用 Python 3 标准库；安全文件操作需要 POSIX 的目录描述符和
`O_NOFOLLOW` 支持（如 macOS/Linux）。

```sh
python3 tools/restore_upstream.py
python3 tools/restore_upstream.py --verify
python3 tools/restore_upstream.py --download
python3 tools/restore_upstream.py --verify
```

默认是离线 dry-run，只打印目标的 `OK`、`MISSING` 或 `MISMATCH`，不联网、不创建目录。
`--verify` 离线校验全部恢复目标的 SHA-256 与字节数；缺失或不匹配时退出码为 1。
只有显式 `--download` 才联网，跳过已有且匹配的文件，下载缺失或不匹配的文件。
两种选项互斥。默认 dry-run 成功退出为 0；清单、路径、安全检查或下载出错为 2。

下载仅允许 `raw.githubusercontent.com`、`github.com`、`api.github.com` 的 HTTPS URL，
包含固定完整 commit SHA，不携带用户认证、query 或 fragment；每次重定向再次检查。
不继承代理配置、Cookie 或认证处理器。所有目标先检查，再进行下载；目标仅能位于
`phase5/vendor/` 内，拒绝绝对路径、traversal、symlink 和非普通目标文件。
目录描述符与 `O_NOFOLLOW` 用于防止跟随目标路径中的 symlink。

下载先写同目录独占临时文件，限制读取字节数，核对 bytes 与 SHA-256 后才原子替换。
失败时清理临时文件；不匹配内容不会覆盖现有目标。原子性针对单个文件，不是整批事务；
中途失败时，之前已验证成功的文件可以保留。CLI 不安装依赖、不解压、不导入或执行上游代码。

网络清单包含 108 个目标，共 15,911,843 字节，恢复范围包括固定源码切片、许可证和两份
有 URL/哈希的 tokenizer JSON。它不是完整 checkout，也不恢复 wheel 或权重。
`tools/upstream-metadata/` 保留九份脱敏来源记录和许可证核对记录。
历史失败下载保留为失败证据，不宣称恢复成功。

## 哈希与可复现性

原实验记录中的哈希属于原始采集文件。脱敏、路径替换或 JSON 重新序列化会改变字节与
哈希；原哈希不能用于校验公开脱敏副本。恢复清单中的哈希则用于验证未经改写的上游文件。

公开新副本的哈希清单由最终导出流程生成于 `docs/public-manifest.json`，排除清单自身和
`.git` 目录，不含私有源路径或排除列表。公开审查摘要见最终生成的 `docs/RELEASE-AUDIT.md`。
这些文件可能晚于本说明生成；它们不证明历史测量已重跑。

native 0.2.0 wheel 的 build commit 未知，不能由相同 stub 或源码 commit 推断其来源。
恢复源码成功只证明下载字节与清单一致，不证明能构建、能运行或能复现 GPU 性能。
上游不可用、硬件、驱动、依赖和输入差异仍可能影响复现。

## 未分发材料

不打包 vendor/tokenizer/wheel/weights。显式下载的文件留在本地恢复目录。
音频省略总数为 445（435 WAV + `phase4/results/exp15` 的 10 PCM），原因是
macOS/Kokoro 音色输出分发许可尚未确认；保留输入文本、哈希、指标和来源，不声称可恢复
全部音频字节。exp29 的 10 个 `.bin` 是文本 HTTP 请求与响应，予以保留。

## 本地 metadata 恢复

exp21 的 `cpu.py`、exp24 的 `check_artifacts.py` 和 exp27 的 `contribution/repro.py`
直接读取原 vendor 路径下的来源 JSON。恢复清单因此另列 `local_metadata` 九项：
从 `tools/upstream-metadata/` 复制脱敏 JSON 到原 `phase5/vendor/` 相对路径，
不联网。108 个外部网络目标及其字节数保持不变，本地 metadata 单独统计。

默认 dry-run 不复制；只有 `--download` 显式复制，并复用网络文件的安全路径检查、
固定 bytes/SHA-256 校验及临时文件原子替换。`--verify` 离线校验九个恢复目标；
所有模式也核对 tools 内的本地来源文件。CLI 分别输出 NETWORK 和 LOCAL-METADATA 统计。
这九项的哈希属于脱敏 JSON，不是私有原始 metadata 的历史哈希。

此操作仅补齐 metadata 路径依赖。exp21 仍依赖未打包的 wheel，其他运行环境、发布材料等
依赖也需独立准备；不保证完整实验直接可运行，不代表任何实验已经重跑。
