"""Auditor: walk-forward test of every strategy with costs, then the final check.

Data split (fixed before looking at any result):
- First 365 days: only ever used for parameter selection.
- Validation: 8 walk-forward folds of 91 days. Used to rank and filter strategies.
- Holdout: the last 4 folds (364 days). Looked at once, as a pass/fail confirmation.
In every fold the parameters are picked on the preceding 365 days only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from . import engine, panel, strategies

REPORTS = Path(__file__).resolve().parent.parent / "reports"
HOURS_YEAR = 8766
TRAIN, TEST, N_HOLDOUT = pd.Timedelta(days=365), pd.Timedelta(days=91), 4
MIN_TRAIN_TRADES = 10


def folds(idx) -> list[tuple]:
    """(train_start, test_start, test_end) from oldest to newest, anchored at the last bar."""
    out, end = [], idx[-1] + pd.Timedelta(hours=1)
    while end - TEST - TRAIN >= idx[0]:
        out.append((end - TEST - TRAIN, end - TEST, end))
        end -= TEST
    return out[::-1]


def sharpe(r: pd.Series) -> float:
    s = r.std()
    return float(r.mean() / s * np.sqrt(HOURS_YEAR)) if s > 0 else 0.0


def max_dd(r: pd.Series) -> float:
    eq = (1 + r).cumprod()
    return float((eq / eq.cummax() - 1).min()) if len(eq) else 0.0


def losing_streak(pnl) -> int:
    best = cur = 0
    for x in pnl:
        cur = cur + 1 if x < 0 else 0
        best = max(best, cur)
    return best


def stats(r: pd.Series, tr: pd.DataFrame, regime: pd.Series | None = None) -> dict:
    tot = float((1 + r).prod() - 1)
    years = len(r) / HOURS_YEAR
    dd = max_dd(r)
    monthly = (1 + r).groupby(r.index.strftime("%Y-%m")).prod() - 1
    tr = tr.sort_values("exit_time")
    wins, losses = tr.loc[tr.pnl > 0, "pnl"].sum(), -tr.loc[tr.pnl < 0, "pnl"].sum()
    out = {
        "ret": tot, "cagr": float((1 + tot) ** (1 / years) - 1) if years > 0 and tot > -1 else -1.0,
        "sharpe": sharpe(r), "max_dd": dd, "ret_over_dd": float(tot / -dd) if dd < 0 else 0.0,
        "worst_month": float(monthly.min()) if len(monthly) else 0.0,
        "worst_month_name": str(monthly.idxmin()) if len(monthly) else "",
        "trades": int(len(tr)), "win_rate": float((tr.pnl > 0).mean()) if len(tr) else 0.0,
        "profit_factor": float(wins / losses) if losses > 0 else 0.0,
        "losing_streak": losing_streak(tr.pnl.to_numpy()),
        "fees": float(tr.fees.sum()), "funding": float(tr.funding.sum()),
    }
    if regime is not None:
        g = np.log1p(r).groupby(regime.reindex(r.index)).sum()
        out["regime"] = {k: float(np.expm1(g.get(k, 0.0))) for k in ("bull", "bear", "chop")}
    return out


def btc_regime(D) -> pd.Series:
    """bull/bear/chop from BTC's trailing 60-day return, known at the prior daily close."""
    d = D.close[strategies.BTC].resample("1D").last()
    m = (d / d.shift(60) - 1).shift(1)
    lab = pd.Series(np.where(m > 0.2, "bull", np.where(m < -0.2, "bear", "chop")), index=d.index)
    return lab.reindex(D.close.index, method="ffill")


def run_grid(D, name: str, costs: engine.Costs, sigs: list | None = None):
    spec = strategies.REGISTRY[name]
    combos = spec.combos()
    sigs = sigs or [spec.fn(D, **p) for p in combos]
    res = []
    for s in sigs:
        r = engine.run(D, s, costs)
        res.append((r.equity.pct_change().fillna(0.0), r.trades))
    return combos, sigs, res


def in_window(tr, a, b):
    return tr[(tr.entry_time >= a) & (tr.entry_time < b)]


def walk_forward(idx, res, picks: list | None = None):
    """Stitch out-of-sample returns. `picks` reuses earlier choices (for the fee stress)."""
    fl, chosen, parts, trades = folds(idx), [], [], []
    for j, (a, b, c) in enumerate(fl):
        if picks is not None:
            best = picks[j]
        else:
            best, best_s = None, -np.inf
            for i, (r, tr) in enumerate(res):
                if len(in_window(tr, a, b)) < MIN_TRAIN_TRADES:
                    continue
                s = sharpe(r[a:b - pd.Timedelta(hours=1)])
                if s > best_s:
                    best, best_s = i, s
        chosen.append(best)
        win = idx[(idx >= b) & (idx < c)]
        if best is None:
            parts.append(pd.Series(0.0, index=win))
        else:
            parts.append(res[best][0].reindex(win))
            trades.append(in_window(res[best][1], b, c))
    r = pd.concat(parts)
    tr = pd.concat(trades) if trades else res[0][1].iloc[:0]
    return r, tr, chosen, fl


def leak_test(D, name: str, params: dict, cuts: int = 4, tail: int = 400) -> bool:
    """Signals recomputed on data cut at T must equal the full-data signals up to T."""
    full = strategies.compute(name, D, params)
    rng = np.random.default_rng(7)
    idx = D.close.index
    for pos in rng.integers(len(idx) // 2, len(idx) - 1, cuts):
        end = idx[pos]
        part = strategies.compute(name, panel.truncate(D, end), params)
        for f in ("le", "se", "lx", "sx", "sd", "tp", "tr"):
            a, b = getattr(full, f), getattr(part, f)
            if a is None:
                continue
            a, b = a.loc[:end].iloc[-tail:], b.iloc[-tail:]
            if a.dtypes.iloc[0] == bool:
                ok = (a.to_numpy() == b.to_numpy()).all()
            else:
                ok = np.allclose(a.to_numpy(float), b.to_numpy(float), rtol=1e-9, atol=0, equal_nan=True)
            if not ok:
                return False
    return True


def monte_carlo(trade_rets: np.ndarray, n: int = 2000) -> dict:
    """Bootstrap the order and mix of out-of-sample trades."""
    if len(trade_rets) < 5:
        return {"p5_ret": 0.0, "median_ret": 0.0, "p95_dd": 0.0, "p_loss": 1.0}
    rng = np.random.default_rng(11)
    draws = rng.choice(trade_rets, (n, len(trade_rets)), replace=True)
    eq = np.cumprod(1 + draws, axis=1)
    dd = (eq / np.maximum.accumulate(eq, axis=1) - 1).min(axis=1)
    tot = eq[:, -1] - 1
    return {"p5_ret": float(np.percentile(tot, 5)), "median_ret": float(np.median(tot)),
            "p95_dd": float(np.percentile(dd, 5)), "p_loss": float((tot < 0).mean())}


def band(x, edges) -> int:
    return 1 + sum(x > e for e in edges)


def score(m: dict) -> dict:
    """1-5 on each scoring axis from the brief."""
    reg = m.get("regime", {})
    bear, chop = reg.get("bear", 0.0), reg.get("chop", 0.0)
    s = {
        "profit": band(m["sharpe"], [0, 0.5, 1.0, 1.5]),
        "drawdown": band(m["max_dd"], [-0.20, -0.15, -0.10, -0.05]),
        "trades": band(m["trades"], [29, 49, 99, 199]),
        "streak": band(-m["losing_streak"], [-16, -11, -8, -5]),
        "bear_chop": 1 + 2 * (bear > 0) + 2 * (chop > 0),
    }
    s["total"] = sum(s.values())
    return s


def evaluate(D, name: str, regime: pd.Series, hold: dict) -> dict:
    idx = D.close.index
    base = engine.Costs()
    combos, sigs, res = run_grid(D, name, base)
    r, tr, chosen, fl = walk_forward(idx, res)
    _, _, res2 = run_grid(D, name, base.scaled(2), sigs)
    r2, tr2, _, _ = walk_forward(idx, res2, chosen)
    split = fl[-N_HOLDOUT][1]
    h1 = pd.Timedelta(hours=1)
    val, hol = (fl[0][1], split - h1), (split, idx[-1])
    seg = lambda x, w: x[w[0]:w[1]]
    tseg = lambda t, w: t[(t.entry_time >= w[0]) & (t.entry_time <= w[1])]
    m_val, m_hol = stats(seg(r, val), tseg(tr, val), regime), stats(seg(r, hol), tseg(tr, hol), regime)
    m_all = stats(r, tr, regime)
    # Fixed-parameter runs over validation only: does it work across the whole grid?
    near = [float((1 + seg(x[0], val)).prod() - 1) for x in res]
    near_sh = [sharpe(seg(x[0], val)) for x in res]
    mid = combos[len(combos) // 2]
    gates = {
        "unseen_validation": m_val["ret"] > 0,
        "trades_50": m_val["trades"] >= 50,
        "fees_doubled": float((1 + seg(r2, val)).prod() - 1) > 0,
        "nearby_settings": float(np.mean([x > 0 for x in near])) >= 0.7,
        "no_lookahead": leak_test(D, name, mid),
        "beats_hold_risk_adj": m_val["ret_over_dd"] > max(hold["val"]["btc"]["ret_over_dd"],
                                                         hold["val"]["basket"]["ret_over_dd"]),
    }
    passed_val = all(gates.values())
    gates["unseen_holdout"] = m_hol["ret"] > 0
    last_a = idx[-1] - TRAIN
    live = max(range(len(res)), key=lambda i: sharpe(res[i][0][last_a:])
               if len(in_window(res[i][1], last_a, idx[-1])) >= MIN_TRAIN_TRADES else -np.inf)
    return {
        "name": name, "regime_tag": strategies.REGISTRY[name].regime,
        "validation": m_val, "holdout": m_hol, "oos": m_all,
        "fees_doubled": {"validation": float((1 + seg(r2, val)).prod() - 1),
                         "holdout": float((1 + seg(r2, hol)).prod() - 1), "oos": float((1 + r2).prod() - 1)},
        "nearby": {"share_profitable": float(np.mean([x > 0 for x in near])), "median_sharpe": float(np.median(near_sh)),
                   "returns": dict(zip([json.dumps(c) for c in combos], near))},
        "monte_carlo": monte_carlo(tr.ret.to_numpy()),
        "gates": gates, "passed_validation": passed_val, "confirmed": passed_val and gates["unseen_holdout"],
        "score": score(m_all), "picks": [combos[i] if i is not None else None for i in chosen],
        "live_params": combos[live],
        "windows": {"validation": [str(val[0]), str(val[1])], "holdout": [str(hol[0]), str(hol[1])]},
        "_r": r,
    }


def hold_stats(D, regime) -> dict:
    idx, fl = D.close.index, folds(D.close.index)
    split, h1 = fl[-N_HOLDOUT][1], pd.Timedelta(hours=1)
    rets = D.close.pct_change(fill_method=None).fillna(0.0)
    series = {"btc": rets[strategies.BTC], "basket": rets.mean(axis=1)}
    empty = pd.DataFrame({"pnl": [], "fees": [], "funding": [], "exit_time": []})
    out = {}
    for seg, (a, b) in {"val": (fl[0][1], split - h1), "hol": (split, idx[-1]), "oos": (fl[0][1], idx[-1])}.items():
        out[seg] = {k: stats(v[a:b], empty, regime) for k, v in series.items()}
    return out


def main(names: list[str] | None = None) -> None:
    REPORTS.mkdir(exist_ok=True)
    D = panel.load_panel()
    regime = btc_regime(D)
    hold = hold_stats(D, regime)
    out, curves = [], {}
    for name in names or list(strategies.REGISTRY):
        e = evaluate(D, name, regime, hold)
        curves[name] = e.pop("_r")
        out.append(e)
        v, h = e["validation"], e["holdout"]
        print(f"{name:24s} val {v['ret']:+7.1%} sh {v['sharpe']:+5.2f} dd {v['max_dd']:6.1%} n {v['trades']:4d} | "
              f"hold-out {h['ret']:+7.1%} sh {h['sharpe']:+5.2f} | 2x fees {e['fees_doubled']['validation']:+7.1%} | "
              f"near {e['nearby']['share_profitable']:.0%} | "
              f"{'PASS' if e['passed_validation'] else 'fail'} {'CONFIRMED' if e['confirmed'] else ''}", flush=True)
    meta = {"generated_at": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
            "data_window": [str(D.close.index[0]), str(D.close.index[-1])], "symbols": list(D.close.columns),
            "costs": vars(engine.Costs()), "risk": vars(engine.Risk()), "hold": hold, "strategies": out}
    (REPORTS / "results.json").write_text(json.dumps(meta, indent=1, default=str))
    pd.DataFrame(curves).to_parquet(REPORTS / "oos_returns.parquet")
    print("hold validation:", {k: (round(v["ret"], 3), round(v["max_dd"], 3)) for k, v in hold["val"].items()})
    print("hold holdout:   ", {k: (round(v["ret"], 3), round(v["max_dd"], 3)) for k, v in hold["hol"].items()})


if __name__ == "__main__":
    main(sys.argv[1:] or None)
