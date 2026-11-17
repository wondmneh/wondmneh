#!/usr/bin/env bash
# Daily routine: catch the paper books up, make sure the bot is running, print the brief.
cd "$(dirname "$0")/.."
uv sync -q
[ -f data/manifest.json ] || uv run python -m desk.data 4 20
uv run python -m desk.bot.run --once > /dev/null 2>&1 || echo "WARNING: catch-up cycle failed, see state/bot.log"
scripts/start.sh
uv run python -m desk.brief
