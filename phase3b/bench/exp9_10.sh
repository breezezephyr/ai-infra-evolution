#!/usr/bin/env bash
# 压测九 · 扩容信号：直连 vLLM，λ 0.5 → 2.2 req/s 爬 240 s 再保持 60 s（合车 μ ≈ 1.45），每秒采 waiting / running / KV / GPU 利用率
# 压测十 · 停车：经网关 :8010，三种输出长度（512 / 1024 / 1536）各 2 路，512 进；60 s 时 /gw/drain，期限 0 / 10 / 30 s
source /opt/p2/bench/lib3.sh
PY=/root/vllm-env/bin/python
window_open
if [ "${SKIP9:-0}" != 1 ]; then log "exp9 ramp"
$PY /opt/p2/bench/ramp.py --name exp9-ramp --base http://127.0.0.1:8003 --lam0 0.5 --lam1 2.2 --secs 240 --hold 60
sleep 20; fi
gw_set GW_MODE=pass GW_TTFT=0 GW_PRIORITY=0 GW_RESERVE=0 GW_BUDGET=12000
for dl in ${ORDER:-0 5 10 30}; do
  curl -s -X POST $BASE/gw/undrain >/dev/null
  start=$(wc -l < $GWLOG)
  log "exp10 drain deadline=$dl"
  ( sleep ${DRAIN_AT:-47}; curl -s -X POST "$BASE/gw/drain?deadline=$dl" >&2; echo >&2 ) &
  $PY /opt/p2/bench/mix.py --name exp10-dl$dl --secs 90 --stop-on-503 --cls o512:2:512:512:100:0 --cls o1024:2:512:1024:100:0 --cls o1536:2:512:1536:100:0 | grep -E '"(done|err)"' | tr -d '\n'; echo
  wait
  sleep 3
  f=$(ls -t $RES/exp10-dl$dl-*.json | grep -v req | head -1); tail -n +$((start+1)) $GWLOG > "${f%.json}.gw.jsonl"
  curl -s -X POST $BASE/gw/undrain >/dev/null; sleep 10
done
gw_set GW_MODE=pass
[ "${KEEP_OPEN:-0}" = 1 ] || window_close
