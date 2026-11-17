"""Strategy library. Each strategy maps the 1H panel to Signals and nothing else.

Rule for every function here: a value on row t may only depend on rows <= t.
tests/test_no_lookahead.py enforces it by recomputing on truncated data.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from types import SimpleNamespace
from typing import Callable

import numpy as np
import pandas as pd

from .engine import Signals

H1 = pd.Timedelta("1h")
BTC = "BTC-USDT-SWAP"


# ---------- helpers ----------
def htf(D, rule: str) -> SimpleNamespace:
    """Aggregate the 1H panel into higher-timeframe bars labelled by their start."""
    k = dict(label="left", closed="left")
    return SimpleNamespace(open=D.open.resample(rule, **k).first(), high=D.high.resample(rule, **k).max(),
                           low=D.low.resample(rule, **k).min(), close=D.close.resample(rule, **k).last(),
                           vol=D.vol.resample(rule, **k).sum(min_count=1))


def _shift(x: pd.DataFrame, rule: str) -> pd.DataFrame:
    # A bar labelled by its start is only known at its last 1H bar. An unfinished
    # last bar lands past the end of the 1H index and is dropped by the reindex.
    x = x.copy()
    x.index = x.index + (pd.Timedelta(rule) - H1)
    return x


def ev(x: pd.DataFrame, rule: str, idx) -> pd.DataFrame:
    """Higher-timeframe boolean event -> True only on the 1H bar that closes that bar."""
    return _shift(x.astype(float), rule).reindex(idx).fillna(0.0) == 1.0


def lvl(x: pd.DataFrame, rule: str, idx) -> pd.DataFrame:
    """Higher-timeframe level -> held on the 1H index from the bar's close onward."""
    return _shift(x.astype(float), rule).reindex(idx, method="ffill")


def state(x: pd.DataFrame, rule: str, idx) -> pd.DataFrame:
    return lvl(x, rule, idx) == 1.0


def ema(x, n):
    return x.ewm(span=n, min_periods=n, adjust=False).mean()


def rsi(c, n):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def atr(b, n):
    pc = b.close.shift(1)
    tr = np.maximum(b.high - b.low, np.maximum((b.high - pc).abs(), (b.low - pc).abs()))
    return tr.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()


def col(s: pd.Series, like: pd.DataFrame) -> pd.DataFrame:
    """Broadcast one series (e.g. a BTC filter) across all symbols."""
    return pd.DataFrame({c: s for c in like.columns})


def prev(x: pd.DataFrame) -> pd.DataFrame:
    return x.shift(1, fill_value=False)


# ---------- strategies ----------
def donchian_trend(D, n, k, btc_filter=False):
    d, idx = htf(D, "1D"), D.close.index
    a = atr(d, 20)
    le = d.close > d.high.rolling(n).max().shift(1)
    se = d.close < d.low.rolling(n).min().shift(1)
    if btc_filter:
        up = col(d.close[BTC] > ema(d.close[BTC], 100), d.close)
        le, se = le & up, se & ~up
    lx = d.close < d.low.rolling(n // 2).min().shift(1)
    sx = d.close > d.high.rolling(n // 2).max().shift(1)
    return Signals(le=ev(le, "1D", idx), se=ev(se, "1D", idx), lx=ev(lx, "1D", idx), sx=ev(sx, "1D", idx),
                   sd=lvl(a * k, "1D", idx), tr=lvl(a * k, "1D", idx))


def donchian_btc_filter(D, n, k):
    return donchian_trend(D, n, k, btc_filter=True)


def squeeze_breakout(D, q, k):
    b, idx = htf(D, "4h"), D.close.index
    mid, sd_ = b.close.rolling(20).mean(), b.close.rolling(20).std()
    tight = prev((4 * sd_ / mid).rolling(120).rank(pct=True) < q)
    a = atr(b, 14)
    return Signals(le=ev(tight & (b.close > mid + 2 * sd_), "4h", idx),
                   se=ev(tight & (b.close < mid - 2 * sd_), "4h", idx),
                   lx=ev(b.close < mid, "4h", idx), sx=ev(b.close > mid, "4h", idx),
                   sd=lvl(a * k, "4h", idx), tr=lvl(a * k, "4h", idx))


def trend_pullback(D, lo, k):
    d, b, idx = htf(D, "1D"), htf(D, "4h"), D.close.index
    e20, e100 = ema(d.close, 20), ema(d.close, 100)
    up = state((d.close > e100) & (e20 > e100), "1D", idx)
    dn = state((d.close < e100) & (e20 < e100), "1D", idx)
    r, a = rsi(b.close, 14), atr(b, 14)
    le = ev((r.shift(1) < lo) & (r >= lo), "4h", idx) & up
    se = ev((r.shift(1) > 100 - lo) & (r <= 100 - lo), "4h", idx) & dn
    return Signals(le=le, se=se, lx=ev(r > 70, "4h", idx), sx=ev(r < 30, "4h", idx),
                   sd=lvl(a * k, "4h", idx), tr=lvl(a * k, "4h", idx))


def panic_snapback(D, z, hold):
    a = atr(D, 24)
    drop = (D.close - D.close.shift(6)) / a.shift(6)
    le = (drop < -z) & (rsi(D.close, 14) < 25)
    return Signals(le=le, lx=D.close > ema(D.close, 24), sd=a * 3, max_hold=hold)


def funding_extreme_fade(D, x, k):
    b, idx = htf(D, "4h"), D.close.index
    f3 = D.funding.rolling(72).sum()
    e, a = ema(b.close, 20), atr(b, 14)
    se = ev(b.close < e, "4h", idx) & (f3 > x)
    le = ev(b.close > e, "4h", idx) & (f3 < -x)
    return Signals(le=le, se=se, lx=f3 > -x / 3, sx=f3 < x / 3, sd=lvl(a * k, "4h", idx), max_hold=120)


def funding_carry_trend(D, days, k):
    d, idx = htf(D, "1D"), D.close.index
    fn = D.funding.rolling(24 * days).sum()
    e, a = ema(d.close, 50), atr(d, 20)
    le = ev(d.close > e, "1D", idx) & (fn < 0)
    lx = ev(d.close < e, "1D", idx) | (fn > 0.001)
    return Signals(le=le, lx=lx, sd=lvl(a * k, "1D", idx), tr=lvl(a * k, "1D", idx))


def volume_surge_breakout(D, vm, lb):
    a = atr(D, 24)
    surge = D.vol > vm * D.vol.rolling(168).mean().shift(1)
    le = surge & (D.close > D.high.rolling(lb).max().shift(1))
    se = surge & (D.close < D.low.rolling(lb).min().shift(1))
    return Signals(le=le, se=se, sd=a * 3, tr=a * 3, max_hold=168)


def liq_cascade_reversal(D, rm, tpm):
    # PROXY: no free 4-year liquidation feed, so a cascade is inferred from a huge
    # high-volume bar that makes a 48h extreme and closes back in the other half.
    a = atr(D, 24).shift(1)
    rng = D.high - D.low
    big = (rng > rm * a) & (D.vol > 3 * D.vol.rolling(168).mean().shift(1))
    pos = (D.close - D.low) / rng
    le = big & (D.low < D.low.rolling(48).min().shift(1)) & (pos > 0.5)
    se = big & (D.high > D.high.rolling(48).max().shift(1)) & (pos < 0.5)
    sd = (D.close - D.low).where(le, D.high - D.close) + 0.25 * a
    return Signals(le=le, se=se, sd=sd, tp=a * tpm, max_hold=48)


def btc_lead_alt_lag(D, z, hold):
    r = D.close.pct_change(fill_method=None)
    rb = r[BTC]
    sig = rb.rolling(168).std().shift(1)
    le = r.lt(0.5 * rb, axis=0) & col(rb > z * sig, r)
    se = r.gt(0.5 * rb, axis=0) & col(rb < -z * sig, r)
    le[BTC], se[BTC] = False, False
    return Signals(le=le, se=se, sd=atr(D, 24) * 2, max_hold=hold)


def xs_momentum(D, lb, k):
    d, idx = htf(D, "1D"), D.close.index
    mom = d.close / d.close.shift(lb) - 1
    top, bot = mom.rank(axis=1, ascending=False), mom.rank(axis=1, ascending=True)
    up = col(d.close[BTC] > ema(d.close[BTC], 50), d.close)
    a = atr(d, 20)
    le, se = (top <= 3) & (mom > 0) & up, (bot <= 3) & (mom < 0) & ~up
    lx, sx = (top > 6) | ~up, (bot > 6) | up
    return Signals(le=ev(le, "1D", idx), se=ev(se, "1D", idx), lx=ev(lx, "1D", idx), sx=ev(sx, "1D", idx),
                   sd=lvl(a * k, "1D", idx), tr=lvl(a * k, "1D", idx))


def xs_reversal(D, lb, k):
    d, idx = htf(D, "1D"), D.close.index
    ret = d.close / d.close.shift(lb) - 1
    le = ret.rank(axis=1, ascending=True) <= 3
    se = ret.rank(axis=1, ascending=False) <= 3
    return Signals(le=ev(le, "1D", idx), se=ev(se, "1D", idx), sd=lvl(atr(d, 20) * k, "1D", idx),
                   max_hold=24 * lb)


def ema_cross(D, fast, slow):
    b, idx = htf(D, "4h"), D.close.index
    es = ema(b.close, slow)
    above, below = ema(b.close, fast) > es, ema(b.close, fast) < es
    return Signals(le=ev(above & prev(below), "4h", idx), se=ev(below & prev(above), "4h", idx),
                   sd=lvl(atr(b, 14) * 4, "4h", idx))


def tsmom(D, lb, k):
    d, idx = htf(D, "1D"), D.close.index
    m = d.close / d.close.shift(lb) - 1
    return Signals(le=ev(m > 0, "1D", idx), se=ev(m < 0, "1D", idx), sd=lvl(atr(d, 20) * k, "1D", idx))


def bb_meanrev_range(D, er_max, k):
    b, idx = htf(D, "4h"), D.close.index
    mid, sd_ = b.close.rolling(20).mean(), b.close.rolling(20).std()
    er = (b.close - b.close.shift(30)).abs() / b.close.diff().abs().rolling(30).sum()
    flat = er < er_max
    return Signals(le=ev(flat & (b.close < mid - 2 * sd_), "4h", idx),
                   se=ev(flat & (b.close > mid + 2 * sd_), "4h", idx),
                   lx=ev(b.close >= mid, "4h", idx), sx=ev(b.close <= mid, "4h", idx),
                   sd=lvl(atr(b, 14) * k, "4h", idx), max_hold=120)


def rsi2_dip(D, thr, k):
    d, b, idx = htf(D, "1D"), htf(D, "4h"), D.close.index
    up = state(d.close > ema(d.close, 100), "1D", idx)
    le = ev(rsi(b.close, 2) < thr, "4h", idx) & up
    return Signals(le=le, lx=ev(b.close > b.close.rolling(5).mean(), "4h", idx),
                   sd=lvl(atr(b, 14) * k, "4h", idx), max_hold=120)


def nr_breakout(D, n, k):
    d, idx = htf(D, "1D"), D.close.index
    rng = d.high - d.low
    narrow = state(rng <= rng.rolling(n).min(), "1D", idx)
    hi, lo, a = lvl(d.high, "1D", idx), lvl(d.low, "1D", idx), lvl(atr(d, 20), "1D", idx)
    return Signals(le=narrow & (D.close > hi), se=narrow & (D.close < lo), sd=a * k, tr=a * k, max_hold=120)


def funding_flip(D, x, k):
    d, b, idx = htf(D, "1D"), htf(D, "4h"), D.close.index
    f1, f7 = D.funding.rolling(24).sum(), D.funding.rolling(168).sum()
    up = state(d.close > ema(d.close, 50), "1D", idx)
    at_close = ev(b.close.notna(), "4h", idx)
    le = at_close & up & (f1 < 0) & (f7.shift(24) > x)
    a = lvl(atr(d, 20) * k, "1D", idx)
    return Signals(le=le, sd=a, tr=a, max_hold=168)


def capitulation_daily(D, z, hold):
    d, idx = htf(D, "1D"), D.close.index
    r = d.close.pct_change(fill_method=None)
    le = (r < -z * r.rolling(30).std().shift(1)) & (d.vol > 2 * d.vol.rolling(30).mean().shift(1))
    return Signals(le=ev(le, "1D", idx), sd=lvl(atr(d, 20) * 2, "1D", idx), max_hold=24 * hold)


def rel_strength_breakout(D, n, k):
    d, idx = htf(D, "1D"), D.close.index
    ratio = d.close.div(d.close[BTC], axis=0)
    le = (ratio > ratio.rolling(n).max().shift(1)) & (d.close > ema(d.close, 50))
    lx = ratio < ratio.rolling(n // 2).min().shift(1)
    le[BTC] = False
    a = lvl(atr(d, 20) * k, "1D", idx)
    return Signals(le=ev(le, "1D", idx), lx=ev(lx, "1D", idx), sd=a, tr=a)


def bear_rally_short(D, hi, k):
    d, b, idx = htf(D, "1D"), htf(D, "4h"), D.close.index
    weak = (d.close < ema(d.close, 100)) & col(d.close[BTC] < ema(d.close[BTC], 100), d.close)
    r = rsi(b.close, 14)
    se = ev((r.shift(1) > hi) & (r <= hi), "4h", idx) & state(weak, "1D", idx)
    a = lvl(atr(b, 14) * k, "4h", idx)
    return Signals(le=se & False, se=se, sx=ev(r < 30, "4h", idx), sd=a, tr=a)


# ---------- registry ----------
@dataclass
class Spec:
    fn: Callable
    grid: dict            # parameter -> candidate values (kept small on purpose)
    regime: str           # trending | ranging | wild
    idea: str
    why: str              # why the edge exists and who is on the losing side
    rules: str            # entry / exit / stop in plain words
    breaks: str           # the market that breaks it
    warning: str          # earliest sign that it is fading

    def combos(self) -> list[dict]:
        keys = list(self.grid)
        return [dict(zip(keys, v)) for v in product(*self.grid.values())]


S = Spec
REGISTRY: dict[str, Spec] = {
    "donchian_trend": S(donchian_trend, {"n": [20, 40, 60], "k": [2.0, 3.0]}, "trending",
        "Buy new N-day highs and short new N-day lows.",
        "Big moves start as breakouts and holders react late; people fading the breakout pay.",
        "Daily close above the prior n-day high: long (below the n-day low: short). Exit on a close through the n/2-day opposite channel. Stop and trail k x daily ATR(20).",
        "Choppy ranges with repeated false breakouts.", "Breakouts reversing inside 3 days more than usual."),
    "donchian_btc_filter": S(donchian_btc_filter, {"n": [20, 40, 60], "k": [2.0, 3.0]}, "trending",
        "Channel breakouts, but only in the direction of BTC's 100-day trend.",
        "Alts rarely sustain moves against BTC; counter-trend breakout buyers pay.",
        "As donchian_trend, with longs only when BTC's daily close is above its EMA100 and shorts only below it.",
        "BTC whipsawing around its 100-day average.", "BTC crossing its EMA100 several times a month."),
    "squeeze_breakout": S(squeeze_breakout, {"q": [0.15, 0.25, 0.35], "k": [2.0, 3.0]}, "ranging",
        "Trade the first band break after volatility gets unusually tight.",
        "Volatility clusters, so compression precedes expansion; range sellers and short-volatility traders pay.",
        "4H Bollinger width in its lowest q share of the last 120 bars, then a 4H close outside the 2-sd band: trade that side. Exit on a close back through the 20-bar mean. Stop and trail k x 4H ATR(14).",
        "Slow grinding markets where squeezes resolve with fake-outs both ways.",
        "Win rate on first breaks dropping while squeezes get more frequent."),
    "trend_pullback": S(trend_pullback, {"lo": [35, 40, 45], "k": [2.0, 3.0]}, "trending",
        "Buy dips inside an established daily uptrend (and the mirror for downtrends).",
        "Trends persist while late sellers get shaken out on dips; the panic sellers pay.",
        "Daily close > EMA100 and EMA20 > EMA100, then 4H RSI(14) crosses back up through lo: long. Mirror for shorts. Exit at RSI > 70 (< 30). Stop and trail k x 4H ATR(14).",
        "Trend tops, where the dip is the start of the reversal.", "Dips no longer followed by new highs."),
    "panic_snapback": S(panic_snapback, {"z": [3.0, 4.0, 5.0], "hold": [12, 24, 48]}, "wild",
        "Buy a sharp 6-hour flush once it is extremely oversold.",
        "Forced sellers overshoot fair value; liquidated longs pay.",
        "1H close down more than z x ATR(24) over 6 hours and RSI(14) < 25: long. Exit on a close above EMA(24) or after hold hours. Stop 3 x ATR(24).",
        "A real regime break where the flush keeps going (exchange failure, depeg).",
        "Bounces getting smaller than the stop distance."),
    "funding_extreme_fade": S(funding_extreme_fade, {"x": [0.0015, 0.003, 0.0045], "k": [2.0, 3.0]}, "wild",
        "Fade the crowded side when funding is extreme and price stalls.",
        "Extreme funding means one side is over-leveraged and paying to stay; that crowd pays twice.",
        "3-day funding sum > x and 4H close < EMA20: short (sum < -x and close > EMA20: long). Exit when funding falls to a third of x or after 5 days. Stop k x 4H ATR(14).",
        "Parabolic runs where funding stays extreme for weeks.", "Funding extremes becoming rarer or milder."),
    "funding_carry_trend": S(funding_carry_trend, {"days": [3, 7, 14], "k": [2.0, 3.0]}, "trending",
        "Hold longs in an uptrend only while shorts are paying the funding.",
        "Negative funding in an uptrend means shorts are leaning the wrong way; they pay carry and the squeeze.",
        "Daily close > EMA50 and the funding sum over `days` < 0: long. Exit on a close < EMA50 or funding sum > 0.1%. Stop and trail k x daily ATR(20).",
        "Bear rallies, where negative funding is correct.", "Funding rarely negative during uptrends."),
    "volume_surge_breakout": S(volume_surge_breakout, {"vm": [3.0, 4.0, 6.0], "lb": [24, 48, 96]}, "trending",
        "Follow breakouts that arrive with a volume surge.",
        "Heavy volume marks new information; slow updaters pay.",
        "1H volume > vm x its 7-day average and a close beyond the prior lb-hour extreme: trade that side. Stop and trail 3 x ATR(24). Time stop 7 days.",
        "News spikes that fully retrace within hours.", "Surge bars closing far off their extremes."),
    "liq_cascade_reversal": S(liq_cascade_reversal, {"rm": [3.0, 4.0, 5.0], "tpm": [2.0, 3.0, 4.0]}, "wild",
        "Fade a liquidation-style bar that makes a 48h extreme and rejects it.",
        "Cascades are forced flow, not information; the liquidated side pays. Uses a price/volume PROXY for liquidations.",
        "1H range > rm x ATR(24), volume > 3 x its 7-day average, a new 48h low and a close in the upper half: long (mirror: short). Stop beyond the bar extreme + 0.25 ATR. Target tpm x ATR. Time stop 48h.",
        "Cascades that are the first leg of a larger collapse.", "Rejection bars failing to reach target more often."),
    "btc_lead_alt_lag": S(btc_lead_alt_lag, {"z": [2.0, 3.0, 4.0], "hold": [2, 4, 8]}, "wild",
        "When BTC jumps and an alt has not followed yet, trade the alt in BTC's direction.",
        "Price discovery happens in BTC first; stale alt quotes pay.",
        "BTC 1H return beyond z x its 7-day hourly sd while the alt moved less than half as much: trade the alt that way. Exit after hold hours. Stop 2 x ATR(24).",
        "Any market at 1H resolution if the lag is really seconds, not hours.",
        "Average catch-up move below round-trip costs."),
    "xs_momentum": S(xs_momentum, {"lb": [14, 30, 60], "k": [2.0, 3.0]}, "trending",
        "Hold the three strongest coins in a BTC uptrend, short the three weakest in a downtrend.",
        "Attention and capital flow to recent winners slowly; holders of laggards pay.",
        "Daily: top 3 by lb-day return, return > 0 and BTC > EMA50: long. Bottom 3, return < 0 and BTC < EMA50: short. Exit when the rank leaves the top (bottom) 6 or BTC flips. Stop and trail k x daily ATR(20).",
        "Sharp rotations where leaders and laggards swap.", "Rank turnover speeding up."),
    "xs_reversal": S(xs_reversal, {"lb": [3, 5, 7], "k": [2.0, 3.0]}, "ranging",
        "Buy the three worst coins of the last few days and short the three best.",
        "Short-term over-reaction reverts; momentum chasers pay.",
        "Daily: bottom 3 by lb-day return: long, top 3: short. Exit after lb days. Stop k x daily ATR(20).",
        "Trending markets where winners keep winning.", "Losers continuing lower through the holding period."),
    "ema_cross": S(ema_cross, {"fast": [20, 30, 50], "slow": [100, 150, 200]}, "trending",
        "Be long while the fast 4H average is above the slow one, short when below.",
        "Trends persist; traders anchored to old prices pay.",
        "4H EMA(fast) crosses above EMA(slow): long; crosses below: short (always reverses). Stop 4 x 4H ATR(14).",
        "Sideways markets with repeated crossings.", "Crossings per month rising."),
    "tsmom": S(tsmom, {"lb": [14, 28, 56], "k": [2.0, 3.0]}, "trending",
        "Go with the sign of each coin's own trailing return.",
        "Time-series momentum from slow reaction and herding; contrarians pay.",
        "Daily: lb-day return > 0: long, < 0: short. Reverses on a sign change. Stop k x daily ATR(20).",
        "Range-bound markets where the sign flips constantly.", "Sign flips per month rising."),
    "bb_meanrev_range": S(bb_meanrev_range, {"er_max": [0.15, 0.2, 0.3], "k": [2.0, 3.0]}, "ranging",
        "Fade band touches when the market is going nowhere.",
        "In a range, breakouts fail; breakout traders pay.",
        "4H efficiency ratio(30) < er_max and a close below the lower 2-sd band: long (above the upper: short). Exit at the 20-bar mean or after 5 days. Stop k x 4H ATR(14).",
        "The bar where a range ends and a trend begins.", "Stops hit before the mean is reached more often."),
    "rsi2_dip": S(rsi2_dip, {"thr": [5, 10, 15], "k": [2.0, 3.0]}, "trending",
        "Buy very short-term oversold readings inside a daily uptrend.",
        "Short-term liquidity shocks revert in uptrends; impatient sellers pay.",
        "Daily close > EMA100 and 4H RSI(2) < thr: long. Exit on a 4H close above its 5-bar mean or after 5 days. Stop k x 4H ATR(14).",
        "Trend tops and crashes.", "Average winner shrinking toward the fee."),
    "nr_breakout": S(nr_breakout, {"n": [4, 7, 10], "k": [1.0, 1.5, 2.0]}, "ranging",
        "After the narrowest day in n, trade the break of that day's range.",
        "Narrow days are compression; expansion follows and range traders pay.",
        "Yesterday's range was the smallest of n days; a 1H close above its high: long, below its low: short. Stop and trail k x daily ATR(20). Time stop 5 days.",
        "Low-volume drift with fake breaks both ways.", "Breaks reversing inside the same day."),
    "funding_flip": S(funding_flip, {"x": [0.001, 0.002, 0.003], "k": [2.0, 3.0]}, "trending",
        "Buy an uptrend right after crowded longs have been flushed.",
        "Once funding flips negative the weak longs are gone; late shorts pay.",
        "Daily close > EMA50, last-24h funding < 0 and the 7-day funding sum a day earlier > x: long (checked at 4H closes). Stop and trail k x daily ATR(20). Time stop 7 days.",
        "Uptrends that are ending.", "Flips followed by lower lows."),
    "capitulation_daily": S(capitulation_daily, {"z": [2.0, 2.5, 3.0], "hold": [2, 3, 5]}, "wild",
        "Buy the day after an outsized, high-volume daily drop.",
        "Capitulation is forced selling; the sellers at the low pay.",
        "Daily return below -z x its 30-day sd with volume > 2 x its 30-day average: long at the next open. Exit after hold days. Stop 2 x daily ATR(20).",
        "Multi-day collapses.", "Second-day continuation becoming common."),
    "rel_strength_breakout": S(rel_strength_breakout, {"n": [20, 30, 50], "k": [2.0, 3.0]}, "trending",
        "Buy alts whose price in BTC terms breaks to a new high.",
        "Relative strength persists as capital rotates; holders of the laggards pay.",
        "Daily alt/BTC ratio above its prior n-day high and alt close > EMA50: long. Exit when the ratio breaks its n/2-day low. Stop and trail k x daily ATR(20).",
        "Market-wide sell-offs where relative strength does not help.", "Ratio breakouts failing within a week."),
    "bear_rally_short": S(bear_rally_short, {"hi": [60, 65, 70], "k": [2.0, 3.0]}, "trending",
        "Short relief rallies while both the coin and BTC are below their 100-day averages.",
        "Bear-market rallies are short covering; late dip buyers pay.",
        "Coin and BTC daily closes < EMA100 and 4H RSI(14) crosses down through hi: short. Exit at RSI < 30. Stop and trail k x 4H ATR(14).",
        "The rally that is the real bottom.", "Rallies making higher highs."),
}


def compute(name: str, D, params: dict) -> Signals:
    return REGISTRY[name].fn(D, **params)
