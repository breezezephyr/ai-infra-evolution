#!/usr/bin/env bash
# 空跑：起服务、发 16 条小请求、确认 /metrics 全部指标名出现、关窗
source "$(dirname "$0")/lib.sh"
window_open
bench smoke 4 256 64 16
echo "--- vllm metric names on 8003:"; curl -s $BASE/metrics | grep "^# TYPE vllm:" | sed 's/# TYPE //'
[ "${KEEP_OPEN:-0}" = 1 ] || window_close
