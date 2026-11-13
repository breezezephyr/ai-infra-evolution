#!/usr/bin/env bash
# 把 DARYU 上的压测结果拉回本地 phase2/results/
mkdir -p "$(dirname "$0")/results" && rsync -az -e "ssh -p 6064" researcher@SSH_HOST:/opt/p2/results/ "$(dirname "$0")/results/" && ls "$(dirname "$0")/results" | tail
