"""Portfolio backtest engine.

Timing contract (the only place execution timing lives):
- A signal on bar t is computed from data up to and including the close of bar t.
- It is acted on at the OPEN of bar t+1, with slippage against us.
- Stops and targets are checked inside each bar from high/low. If both are touched in
  one bar the stop is assumed to fill first. Gaps through the stop fill at the open.
- Funding is charged at the funding hour to positions opened before that hour.
- Every fill pays the taker fee.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from numba import njit


@dataclass
class Costs:
    fee: float = 0.0005            # OKX regular-tier taker fee per side
    slip_major: float = 0.0002     # ESTIMATE: slippage per fill, BTC and ETH
    slip_alt: float = 0.0005       # ESTIMATE: slippage per fill, everything else

    def scaled(self, m: float) -> "Costs":
        return Costs(self.fee * m, self.slip_major * m, self.slip_alt * m)

    def slip(self, symbols) -> np.ndarray:
        return np.array([self.slip_major if s.split("-")[0] in ("BTC", "ETH") else self.slip_alt for s in symbols])


@dataclass
class Risk:
    equity: float = 10_000.0
    risk_per_trade: float = 0.005  # fraction of equity lost if the stop is hit
    max_pos_lev: float = 1.0       # cap on one position's notional / equity
    max_gross_lev: float = 3.0     # cap on total notional / equity
    max_positions: int = 8


@dataclass
class Signals:
    """All frames share the 1H panel index. Missing pieces mean 'not used'."""
    le: pd.DataFrame                        # long entry
    se: pd.DataFrame | None = None          # short entry
    lx: pd.DataFrame | None = None          # long exit
    sx: pd.DataFrame | None = None          # short exit
    sd: pd.DataFrame | None = None          # stop distance in price units (required)
    tp: pd.DataFrame | None = None          # take-profit distance in price units
    tr: pd.DataFrame | None = None          # trailing-stop distance in price units
    max_hold: int = 0                       # hours, 0 = unlimited
    extra: dict = field(default_factory=dict)


REASONS = {0: "signal", 1: "time", 2: "stop", 3: "target", 4: "end"}


@njit(cache=True)
def _sim(o, h, l, c, fund, le, se, lx, sx, sd, tp, tr, max_hold, fee, slip,
         risk, pos_cap, gross_cap, max_pos, eq0):
    T, N = o.shape
    qty = np.zeros(N)
    epx = np.zeros(N)
    stop = np.zeros(N)
    tpx = np.full(N, np.nan)
    et = np.zeros(N, np.int64)
    acc_fee = np.zeros(N)
    acc_fund = np.zeros(N)
    eq_at = np.zeros(N)
    lastc = np.zeros(N)
    new = np.zeros(N, np.bool_)
    equity = np.empty(T)
    equity[0] = eq0
    cash = eq0
    eq_prev = eq0
    npos = 0
    cap = 1024
    trades = np.empty((cap, 12))
    k = 0
    for t in range(1, T):
        last = t == T - 1
        for step in range(3):
            for n in range(N):
                if np.isnan(o[t, n]):
                    continue
                if step == 0:
                    new[n] = False
                d = 0.0
                if qty[n] > 0:
                    d = 1.0
                elif qty[n] < 0:
                    d = -1.0
                fill = np.nan
                reason = -1
                if step == 0 and d != 0:
                    if fund[t, n] != 0:
                        f = qty[n] * o[t, n] * fund[t, n]
                        cash -= f
                        acc_fund[n] += f
                    if (d > 0 and (lx[t - 1, n] or se[t - 1, n])) or (d < 0 and (sx[t - 1, n] or le[t - 1, n])):
                        fill = o[t, n] * (1 - d * slip[n])
                        reason = 0
                    elif max_hold > 0 and t - et[n] >= max_hold:
                        fill = o[t, n] * (1 - d * slip[n])
                        reason = 1
                elif step == 1 and d == 0:
                    s = sd[t - 1, n]
                    nd = 0.0
                    if le[t - 1, n] and not se[t - 1, n]:
                        nd = 1.0
                    elif se[t - 1, n] and not le[t - 1, n]:
                        nd = -1.0
                    if nd != 0 and s > 0 and npos < max_pos and eq_prev > 0:
                        px = o[t, n] * (1 + nd * slip[n])
                        if s < px:
                            q = min(risk * eq_prev / s, pos_cap * eq_prev / px)
                            gross = 0.0
                            for m in range(N):
                                gross += abs(qty[m]) * lastc[m]
                            if gross + q * px <= gross_cap * eq_prev:
                                qty[n] = nd * q
                                epx[n] = px
                                stop[n] = px - nd * s
                                tpx[n] = px + nd * tp[t - 1, n] if tp[t - 1, n] > 0 else np.nan
                                et[n] = t
                                acc_fee[n] = q * px * fee
                                cash -= acc_fee[n]
                                acc_fund[n] = 0.0
                                eq_at[n] = eq_prev
                                new[n] = True
                                npos += 1
                elif step == 2 and d != 0:
                    if d > 0:
                        if (not new[n]) and o[t, n] <= stop[n]:
                            fill = o[t, n] * (1 - slip[n]); reason = 2
                        elif l[t, n] <= stop[n]:
                            fill = stop[n] * (1 - slip[n]); reason = 2
                        elif not np.isnan(tpx[n]) and h[t, n] >= tpx[n]:
                            fill = max(tpx[n], o[t, n]) if not new[n] else tpx[n]
                            reason = 3
                    else:
                        if (not new[n]) and o[t, n] >= stop[n]:
                            fill = o[t, n] * (1 + slip[n]); reason = 2
                        elif h[t, n] >= stop[n]:
                            fill = stop[n] * (1 + slip[n]); reason = 2
                        elif not np.isnan(tpx[n]) and l[t, n] <= tpx[n]:
                            fill = min(tpx[n], o[t, n]) if not new[n] else tpx[n]
                            reason = 3
                    if reason < 0 and last:
                        fill = c[t, n] * (1 - d * slip[n]); reason = 4
                    if reason < 0 and tr[t, n] > 0:
                        if d > 0:
                            stop[n] = max(stop[n], c[t, n] - tr[t, n])
                        else:
                            stop[n] = min(stop[n], c[t, n] + tr[t, n])
                if reason >= 0:
                    q = abs(qty[n])
                    xfee = q * fill * fee
                    gross_pnl = qty[n] * (fill - epx[n])
                    cash += gross_pnl - xfee
                    if k == cap:
                        cap *= 2
                        bigger = np.empty((cap, 12))
                        bigger[:k] = trades[:k]
                        trades = bigger
                    trades[k, 0] = n; trades[k, 1] = d; trades[k, 2] = et[n]; trades[k, 3] = t
                    trades[k, 4] = epx[n]; trades[k, 5] = fill; trades[k, 6] = q
                    trades[k, 7] = gross_pnl - xfee - acc_fee[n] - acc_fund[n]
                    trades[k, 8] = xfee + acc_fee[n]; trades[k, 9] = acc_fund[n]
                    trades[k, 10] = reason; trades[k, 11] = eq_at[n]
                    k += 1
                    qty[n] = 0.0
                    tpx[n] = np.nan
                    npos -= 1
                if step == 2:
                    lastc[n] = c[t, n]
        e = cash
        for n in range(N):
            if qty[n] != 0:
                e += qty[n] * (lastc[n] - epx[n])
        equity[t] = e
        eq_prev = e
    return equity, trades[:k]


def _arr(x, like: pd.DataFrame, fill, dtype):
    if x is None:
        return np.full(like.shape, fill, dtype=dtype)
    return np.ascontiguousarray(x.reindex(index=like.index, columns=like.columns).fillna(fill).to_numpy(dtype=dtype))


def run(D, sig: Signals, costs: Costs | None = None, risk: Risk | None = None):
    """Returns (equity Series, trades DataFrame)."""
    costs, risk = costs or Costs(), risk or Risk()
    like = D.close
    f = lambda x: np.ascontiguousarray(x.to_numpy(dtype=np.float64))
    eq, tr = _sim(f(D.open), f(D.high), f(D.low), f(D.close), f(D.funding),
                  _arr(sig.le, like, False, np.bool_), _arr(sig.se, like, False, np.bool_),
                  _arr(sig.lx, like, False, np.bool_), _arr(sig.sx, like, False, np.bool_),
                  _arr(sig.sd, like, np.nan, np.float64), _arr(sig.tp, like, np.nan, np.float64),
                  _arr(sig.tr, like, np.nan, np.float64), int(sig.max_hold), costs.fee,
                  costs.slip(like.columns), risk.risk_per_trade, risk.max_pos_lev, risk.max_gross_lev,
                  risk.max_positions, risk.equity)
    t = pd.DataFrame(tr, columns=["n", "dir", "et", "xt", "entry", "exit", "qty", "pnl", "fees", "funding",
                                  "reason", "eq_at_entry"])
    t["symbol"] = like.columns[t["n"].astype(int)]
    t["entry_time"] = like.index[t["et"].astype(int)]
    t["exit_time"] = like.index[t["xt"].astype(int)]
    t["reason"] = t["reason"].astype(int).map(REASONS)
    t["ret"] = t["pnl"] / t["eq_at_entry"]
    return pd.Series(eq, index=like.index), t.drop(columns=["n", "et", "xt"])
