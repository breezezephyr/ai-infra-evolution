#!/usr/bin/env bash
# 把 DARYU 上 exp5+ / smoke3 的结果拉回 phase3/results/
cd "$(dirname "$0")" && mkdir -p results && rsync -az -e "ssh -p 6064" --include='exp[5-9]-*' --include='smoke3-*' --include="gw.jsonl" --exclude='*' researcher@SSH_HOST:/opt/p2/results/ results/ && ls results | tail
