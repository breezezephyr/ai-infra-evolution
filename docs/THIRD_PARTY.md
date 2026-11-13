# 第三方材料

本仓库不打包 phase5/vendor、tokenizer、wheel 或模型权重。来源记录经脱敏保留在
`tools/upstream-metadata/`；`tools/upstream-sources.json` 提供固定源码切片的恢复清单。
恢复文件不因进入本项目而改用本项目原创代码或文章的许可。

| 上游 | 固定 commit | 许可 |
| --- | --- | --- |
| [deepseek-recipe](https://github.com/deepseek-ai/deepseek-recipe) | `935817c66f5d6e64838f419692545f06787e485f` | MIT |
| [DeepInfer](https://github.com/deepseek-ai/DeepInfer) | `9bd9cf243fc53ef9afbf8f04d391d989117d6ab9` | Apache-2.0 |
| [Mooncake](https://github.com/kvcache-ai/Mooncake) | `c67a88f381f69e869045f353539e90c76e738830` | Apache-2.0 |

许可证于 2026-11-13 按上述 commit 的原始字节核对：deepseek-recipe 和 DeepInfer 的
文件名为 `LICENSE`，Mooncake 为 `LICENSE-APACHE`。
URL、SHA-256、字节数和核对范围见 `tools/upstream-metadata/license-verification.json`。
deepseek-recipe 的 MIT 原文另存于 `LICENSES/DeepSeek-Recipe-MIT.txt`，与采集副本逐字节一致。
恢复清单也包含各源码切片对应的上游许可证；具体文件自带的版权与许可声明继续适用。

## 恢复边界

网络清单包含 108 个恢复目标（含许可证和两份 tokenizer JSON），总计 15,911,843 字节。
每项固定 HTTPS URL、SHA-256 和字节数；不下载完整仓库，不执行、安装或编译上游代码。
原始 metadata 中的三条失败采集记录仅作历史证据，不列为可恢复文件。
跨实验复用的缓存按内容哈希匹配回原路径，不把上游路径直接当成本地目标路径。

`deepseek-recipe==0.2.0` 的 native wheel build commit 未知。stub 与固定源码字节相同，
只能证明 stub 身份，不能证明原生二进制来自该 commit；wheel 不打包、不自动恢复。
Mooncake 源码版本与历史运行 wheel 版本也不能据此视为相同构建。

445 个音频文件不再分发：435 WAV，以及 `phase4/results/exp15` 的 10 PCM。
macOS/Kokoro 音色输出分发许可尚未确认；保留输入文本、哈希、指标和来源记录不等于
取得音频分发授权。exp29 的 10 个 `.bin` 为文本 HTTP 请求与响应记录，继续保留。

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
