#!/usr/bin/env bash
# Restart the paper bot after any exit (10s backoff); refuse a second copy.
cd "$(dirname "$0")/.." || exit 1
mkdir -p state
PIDF=state/supervisor.pid
if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then
  echo "supervisor already running (pid $(cat "$PIDF"))" >&2
  exit 1
fi
echo $$ > "$PIDF"
trap 'rm -f "$PIDF"; exit 0' INT TERM
while true; do
  uv run python -m desk.bot.run --loop
  echo "$(date -u +%FT%TZ) bot exited with $?, restarting in 10s" >> state/bot.log
  sleep 10
done
