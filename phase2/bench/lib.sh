#!/usr/bin/env bash
# P2 压测公用函数。在 DARYU 上跑（客户端与服务端同机，去掉网络抖动；24 核够用）。
set -Eeuo pipefail   # -E：函数内的错误也触发 ERR trap
VLLM=/root/vllm-env/bin/vllm
BASE=http://127.0.0.1:8003
MODEL=qwen3-1.7b
MODEL_DIR=/opt/models/Qwen3-1.7B   # 客户端要本地 tokenizer
RES=/opt/p2/results; mkdir -p "$RES"
ENVF=/etc/default/bench-vllm
# 同一时刻只允许一个实验窗口，防止两个脚本互相开关服务
exec 9>/opt/p2/.window.lock; flock -n 9 || { echo "another bench window is running (lock /opt/p2/.window.lock)" >&2; exit 2; }

log(){ printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" >&2; }

# 实验窗口：停 embedding（Conflicts 会自动做），起 bench，等就绪
window_open(){
  log "window open: stop embedding, start bench-vllm ($(grep -v '^#' $ENVF | tr '\n' ' '))"
  systemctl start bench-vllm
  for i in $(seq 1 60); do curl -sf -m 2 $BASE/health >/dev/null && { log "bench-vllm ready"; return; }; sleep 5; done
  log "bench-vllm failed to start"; journalctl -u bench-vllm -n 30 --no-pager -o cat >&2; window_close; exit 1
}
# 任何异常退出都把 embedding 恢复回来（正常结束由脚本末尾的 window_close 负责）
_closed=0
window_close(){ [ $_closed = 1 ] && return; _closed=1; log "window close: restore embedding"; systemctl stop bench-vllm; systemctl start qwen3-embedding; }
trap '[ "${KEEP_OPEN:-0}" = 1 ] || window_close' ERR

# 改参数并重启 bench（key=value ...）
set_param(){ for kv in "$@"; do k=${kv%%=*}; v=${kv#*=}; sed -i "s|^$k=.*|$k=$v|" $ENVF; done; systemctl restart bench-vllm; sleep 3; window_open; }

# bench <name> <concurrency> <input> <output> <num_prompts> [extra vllm-bench args]
# 结果 json 里带 prom_start/prom_end 时间戳，回头在 Grafana 上框窗口
bench(){
  local name=$1 conc=$2 inp=$3 out=$4 n=$5; shift 5
  local ts=$(date +%Y%m%d-%H%M%S) t0=$(date +%s)
  log "bench $name conc=$conc in=$inp out=$out n=$n $*"
  $VLLM bench serve --endpoint-type openai-comp --endpoint /v1/completions --base-url $BASE --model $MODEL_DIR --tokenizer $MODEL_DIR --served-model-name $MODEL \
    --dataset-name random --random-input-len $inp --random-output-len $out --ignore-eos \
    --num-prompts $n --max-concurrency $conc --request-rate inf \
    --percentile-metrics ttft,tpot,itl,e2el --metric-percentiles 50,90,99 \
    --save-result --result-dir $RES --result-filename "${name}-${ts}.json" \
    --metadata name=$name conc=$conc prom_start=$t0 "$(grep -v '^#' $ENVF | tr '\n' ' ' | sed 's/ /,/g;s/,$//' | sed 's/^/env=/')" "$@" 2>&1 | grep -vE "^\s*$|it/s\]" | tail -25
  python3 - "$RES/${name}-${ts}.json" $(date +%s) <<'PY'
import json,sys; p=sys.argv[1]; d=json.load(open(p)); d['prom_end']=int(sys.argv[2]); json.dump(d,open(p,'w'),indent=1)
PY
  sleep 15   # 让曲线回落，窗口之间留白
}
