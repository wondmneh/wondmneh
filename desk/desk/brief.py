"""Morning brief: market, podium, paper trades and P&L, Guardian alerts. Facts only."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from . import hunter, panel, research, strategies
from .bot import paper
from .bot.feed import Feed
from .bot.okx import OKX

ROOT = Path(__file__).resolve().parent.parent
STATE, REPORTS = ROOT / "state", ROOT / "reports"
SWAP_AFTER = 7
pct = lambda x: f"{x:+.2%}"


def beat_streak(ch: dict, champ: dict) -> int:
    """Consecutive completed UTC days on which the challenger made money and beat the champion."""
    a, b = pd.Series(ch.get("daily_equity", {})).diff(), pd.Series(champ.get("daily_equity", {})).diff()
    days = sorted(set(a.dropna().index) & set(b.dropna().index))[:-1]      # drop today, still open
    n = 0
    for d in reversed(days):
        if a[d] > 0 and a[d] > b[d]:
            n += 1
        else:
            break
    return n


def main() -> None:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    res = json.loads((REPORTS / "results.json").read_text())
    back = {s["name"]: s for s in res["strategies"]}
    feed = Feed(STATE, OKX(), cfg["feed"])
    D = panel.build_panel(*feed.panel_inputs())
    t = hunter.sweep(D)
    now = pd.Timestamp.now(tz="UTC")
    cut = now - pd.Timedelta(hours=24)
    hb = paper.read_json(STATE / "heartbeat.json", {})
    btc = t.loc[strategies.BTC]
    L = [f"# Morning brief, {now:%Y-%m-%d %H:%M} UTC", "",
         "## Market (OKX, data to " + f"{D.close.index[-1]:%Y-%m-%d %H:%M} UTC)", "",
         f"1. BTC {btc['last']:,.0f}: {pct(btc.ret_7d)} in 7 days, {pct(btc.ret_30d)} in 30 days; regime "
         f"**{research.btc_regime(D).iloc[-1]}**.",
         f"2. Breadth: {int(t.above_ema50.sum())}/{len(t)} coins above their 50-day average; median 30-day return "
         f"{pct(t.ret_30d.median())}; strongest {t.ret_30d.idxmax().split('-')[0]} {pct(t.ret_30d.max())}, weakest "
         f"{t.ret_30d.idxmin().split('-')[0]} {pct(t.ret_30d.min())}.",
         f"3. Volatility at the {t.vol_pctile_1y.median():.0%} percentile of the last year; median funding "
         f"{pct(t.funding_7d_ann.median())} annualised; volume {t.volume_vs_30d.median():.2f}x its 30-day average.", "",
         "## Podium", "",
         "| Book | Role | Backtest 3y return / max DD / Sharpe | Paper equity | Paper return | Today | Open | Trades (W/L) | Days beating champion |",
         "|---|---|---|---|---|---|---|---|---|"]
    stat = {b: paper.read_json(STATE / "books" / b / "status.json", {}) for b in cfg["books"]}
    champ = cfg["champion"]
    swaps = []
    for b, bc in cfg["books"].items():
        s, o = stat[b], back[bc["strategy"]]["oos"]
        role = "champion (provisional)" if b == champ else "challenger"
        streak = "" if b == champ else str(beat_streak(s, stat[champ]))
        if streak and int(streak) >= SWAP_AFTER:
            swaps.append(b)
        if not s.get("equity"):
            L.append(f"| {b} | {role} | {pct(o['ret'])} / {pct(o['max_dd'])} / {o['sharpe']:.2f} | warming up | | | | | {streak} |")
            continue
        L.append(f"| {b} | {role} | {pct(o['ret'])} / {pct(o['max_dd'])} / {o['sharpe']:.2f} | ${s['equity']:,.2f} | "
                 f"{pct(s['return_since_start'])} | ${s['pnl_today']:+,.2f} | {len(s['open_positions'])} | "
                 f"{s['trades']} ({s['wins']}/{s['losses']}) | {streak} |")
    L += ["", f"Paper trading started {cfg['paper_start']}. Backtest figures are walk-forward, after fees, slippage and funding.",
          "", "## Paper trades, last 24 hours", ""]
    alerts, n = [], 0
    for b in cfg["books"]:
        path = STATE / "books" / b / "journal.jsonl"
        for line in path.read_text().splitlines() if path.exists() else []:
            e = json.loads(line)
            if pd.Timestamp(e["time"]) <= cut:
                continue
            if e["type"] in ("alert", "halt"):
                alerts.append(f"- {e['time']} {b}: {e['type']} ({e['reason']})")
            elif e["type"] == "entry":
                n += 1
                stop = f", stop {e['stop']:g}" if e.get("stop") else ""
                L.append(f"- {e['time']} {b}: opened {e['side']} {e['symbol'].split('-')[0]} at {e['price']:g}, "
                         f"size {e['qty']:.4g}{stop}")
            else:
                n += 1
                L.append(f"- {e['time']} {b}: closed {e['symbol'].split('-')[0]} at {e['price']:g} ({e['reason']}), "
                         f"P&L ${e['pnl']:+,.2f}")
    if not n:
        L.append("- None.")
    L += ["", "Closed-trade P&L, last 24 hours: " + ", ".join(
        f"{b} ${stat[b].get('pnl_24h', 0):+,.2f} ({stat[b].get('closed_24h', 0)} trades)" for b in cfg["books"]) + ".",
        "", "## Guardian", ""] + (sorted(set(alerts)) or ["- No alerts."])
    L += ["", f"Bot heartbeat: {hb.get('time', 'none')} (feed {hb.get('feed', 'unknown')}).", "", "## Flags", ""]
    L.append(f"- Swap rule: {', '.join(swaps)} beat the champion on {SWAP_AFTER}+ straight days." if swaps
             else f"- Swap rule: no challenger has beaten the champion on {SWAP_AFTER} straight days.")
    sel = paper.read_json(REPORTS / "selection.json", {})
    L.append("- Real money: " + ("a strategy is cleared, waiting for your go live." if sel.get("cleared_for_live")
                                 else "nothing is cleared; no strategy has passed every check."))
    out = "\n".join(L) + "\n"
    (REPORTS / "brief.md").write_text(out)
    print(out)


if __name__ == "__main__":
    main()
