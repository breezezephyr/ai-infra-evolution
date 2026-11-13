#!/usr/bin/env bash
# 验网关链路：pass / reject / queue 各跑 16 条小请求
source "$(dirname "$0")/lib3.sh"
window_open
gw_set GW_MODE=pass;   gw_bench smoke3-pass   4 256 64 16
gw_set GW_MODE=reject GW_BUDGET=1500; gw_bench smoke3-reject 8 256 64 16
gw_set GW_MODE=queue  GW_BUDGET=1500 GW_QUEUE_WAIT=30; gw_bench smoke3-queue  8 256 64 16
gw_set GW_MODE=pass GW_BUDGET=12000 GW_QUEUE_WAIT=10
[ "${KEEP_OPEN:-0}" = 1 ] || window_close
