#!/usr/bin/env bash
# 压测六 · 谁先出首字：1 路交互（256 in / 64 out，高优，思考 0.5 s）+ 7 路批处理（2K in / 256 out）同车
#   pass      网关透传，vLLM 自己 FCFS（vLLM 0.8.5 V1 没有 priority 调度）
#   fcfs      网关预算 12000 排队，先来先上（7 × 2304 放 5 路，站台常驻 2 路批处理）
#   prio      同上，交互路 x-priority 插队
#   reserve   优先级 + 给高优留 1000 token 座位：批处理只能用 11000（放 4 路），交互路到了就有座
# 批处理每条实际 ≈ 2400 token（随机文本重新分词 +5%），不是名义 2304
source "$(dirname "$0")/lib3.sh"
SECS=${SECS:-150}
MIX=(--cls inter:1:256:64:1:0.5 --cls batch:7:2048:256:100:0)
PY=/root/vllm-env/bin/python
mix(){ local name=$1; shift; local start=$(wc -l < $GWLOG 2>/dev/null || echo 0)
  log "mix $name secs=$SECS $*"
  $PY /opt/p2/bench/mix.py --name $name --secs $SECS "${MIX[@]}" "$@" | tail -40
  local f=$(ls -t $RES/${name}-*.json | grep -v req | head -1)
  tail -n +$((start+1)) $GWLOG > "${f%.json}.gw.jsonl"; curl -s $BASE/gw/stats >&2; echo >&2
  sleep 15; }
window_open
grep -q '^GW_RESERVE=' $GWENV || echo GW_RESERVE=0 >> $GWENV
gw_set GW_MODE=pass GW_TTFT=0 GW_PRIORITY=0 GW_BUDGET=12000 GW_QUEUE_WAIT=60 GW_RESERVE=0
mix exp6-pass
gw_set GW_MODE=queue GW_PRIORITY=0
mix exp6-fcfs
gw_set GW_MODE=queue GW_PRIORITY=1
mix exp6-prio
gw_set GW_MODE=queue GW_PRIORITY=1 GW_RESERVE=1000
mix exp6-reserve
gw_set GW_MODE=pass GW_PRIORITY=0 GW_BUDGET=12000 GW_QUEUE_WAIT=10 GW_RESERVE=0
[ "${KEEP_OPEN:-0}" = 1 ] || window_close
