#!/usr/bin/env bash
# 加一个 · 制造抢占：GPU_UTIL 0.90 → 0.80 且 MAX_MODEL_LEN 2048（0.70 连一人都坐不下；0.80 预算约 5–6K token，1280 的乘客 4 人即满），重跑并发 8 / 16。看 num_preemptions 何时动、ITL 抖成什么样
source "$(dirname "$0")/lib.sh"
window_open
set_param GPU_UTIL=0.80 MAX_MODEL_LEN=2048
for c in 8 16; do bench exp4-u80-c$c $c 1024 256 $(( c*8 )); done
set_param GPU_UTIL=0.90 MAX_MODEL_LEN=8192
[ "${KEEP_OPEN:-0}" = 1 ] || window_close
