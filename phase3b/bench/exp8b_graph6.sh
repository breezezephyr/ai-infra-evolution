#!/usr/bin/env bash
# exp8 补跑：只捕获 6 个 graph 尺寸。systemd 会把 $EXTRA_ARGS 里的 JSON 引号吃掉，改用临时 drop-in + ${COMP} 整词传参
source /opt/p2/bench/lib.sh
OUTJ=$RES/exp8-starts.jsonl; DI=/etc/systemd/system/bench-vllm.service.d
cleanup(){ sed -i "s|^EXTRA_ARGS=.*|EXTRA_ARGS=|" $ENVF; rm -f $DI/exp8.conf; rmdir $DI 2>/dev/null; systemctl daemon-reload; window_close; }
trap cleanup ERR EXIT
start_once(){ local name=$1; systemctl stop bench-vllm; sleep 3; local since=$(date '+%Y-%m-%d %H:%M:%S')
  systemctl start bench-vllm
  for i in $(seq 1 300); do curl -sf -m 1 $BASE/health >/dev/null && break; systemctl is-failed -q bench-vllm && { log "$name failed"; exit 1; }; sleep 0.5; done
  python3 /opt/p2/bench/startlog.py $name "$since" >> $OUTJ; tail -1 $OUTJ | cut -c1-220 >&2; }
mkdir -p $DI
cat > $DI/exp8.conf <<'U'
[Service]
Environment='COMP={"level":3,"cudagraph_capture_sizes":[32,16,8,4,2,1]}'
ExecStart=
ExecStart=/root/vllm-env/bin/vllm serve /opt/models/Qwen3-1.7B --served-model-name qwen3-1.7b --host 127.0.0.1 --port 8003 --dtype bfloat16 --max-model-len ${MAX_MODEL_LEN} --gpu-memory-utilization ${GPU_UTIL} --max-num-seqs ${MAX_NUM_SEQS} --max-num-batched-tokens ${MAX_BATCHED_TOKENS} --compilation-config ${COMP}
U
systemctl daemon-reload
systemctl stop qwen3-embedding
for i in 1 2; do start_once graph6_$i; done
journalctl -u bench-vllm --no-pager -o cat --since "-3min" | grep -o "cudagraph_capture_sizes[^]]*]" | head -1 >&2 || true
bench exp8-graph6-c1 1 256 128 32; bench exp8-graph6-c8 8 256 128 32
bench exp8-graph6-c16 16 256 128 64
# 对照：默认 67 个尺寸 与 eager 各补一组并发 16
rm -f $DI/exp8.conf; systemctl daemon-reload
sed -i "s|^EXTRA_ARGS=.*|EXTRA_ARGS=|" $ENVF; systemctl restart bench-vllm; window_open
bench exp8-warm-c16 16 256 128 64
sed -i "s|^EXTRA_ARGS=.*|EXTRA_ARGS=--enforce-eager|" $ENVF; systemctl restart bench-vllm; window_open
bench exp8-eager-c16 16 256 128 64
sed -i "s|^EXTRA_ARGS=.*|EXTRA_ARGS=|" $ENVF
