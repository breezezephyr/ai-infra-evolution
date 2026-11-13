#!/usr/bin/env bash
# 部署网关 + bench 脚本 + 单元到 DARYU
set -e; cd "$(dirname "$0")"
H="ssh -p 6064 researcher@SSH_HOST"
$H 'mkdir -p /opt/p2/gateway /opt/p2/bench'
scp -P 6064 -q gateway/gw.py researcher@SSH_HOST:/opt/p2/gateway/
scp -P 6064 -q bench/lib3.sh bench/exp5_admission.sh bench/smoke3.sh bench/exp6_priority.sh bench/exp7_routing.sh bench/mix.py researcher@SSH_HOST:/opt/p2/bench/
scp -P 6064 -q daryu/p2-gw.service researcher@SSH_HOST:/etc/systemd/system/
$H '[ -f /etc/default/p2-gw ] || cat > /etc/default/p2-gw' < daryu/p2-gw.default
$H 'chmod +x /opt/p2/bench/*.sh /opt/p2/gateway/gw.py; systemctl daemon-reload; systemctl disable p2-gw 2>/dev/null; echo deployed; python3 -c "import ast;ast.parse(open(\"/opt/p2/gateway/gw.py\").read());print(\"gw.py ok\")"'
