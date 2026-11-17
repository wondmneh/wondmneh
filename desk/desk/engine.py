"""Portfolio backtest engine. The paper bot runs this same code, so backtest and
paper trading cannot drift apart.

Timing contract (the only place execution timing lives):
- A signal on bar t is computed from data up to and including the close of bar t.
- It is acted on at the OPEN of bar t+1, with slippage against us.
- Stops and targets are checked inside each bar from high/low. If both are touched in
  one bar the stop is assumed to fill first. Gaps through the stop fill at the open.
- Funding is charged at the funding hour to positions opened before that hour.
- Every fill pays the taker fee.

Guardian rules (optional, evaluated at each bar close): a loss of `day_loss` since the
UTC day started, `max_streak` losing trades in a row, or an external block (frozen
feed) flattens everything at the next open and stops new entries for `halt_bars`.
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
class Guard:
    day_loss: float = 0.0          # 0.03 = flatten at -3% on the UTC day; 0 disables
    max_streak: int = 0            # losing trades in a row; 0 disables
    halt_bars: int = 24


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


@dataclass
class Result:
    equity: pd.Series
    trades: pd.DataFrame
    positions: pd.DataFrame                 # still open at the end (empty when close_at_end)
    halts: pd.Series                        # bars where the Guardian tripped, with the reason
    extra: dict = field(default_factory=dict)


REASONS = {0: "signal", 1: "time", 2: "stop", 3: "target", 4: "end", 5: "guardian"}
HALTS = {1: "day_loss", 2: "loss_streak", 3: "feed_block"}


@njit(cache=True)
def _sim(o, h, l, c, fund, le, se, lx, sx, sd, tp, tr, max_hold, fee, slip,
         risk, pos_cap, gross_cap, max_pos, eq0, day, block, day_loss, max_streak, halt_bars, close_at_end):
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
    halts = np.zeros(T, np.int8)
    equity[0] = eq0
    cash = eq0
    eq_prev = eq0
    day_start = eq0
    npos = 0
    streak = 0
    halt_until = 0
    flat_now = False
    cap = 1024
    trades = np.empty((cap, 12))
    k = 0
    for t in range(1, T):
        last = close_at_end and t == T - 1
        if day[t] != day[t - 1]:
            day_start = eq_prev
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
                    if flat_now:
                        fill = o[t, n] * (1 - d * slip[n])
                        reason = 5
                    elif (d > 0 and (lx[t - 1, n] or se[t - 1, n])) or (d < 0 and (sx[t - 1, n] or le[t - 1, n])):
                        fill = o[t, n] * (1 - d * slip[n])
                        reason = 0
                    elif max_hold > 0 and t - et[n] >= max_hold:
                        fill = o[t, n] * (1 - d * slip[n])
                        reason = 1
                elif step == 1 and d == 0 and t >= halt_until and not flat_now:
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
                            fill = o[t, n] * (1 - slip[n])
                            reason = 2
                        elif l[t, n] <= stop[n]:
                            fill = stop[n] * (1 - slip[n])
                            reason = 2
                        elif not np.isnan(tpx[n]) and h[t, n] >= tpx[n]:
                            fill = tpx[n] if new[n] else max(tpx[n], o[t, n])
                            reason = 3
                    else:
                        if (not new[n]) and o[t, n] >= stop[n]:
                            fill = o[t, n] * (1 + slip[n])
                            reason = 2
                        elif h[t, n] >= stop[n]:
                            fill = stop[n] * (1 + slip[n])
                            reason = 2
                        elif not np.isnan(tpx[n]) and l[t, n] <= tpx[n]:
                            fill = tpx[n] if new[n] else min(tpx[n], o[t, n])
                            reason = 3
                    if reason < 0 and last:
                        fill = c[t, n] * (1 - d * slip[n])
                        reason = 4
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
                    net = gross_pnl - xfee - acc_fee[n] - acc_fund[n]
                    if k == cap:
                        cap *= 2
                        bigger = np.empty((cap, 12))
                        bigger[:k] = trades[:k]
                        trades = bigger
                    trades[k, 0] = n
                    trades[k, 1] = d
                    trades[k, 2] = et[n]
                    trades[k, 3] = t
                    trades[k, 4] = epx[n]
                    trades[k, 5] = fill
                    trades[k, 6] = q
                    trades[k, 7] = net
                    trades[k, 8] = xfee + acc_fee[n]
                    trades[k, 9] = acc_fund[n]
                    trades[k, 10] = reason
                    trades[k, 11] = eq_at[n]
                    k += 1
                    streak = streak + 1 if net < 0 else 0
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
        flat_now = False
        if block[t]:
            halts[t] = 3
            flat_now = True
        elif t >= halt_until:
            if day_loss > 0 and e <= day_start * (1 - day_loss):
                halts[t] = 1
            elif max_streak > 0 and streak >= max_streak:
                halts[t] = 2
            if halts[t] > 0:
                flat_now = True
                streak = 0
                halt_until = t + 1 + halt_bars
    pos = np.zeros((N, 6))
    for n in range(N):
        pos[n, 0] = qty[n]
        pos[n, 1] = epx[n]
        pos[n, 2] = stop[n]
        pos[n, 3] = tpx[n]
        pos[n, 4] = et[n]
        pos[n, 5] = lastc[n]
    return equity, trades[:k], pos, halts


def _arr(x, like: pd.DataFrame, fill, dtype):
    if x is None:
        return np.full(like.shape, fill, dtype=dtype)
    return np.ascontiguousarray(x.reindex(index=like.index, columns=like.columns).fillna(fill).to_numpy(dtype=dtype))


def run(D, sig: Signals, costs: Costs | None = None, risk: Risk | None = None, guard: Guard | None = None,
        block: pd.Series | None = None, close_at_end: bool = True) -> Result:
    costs, risk, guard = costs or Costs(), risk or Risk(), guard or Guard()
    like = D.close
    f = lambda x: np.ascontiguousarray(x.to_numpy(dtype=np.float64))
    day = (like.index.asi8 // (86_400 * 10 ** 9 if like.index.unit == "ns" else 86_400 * 10 ** 6)).astype(np.int64)
    blk = np.zeros(len(like), np.bool_) if block is None else block.reindex(like.index).fillna(False).to_numpy(np.bool_)
    eq, tr, pos, halts = _sim(
        f(D.open), f(D.high), f(D.low), f(D.close), f(D.funding),
        _arr(sig.le, like, False, np.bool_), _arr(sig.se, like, False, np.bool_),
        _arr(sig.lx, like, False, np.bool_), _arr(sig.sx, like, False, np.bool_),
        _arr(sig.sd, like, np.nan, np.float64), _arr(sig.tp, like, np.nan, np.float64),
        _arr(sig.tr, like, np.nan, np.float64), int(sig.max_hold), costs.fee, costs.slip(like.columns),
        risk.risk_per_trade, risk.max_pos_lev, risk.max_gross_lev, risk.max_positions, risk.equity,
        day, blk, guard.day_loss, guard.max_streak, guard.halt_bars, close_at_end)
    t = pd.DataFrame(tr, columns=["n", "dir", "et", "xt", "entry", "exit", "qty", "pnl", "fees", "funding",
                                  "reason", "eq_at_entry"])
    t["symbol"] = like.columns[t["n"].astype(int)]
    t["entry_time"] = like.index[t["et"].astype(int)]
    t["exit_time"] = like.index[t["xt"].astype(int)]
    t["reason"] = t["reason"].astype(int).map(REASONS)
    t["ret"] = t["pnl"] / t["eq_at_entry"]
    p = pd.DataFrame(pos, columns=["qty", "entry", "stop", "target", "et", "last"], index=like.columns)
    p = p[p["qty"] != 0].copy()
    p["entry_time"] = like.index[p["et"].astype(int)]
    p["unrealized"] = p["qty"] * (p["last"] - p["entry"])
    hs = pd.Series(halts, index=like.index)
    return Result(pd.Series(eq, index=like.index), t.drop(columns=["n", "et", "xt"]),
                  p.drop(columns=["et"]), hs[hs > 0].map(HALTS))
