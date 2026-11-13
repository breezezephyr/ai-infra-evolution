#!/usr/bin/env bash
set -euo pipefail
exec /root/voice-env/bin/python -c '
import glob,os,sys
paths=sorted(glob.glob("/root/vllm-env/lib/python3.12/site-packages/nvidia/*/lib"))
prior=os.environ.get("LD_LIBRARY_PATH","")
os.environ["LD_LIBRARY_PATH"]=":".join(paths+([prior] if prior else []))
os.execv(sys.executable,[sys.executable,*sys.argv[1:]])
' /opt/p4/exp18/idle_probe.py "$@"
