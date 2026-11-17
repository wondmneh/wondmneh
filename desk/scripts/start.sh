#!/usr/bin/env bash
# Start the supervised paper bot if it is not already running.
cd "$(dirname "$0")/.."
mkdir -p state
if [ -f state/supervisor.pid ] && kill -0 "$(cat state/supervisor.pid)" 2>/dev/null; then
  echo "already running (pid $(cat state/supervisor.pid))"
  exit 0
fi
[ -f data/manifest.json ] || uv run python -m desk.data 4 20
nohup setsid scripts/supervise.sh > state/supervisor.log 2>&1 &
sleep 2
echo "started (pid $(cat state/supervisor.pid 2>/dev/null))"
