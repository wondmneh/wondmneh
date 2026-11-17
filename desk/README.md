# Desk

A crypto research desk in one folder: it downloads real history, tests strategy ideas
with costs, and paper trades the survivors. Nothing here can place a real order yet.

## What is where

| Part | File | Job |
|---|---|---|
| Data | `desk/data.py` | 4 years of 1H candles and funding for 20 OKX USDT perpetuals, with sources in `data/manifest.json` |
| Hunter | `desk/hunter.py`, `desk/strategies.py` | Market sweep, and 21 strategy ideas, each with its reason |
| Auditor | `desk/engine.py`, `desk/research.py`, `desk/report.py` | Backtests with fees, slippage and funding, walk-forward, Monte Carlo, final check, strategy cards |
| Builder | `desk/bot/` | Paper bot that replays the same engine on live OKX candles |
| Guardian | `desk/engine.py` (`Guard`), `desk/bot/run.py` | Flattens and pauses 24h at -3% on the day, 3 losses in a row, or a frozen feed |

## Run it

```bash
uv sync
uv run python -m desk.data 4 20     # download (about 15 minutes)
uv run python -m desk.research      # audit all strategies -> reports/results.json
uv run python -m desk.report        # reports/REPORT.md and reports/selection.json
scripts/start.sh                    # start the supervised paper bot
scripts/morning.sh                  # catch up, restart if needed, print the brief
scripts/weekly.sh                   # fresh download and full re-audit
uv run pytest
```

## Swapping strategies

Edit `config.yaml`. Each entry under `books` is its own $10,000 paper account and
`champion` names the one that would trade real money. Books are replayed from
`paper_start` on every cycle, so add a new book rather than changing the settings of an
existing one.

## How paper trading stays honest

The bot keeps no position state. Each hour it re-runs the backtest engine from
`paper_start` on real OKX candles, so paper results follow exactly the rules that were
backtested, and a crash or a sleeping machine loses nothing: the next run replays the
missed hours and marks those events `replayed`.

## Limits

- Fills are simulated from hourly candles with estimated slippage. Real fills will differ.
- The coin list contains only contracts that are still listed, which flatters backtests.
- Funding older than about 3 months is a Binance proxy for OKX.
- No free source has 4 years of open interest or liquidations, so no strategy uses them;
  `liq_cascade_reversal` uses a price and volume proxy.
- `desk/bot/live.py` can sign and send OKX orders but has never been run against the
  exchange and is not connected to the bot. It refuses to start unless `mode: live` and
  `DESK_GO_LIVE=yes`, reads keys only from environment variables, and has no withdrawal call.
