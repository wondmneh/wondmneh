"""Turn reports/results.json into the leaderboard, the podium and the strategy cards.

Podium rule (set before the holdout was read): among strategies that pass every
validation check and are profitable in the holdout, rank by the 1-5 rubric scored on
VALIDATION data only; ties go to the higher validation Sharpe.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import engine, panel, research, strategies

REPORTS = research.REPORTS
HOLD_GATE = "beats_hold_risk_adj"
pct = lambda x: f"{x:+.1%}"

GATE_TEXT = {
    "unseen_validation": "Profitable on walk-forward data it was not fitted on",
    "unseen_holdout": "Profitable on the final holdout year",
    "trades_50": "At least 50 out-of-sample trades",
    "fees_doubled": "Still profitable with fees and slippage doubled",
    "nearby_settings": "At least 70% of nearby settings profitable",
    "no_lookahead": "No future data leak (truncation test)",
    HOLD_GATE: "Beat holding on return per unit of drawdown in the validation window",
}


def podium(res: dict) -> tuple[list[dict], list[dict]]:
    """(strict passers, provisional list that only failed the hold gate), each ranked."""
    def rank(xs):
        return sorted(xs, key=lambda s: (-research.score(s["validation"])["total"], -s["validation"]["sharpe"]))
    strict = [s for s in res["strategies"] if s["confirmed"]]
    prov = [s for s in res["strategies"]
            if all(v for k, v in s["gates"].items() if k != HOLD_GATE) and not s["gates"][HOLD_GATE]]
    return rank(strict), rank(prov)


def fixed_run(D, name, params, start, guard=None):
    r = engine.run(D, strategies.compute(name, D, params), guard=guard)
    ret = r.equity.pct_change().fillna(0.0)[start:]
    tr = r.trades[r.trades.entry_time >= start]
    return ret, tr, r.halts[start:]


def card(D, s: dict, res: dict, role: str) -> list[str]:
    spec = strategies.REGISTRY[s["name"]]
    v, h, o = s["validation"], s["holdout"], s["oos"]
    hold = res["hold"]
    start = pd.Timestamp(s["windows"]["validation"][0])
    lp = s["live_params"]
    r0, t0, _ = fixed_run(D, s["name"], lp, start)
    r1, t1, halts = fixed_run(D, s["name"], lp, start, engine.Guard(0.03, 3, 24))
    g0, g1 = research.stats(r0, t0), research.stats(r1, t1)
    oos = pd.read_parquet(REPORTS / "oos_returns.parquet")[s["name"]]
    fold_ret = [float((1 + oos[b:c - pd.Timedelta(hours=1)]).prod() - 1) for _, b, c in research.folds(D.close.index)]
    lev = (t0.qty * t0.entry / t0.eq_at_entry)
    held = (t0.exit_time - t0.entry_time).dt.total_seconds() / 3600
    sc = research.score(o)
    mc = s["monte_carlo"]
    yes = lambda b: "Yes" if b else "NO"
    return [
        f"### {role}: `{s['name']}` ({spec.regime} markets)", "",
        f"**Idea.** {spec.idea}", "",
        f"**Why the edge exists, and who loses.** {spec.why}", "",
        f"**Rules.** {spec.rules}", "",
        f"**Settings going into paper trading.** `{json.dumps(lp)}`, chosen on the last 365 days only.", "",
        f"**Position size.** Risk 0.5% of equity to the stop; at most 1x equity per position, 3x in total and 8 positions "
        f"(when more than 8 coins signal, the 8 most liquid take the slots). In the backtest the typical position was "
        f"{lev.median():.0%} of equity and was held {held.median() / 24:.1f} days.", "",
        "**Results after fees, slippage and funding (out-of-sample, walk-forward).**", "",
        "| Period | Strategy return | Max drawdown | Sharpe | Trades | Hold BTC | Hold all 20 coins |",
        "|---|---|---|---|---|---|---|",
        f"| Validation ({s['windows']['validation'][0][:10]} to {s['windows']['validation'][1][:10]}) | {pct(v['ret'])} | "
        f"{pct(v['max_dd'])} | {v['sharpe']:.2f} | {v['trades']} | {pct(hold['val']['btc']['ret'])} | {pct(hold['val']['basket']['ret'])} |",
        f"| Holdout ({s['windows']['holdout'][0][:10]} to {s['windows']['holdout'][1][:10]}) | {pct(h['ret'])} | "
        f"{pct(h['max_dd'])} | {h['sharpe']:.2f} | {h['trades']} | {pct(hold['hol']['btc']['ret'])} | {pct(hold['hol']['basket']['ret'])} |",
        f"| All 3 years | {pct(o['ret'])} | {pct(o['max_dd'])} | {o['sharpe']:.2f} | {o['trades']} | "
        f"{pct(hold['oos']['btc']['ret'])} (drawdown {pct(hold['oos']['btc']['max_dd'])}) | "
        f"{pct(hold['oos']['basket']['ret'])} (drawdown {pct(hold['oos']['basket']['max_dd'])}) |", "",
        f"**Walk-forward.** {sum(x > 0 for x in fold_ret)} of {len(fold_ret)} quarterly folds profitable: "
        + ", ".join(pct(x) for x in fold_ret) + ".", "",
        f"**Worst month.** {pct(o['worst_month'])} ({o['worst_month_name']}). "
        f"**Longest losing streak.** {o['losing_streak']} trades. **Win rate.** {o['win_rate']:.0%}. "
        f"**Costs paid.** ${o['fees']:,.0f} fees and ${o['funding']:,.0f} funding on a $10,000 account.", "",
        f"**By BTC regime (all 3 years).** Bull {pct(o['regime']['bull'])}, bear {pct(o['regime']['bear'])}, "
        f"chop {pct(o['regime']['chop'])}.", "",
        f"**Monte Carlo (2,000 reshuffles of the out-of-sample trades).** 5th-percentile return {pct(mc['p5_ret'])}, "
        f"median {pct(mc['median_ret'])}, 95th-percentile drawdown {pct(mc['p95_dd'])}, chance of a loss {mc['p_loss']:.0%}.", "",
        f"**Score (1-5).** Profit {sc['profit']}, drawdown {sc['drawdown']}, trade count {sc['trades']}, "
        f"losing streak {sc['streak']}, bear and chop {sc['bear_chop']}. Total {sc['total']}/25.", "",
        f"**With the Guardian switched on** (flatten at -3% on the day or 3 losses in a row, 24h pause; current settings, "
        f"3 years): {pct(g1['ret'])} with drawdown {pct(g1['max_dd'])} and {len(halts)} halts, against {pct(g0['ret'])} "
        f"and {pct(g0['max_dd'])} without it.", "",
        "**Final check.**", "",
        f"- Wins on data it has never seen? Validation {yes(s['gates']['unseen_validation'])}, holdout {yes(s['gates']['unseen_holdout'])}.",
        f"- After fees and funding? Yes, all numbers above include them.",
        f"- Across 50+ trades? {yes(s['gates']['trades_50'])} ({o['trades']}).",
        f"- With fees doubled? {yes(s['gates']['fees_doubled'])}: {pct(s['fees_doubled']['oos'])} over the 3 years.",
        f"- Across nearby settings? {yes(s['gates']['nearby_settings'])}: {s['nearby']['share_profitable']:.0%} of the grid "
        f"profitable in validation, median Sharpe {s['nearby']['median_sharpe']:.2f}.",
        f"- Anything leak from the future? {'No' if s['gates']['no_lookahead'] else 'YES'}, by the truncation test.",
        f"- Beats simply holding? {yes(s['gates'][HOLD_GATE])} in validation (return/drawdown {v['ret_over_dd']:.2f} against "
        f"BTC {hold['val']['btc']['ret_over_dd']:.2f}). Over all 3 years: {o['ret_over_dd']:.2f} against BTC "
        f"{hold['oos']['btc']['ret_over_dd']:.2f} and the 20-coin basket {hold['oos']['basket']['ret_over_dd']:.2f}.", "",
        f"**Market that breaks it.** {spec.breaks} **Earliest warning sign.** {spec.warning}", "",
        f"**WHY THIS COULD FAIL.** It made less money than holding BTC through the bull market, so its case rests on "
        f"smaller drawdowns, not higher returns. It was the survivor of 21 ideas, so some of its result is selection luck. "
        f"The coin list contains only contracts still listed today, slippage is an estimate, and funding before the last "
        f"3 months is a Binance proxy. {spec.breaks}", "",
    ]


def main() -> None:
    res = json.loads((REPORTS / "results.json").read_text())
    D = panel.load_panel()
    strict, prov = podium(res)
    picks = (strict + [p for p in prov if p not in strict])[:3]
    roles = ["Champion", "Challenger 1", "Challenger 2"]
    hold = res["hold"]
    L = [f"# Desk report, {res['generated_at'][:16].replace('T', ' ')} UTC", "",
         f"Data: {len(res['symbols'])} OKX USDT perpetuals, 1H candles, {res['data_window'][0][:10]} to "
         f"{res['data_window'][1][:10]}. Sources and download times are in `data/manifest.json`.", "",
         f"Costs in every test: {res['costs']['fee']:.2%} taker fee per fill, slippage {res['costs']['slip_major']:.2%} "
         f"(BTC, ETH) or {res['costs']['slip_alt']:.2%} (others) per fill (ESTIMATE), and funding "
         f"(OKX for the last 3 months, Binance as a proxy before that: ESTIMATE).", "",
         "## Verdict", ""]
    if strict:
        L.append(f"{len(strict)} strategies passed every check.")
    else:
        L += [f"**No strategy passed every check, so nothing is cleared for real money.** {len(prov)} passed everything "
              f"except beating BTC hold on return per unit of drawdown during the validation window, which was a bull market "
              f"(BTC {pct(hold['val']['btc']['ret'])}). They are on the podium as PROVISIONAL, for paper trading only."]
    L += ["", "## Leaderboard (walk-forward, after all costs)", "",
          "| Strategy | Regime | Validation | Holdout | 3-year return | Max DD | Sharpe | Trades | Fees x2 | Nearby | Score | Failed checks |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in sorted(res["strategies"], key=lambda s: -s["oos"]["sharpe"]):
        failed = [k for k, v in s["gates"].items() if not v]
        L.append(f"| {s['name']} | {s['regime_tag']} | {pct(s['validation']['ret'])} | {pct(s['holdout']['ret'])} | "
                 f"{pct(s['oos']['ret'])} | {pct(s['oos']['max_dd'])} | {s['oos']['sharpe']:.2f} | {s['oos']['trades']} | "
                 f"{pct(s['fees_doubled']['oos'])} | {s['nearby']['share_profitable']:.0%} | {s['score']['total']}/25 | "
                 f"{', '.join(failed) or 'none'} |")
    L += ["", f"Holding instead, over the same 3 years: BTC {pct(hold['oos']['btc']['ret'])} (max drawdown "
          f"{pct(hold['oos']['btc']['max_dd'])}); all 20 coins equally weighted {pct(hold['oos']['basket']['ret'])} "
          f"(max drawdown {pct(hold['oos']['basket']['max_dd'])}).", "",
          "Checks: " + "; ".join(f"`{k}` = {v}" for k, v in GATE_TEXT.items()) + ".", "", "## Strategy cards", ""]
    for role, s in zip(roles, picks):
        L += card(D, s, res, role if strict else f"Provisional {role.lower()}")
    L += ["## Deleted", ""]
    for s in res["strategies"]:
        if s not in picks:
            failed = [GATE_TEXT[k] for k, v in s["gates"].items() if not v]
            L.append(f"- `{s['name']}`: failed {len(failed)} checks ({'; '.join(failed)}).")
    (REPORTS / "REPORT.md").write_text("\n".join(L) + "\n")
    sel = {"cleared_for_live": bool(strict), "books": {
        k: {"strategy": s["name"], "params": s["live_params"]}
        for k, s in zip(["champion", "challenger_1", "challenger_2"], picks)}}
    (REPORTS / "selection.json").write_text(json.dumps(sel, indent=1))
    print(json.dumps(sel))


if __name__ == "__main__":
    main()
