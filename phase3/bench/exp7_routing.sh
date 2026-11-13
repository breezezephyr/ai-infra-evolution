#!/usr/bin/env bash
# 压测七 · 寄存箱在哪辆车上：两辆 Qwen3-0.6B（8004 / 8005，KV 各 9,952 token），网关 :8011 选车
# 负载：8 组常客，每组 1,536 token 公共前缀 + 64 随机 token，输出 64，闭环并发 8，每组 150 s
#   8 × 1,536 = 12.3K > 一辆车 9.95K：轮询时每辆车都要装全部 8 组，装不下；哈希时每辆车只装 4 组（6.1K）
#   rr        轮询，常客均匀
#   hash      前缀哈希，常客均匀
#   hash-zipf 前缀哈希，常客 Zipf 1.1（头部一组约占三成）
#   bounded   有界负载哈希（在途 > ⌈1.25 × 平均⌉ 改道），常客 Zipf 1.1
# 每组换 seed 生成新前缀，上一组的寄存箱不会被命中；前后抓两辆车 /metrics 做差
source /opt/p2/bench/lib.sh   # 只用 log / RES / 锁；窗口自己管（两辆车不是 bench-vllm）
trap - ERR
SECS=${SECS:-150}; CONC=${CONC:-8}
GWPID=; GW=http://127.0.0.1:8011; PY=/root/vllm-env/bin/python; GWLOG7=$RES/gw7.jsonl
pair_open(){ log "pair open: stop embedding, start bench-pair@8004/8005"
  for p in 8004 8005; do systemctl start bench-pair@$p
    for i in $(seq 80); do curl -sf -m2 localhost:$p/health >/dev/null && break; sleep 3; done
    curl -sf -m2 localhost:$p/health >/dev/null || { log "$p failed"; pair_close; exit 1; }; done; log "pair ready"; }
pair_close(){ log "pair close: restore embedding"; [ -n "$GWPID" ] && kill $GWPID 2>/dev/null || true; systemctl stop bench-pair@8004 bench-pair@8005; systemctl start qwen3-embedding; }
trap pair_close ERR
gw_start(){ [ -n "$GWPID" ] && kill $GWPID 2>/dev/null || true; sleep 1
  env GW_PORT=8011 GW_BACKENDS=8004,8005 GW_MODE=pass GW_ROUTE=$1 GW_LOG=$GWLOG7 python3 /opt/p2/gateway/gw.py >> $RES/gw7.out 2>&1 &
  GWPID=$!; for i in $(seq 20); do curl -sf -m2 $GW/health >/dev/null && { log "gw7 route=$1"; return; }; sleep 0.5; done; log "gw7 failed"; exit 1; }
snap(){ for p in 8004 8005; do curl -s localhost:$p/metrics | grep -E '^vllm:(gpu_prefix_cache_(queries|hits)_total|num_preemptions_total|prompt_tokens_total|generation_tokens_total|request_success_total)' | sed "s/^/$p /"; done; }
run(){ local name=$1 route=$2 zipf=$3 seed=$4
  gw_start $route; local start=$(wc -l < $GWLOG7 2>/dev/null || echo 0)
  snap > /tmp/exp7.before
  $PY /opt/p2/bench/mix.py --name $name --secs $SECS --base $GW --model qwen3-0.6b --tokenizer /opt/models/Qwen3-0.6B \
    --prefix-groups 8 --prefix-len 1536 --zipf $zipf --seed $seed --cls user:$CONC:64:64:100:0 | grep -E '"(done|err|ttft_p50|ttft_p99|itl_p99|out_tok_s)"'
  snap > /tmp/exp7.after
  local f=$(ls -t $RES/${name}-*.json | grep -v req | head -1)
  tail -n +$((start+1)) $GWLOG7 > "${f%.json}.gw.jsonl"
  python3 - "$f" <<'PY'
import json,sys,re
def load(p):
    d={}
    for l in open(p):
        port,rest=l.split(' ',1); k,v=rest.rsplit(' ',1); k=re.sub(r'\{.*?finished_reason="(\w+)".*\}',r'_\1',k); k=re.sub(r'\{.*\}','',k)
        d[(port,k)]=d.get((port,k),0)+float(v)
    return d
b,a=load('/tmp/exp7.before'),load('/tmp/exp7.after'); f=sys.argv[1]; s=json.load(open(f)); s['servers']={}
for port in ('8004','8005'):
    g=lambda k: a.get((port,k),0)-b.get((port,k),0)
    s['servers'][port]={'queries':g('vllm:gpu_prefix_cache_queries_total'),'hits':g('vllm:gpu_prefix_cache_hits_total'),'preempt':g('vllm:num_preemptions_total'),
        'prompt_tok':g('vllm:prompt_tokens_total'),'gen_tok':g('vllm:generation_tokens_total'),'done':g('vllm:request_success_total_length')+g('vllm:request_success_total_stop')}
    q=s['servers'][port]; q['hit_rate']=round(q['hits']/q['queries'],3) if q['queries'] else None
json.dump(s,open(f,'w'),indent=1,ensure_ascii=False); print(json.dumps(s['servers']))
PY
  sleep 10; }
pair_open
run exp7-rr        rr      0   71
run exp7-hash      hash    0   72
run exp7-hash-zipf hash    1.1 73
run exp7-bounded   bounded 1.1 73
pair_close
