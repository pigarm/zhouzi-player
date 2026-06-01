#!/bin/bash
# 启动肘子播放器（后台运行，不占用终端）
cd "$(dirname "$0")" || exit 1
nohup python3 player.py </dev/null >/dev/null 2>&1 &
disown
