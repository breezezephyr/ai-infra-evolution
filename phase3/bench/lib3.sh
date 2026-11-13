#!/usr/bin/env bash
# P3 公用：沿用 P2 lib.sh（窗口、bench、锁），bench 走网关 :8010
source /opt/p2/bench/lib.sh
BASE=http://127.0.0.1:8010
# 窗口开关仍探 vLLM 本体（网关在窗口打开后才由 gw_set 起）
eval "$(declare -f window_open | sed '1s/^window_open/vllm_window_open/')"
window_open(){ local BASE=http://127.0.0.1:8003; vllm_window_open; }
GWENV=/etc/default/p2-gw
GWLOG=/opt/p2/results/gw.jsonl

# gw_set key=value ... ：改网关参数并重启，等就绪
gw_set(){
  for kv in "$@"; do k=${kv%%=*}; v=${kv#*=}; sed -i "s|^$k=.*|$k=$v|" $GWENV; done
  systemctl restart p2-gw
  for i in $(seq 1 20); do curl -sf -m 2 $BASE/health >/dev/null && { log "p2-gw ready: $(grep -v '^#' $GWENV | tr '\n' ' ')"; return; }; sleep 1; done
  log "p2-gw failed"; journalctl -u p2-gw -n 20 --no-pager -o cat >&2; exit 1
}
# 一次 bench 前后截网关日志：gw_bench <name> <conc> <in> <out> <n> [extra]
# 网关 JSONL 按 name 切一份 -> $RES/<name>-<ts>.gw.jsonl，并把 /gw/stats 打到 stderr
gw_bench(){
  local name=$1; local start=$(wc -l < $GWLOG 2>/dev/null || echo 0)
  bench "$@"
  local f=$(ls -t $RES/${name}-*.json | head -1); local out=${f%.json}.gw.jsonl
  tail -n +$((start+1)) $GWLOG > "$out"; log "gw log $(wc -l < "$out") lines -> $out"
  curl -s $BASE/gw/stats >&2; echo >&2
}
