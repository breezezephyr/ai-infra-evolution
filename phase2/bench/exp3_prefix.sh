#!/usr/bin/env bash
# 压测三 · 常客：3K 公共前缀 + 64 随机 token，输出 64，120 条，并发 4。开/关 prefix caching 各一遍
# 看命中率、TTFT 降幅、ITL 是否不变（P0：省搬不省跑）
source "$(dirname "$0")/lib.sh"
window_open
set_param EXTRA_ARGS=--no-enable-prefix-caching
bench exp3-nocache 4 64 64 120 --random-prefix-len 3072
set_param EXTRA_ARGS=
bench exp3-cache 4 64 64 120 --random-prefix-len 3072
[ "${KEEP_OPEN:-0}" = 1 ] || window_close
