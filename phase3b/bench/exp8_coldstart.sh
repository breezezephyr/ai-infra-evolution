#!/usr/bin/env bash
# 压测八 · 出一辆新车要多久：同一辆 bench-vllm（Qwen3-1.7B）反复起，按 journal 切段
#   warm      页缓存热 + 编译缓存在（日常重启）×3
#   pagecold  drop_caches 后起：权重从盘读 ×2
#   nocompile 编译缓存移走（备份到 .bak，结束恢复）：冷编译 ×1，之后缓存重新生成
#   eager     --enforce-eager：不编译、不捕获 graph ×2
#   graph6    只捕获 6 个 graph 尺寸 [1,2,4,8,16,32] ×2
# eager / graph6 / warm 各跑一小段压测（并发 1 与 8，各 32 条 256 进 128 出），看启动省下的时间在 decode 上付多少
source /opt/p2/bench/lib.sh
OUTJ=$RES/exp8-starts.jsonl; CC=/root/.cache/vllm/torch_compile_cache
restore(){ [ -d $CC.bak ] && { rm -rf $CC; mv $CC.bak $CC; log "compile cache restored"; }; sed -i "s|^EXTRA_ARGS=.*|EXTRA_ARGS=|" $ENVF; }
trap 'restore; window_close' ERR EXIT
start_once(){ local name=$1
  systemctl stop bench-vllm; sleep 3
  local since=$(date '+%Y-%m-%d %H:%M:%S')
  systemctl start bench-vllm
  for i in $(seq 1 600); do curl -sf -m 1 $BASE/health >/dev/null && break; sleep 0.5; done
  local t_health=$(date +%s.%N)
  local r=$(python3 /opt/p2/bench/startlog.py $name "$since")
  echo "$r" | python3 -c "import json,sys;d=json.loads(sys.stdin.read());d['health_epoch']=$t_health;print(json.dumps(d,ensure_ascii=False))" >> $OUTJ
  log "$name: $(echo "$r" | cut -c1-300)"; }
extra(){ sed -i "s|^EXTRA_ARGS=.*|EXTRA_ARGS=$1|" $ENVF; }
smallbench(){ bench exp8-$1-c1 1 256 128 32; bench exp8-$1-c8 8 256 128 32; }

systemctl stop qwen3-embedding
extra ""
for i in 1 2 3; do start_once warm$i; done
smallbench warm
for i in 1 2; do systemctl stop bench-vllm; sync; echo 3 > /proc/sys/vm/drop_caches; start_once pagecold$i; done
mv $CC $CC.bak; start_once nocompile1; rm -rf $CC; mv $CC.bak $CC
extra "--enforce-eager"
for i in 1 2; do start_once eager$i; done
smallbench eager
extra '--compilation-config {"level":3,"cudagraph_capture_sizes":[32,16,8,4,2,1]}'
for i in 1 2; do start_once graph6_$i; done
smallbench graph6
extra ""
