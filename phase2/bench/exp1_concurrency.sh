#!/usr/bin/env bash
# 压测一 · 坐几人：并发 1→2→4→8→16→32（8 GB 卡 KV 预算 ~1.4 GiB ≈ 13K token 座位，1K+256 的乘客约 10 人坐满），输入 1K 输出 256。看 ITL 涨多少、吞吐拐点、KV 水位何时出现抢占
source "$(dirname "$0")/lib.sh"
window_open
for c in 1 2 4 8 16 32; do n=$(( c*8 < 32 ? 32 : c*8 )); bench exp1-c$c $c 1024 256 $n; done
[ "${KEEP_OPEN:-0}" = 1 ] || window_close
