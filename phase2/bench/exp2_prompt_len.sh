#!/usr/bin/env bash
# 压测二 · 行李多重：并发 4，输入 256→1K→2K→6K（max-model-len 8192），输出 128。看 TTFT 斜率、ITL 有没被拖
# 再对 MAX_BATCHED_TOKENS 2048 vs 8192 各跑一遍——P1·上 决定 4 的核心取舍
source "$(dirname "$0")/lib.sh"
window_open
for bt in 2048 8192; do
  set_param MAX_BATCHED_TOKENS=$bt
  for l in 256 1024 2048 6000; do bench exp2-bt$bt-in$l 4 $l 128 32; done
done
set_param MAX_BATCHED_TOKENS=8192
[ "${KEEP_OPEN:-0}" = 1 ] || window_close
