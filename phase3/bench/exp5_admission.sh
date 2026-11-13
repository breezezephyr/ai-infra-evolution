#!/usr/bin/env bash
# 压测五 · 站台那道门：并发 32（exp1 里全在站台排队的那组），同一负载走三种门
#   pass    透传基线 = exp1-c32 重现
#   reject  token 预算 12000，放不下 429
#   queue   token 预算 12000，网关排队，最多等 GW_QUEUE_WAIT 秒后 503
# 再加一组 pass + GW_TTFT=5：不限流，只给首字期限，看多少人会被 504
source "$(dirname "$0")/lib3.sh"
CONC=${CONC:-32}; N=${N:-256}
window_open
for mode in pass reject queue; do
  gw_set GW_MODE=$mode GW_TTFT=0
  gw_bench exp5-$mode-c$CONC $CONC 1024 256 $N
done
gw_set GW_MODE=pass GW_TTFT=${TTFT_DEADLINE:-5}
gw_bench exp5-ttft5-c$CONC $CONC 1024 256 $N
gw_set GW_MODE=pass GW_TTFT=0
[ "${KEEP_OPEN:-0}" = 1 ] || window_close
