#!/usr/bin/env bash
# Sunday routine: fresh 4-year download, full re-audit, new report. Does not change config.yaml.
set -e
cd "$(dirname "$0")/.."
uv sync -q
uv run python -m desk.data 4 20
uv run python -m desk.research
uv run python -m desk.report
uv run python -m desk.hunter
