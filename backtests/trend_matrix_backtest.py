#!/usr/bin/env python3
"""Backtest of the "Trend Matrix — Replica" Pine indicator.

Trades exactly what the indicator draws: on a confirmed trend flip, enter at the
bar close, stop = risk x ATR away, target = reward x risk away. Each signal is
an independent trade. If a bar touches both stop and target, the stop is assumed
to have been hit first.

    python3 backtests/trend_matrix_backtest.py
"""
import json
import math
import os
import sys
import time
import urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data")

# indicator defaults
LEN_BASE, SLOPE_SM, ATR_LEN, ATR_MULT, RR = 50, 3, 14, 1.0, 2.0

# (label, source, symbol, round-trip cost as a fraction of price)
MARKETS = [
    ("BTCUSDT", "binance", "BTCUSDT", 0.0010),
    ("ETHUSDT", "binance", "ETHUSDT", 0.0010),
    ("EURUSD", "yahoo", "EURUSD=X", 0.00010),
    ("GBPUSD", "yahoo", "GBPUSD=X", 0.00012),
    ("XAUUSD (gold fut.)", "yahoo", "GC=F", 0.00015),
]
BINANCE_TF = {"15m": 730, "1h": 1460, "4h": 2190, "1d": 3000}  # days of history
YAHOO_TF = {"15m": ("15m", "60d"), "1h": ("1h", "730d"), "1d": ("1d", "10y")}


# ───────────────────────────── data ─────────────────────────────
def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))


def fetch_binance(symbol, tf, days):
    end = int(time.time() * 1000)
    start = end - days * 86400_000
    rows = []
    while start < end:
        chunk = _get("https://data-api.binance.vision/api/v3/klines?symbol=%s&interval=%s"
                     "&startTime=%d&limit=1000" % (symbol, tf, start))
        if not chunk:
            break
        rows += [[c[0] / 1000, float(c[1]), float(c[2]), float(c[3]), float(c[4])] for c in chunk]
        start = chunk[-1][0] + 1
        if len(chunk) < 1000:
            break
    return np.array(rows[:-1])  # drop the still-forming bar


def fetch_yahoo(symbol, interval, rng):
    d = _get("https://query1.finance.yahoo.com/v8/finance/chart/%s?interval=%s&range=%s"
             % (symbol, interval, rng))["chart"]["result"][0]
    q = d["indicators"]["quote"][0]
    rows = [[t, o, h, l, c] for t, o, h, l, c in
            zip(d["timestamp"], q["open"], q["high"], q["low"], q["close"])
            if None not in (o, h, l, c) and h > l]
    return np.array(rows[:-1])


def resample(bars, seconds):
    out, key = [], None
    for t, o, h, l, c in bars:
        k = int(t // seconds)
        if k != key:
            out.append([k * seconds, o, h, l, c])
            key = k
        else:
            out[-1][2] = max(out[-1][2], h)
            out[-1][3] = min(out[-1][3], l)
            out[-1][4] = c
    return np.array(out)


def load(source, symbol, tf):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, "%s_%s.npy" % (symbol.replace("=", ""), tf))
    if os.path.exists(path):
        return np.load(path)
    if source == "binance":
        bars = fetch_binance(symbol, tf, BINANCE_TF[tf])
    elif tf == "4h":
        bars = resample(load(source, symbol, "1h"), 4 * 3600)
    else:
        bars = fetch_yahoo(symbol, *YAHOO_TF[tf])
    np.save(path, bars)
    return bars


# ───────────────────────────── Pine built-ins ─────────────────────────────
def wma(x, n):
    out = np.full(len(x), np.nan)
    w = np.arange(1, n + 1, dtype=float)
    v = np.lib.stride_tricks.sliding_window_view(x, n) @ w / w.sum()
    out[n - 1:] = v
    return out


def hma(x, n):
    return wma(2 * wma(x, n // 2) - wma(x, n), int(math.floor(math.sqrt(n))))


def _smooth(x, n, alpha):
    """Pine ta.ema / ta.rma: seeded with the SMA of the first n valid values."""
    out = np.full(len(x), np.nan)
    valid = np.flatnonzero(~np.isnan(x))
    if len(valid) < n:
        return out
    s = valid[0] + n - 1
    prev = out[s] = x[valid[0]:s + 1].mean()
    for i in range(s + 1, len(x)):
        prev = out[i] = alpha * x[i] + (1 - alpha) * prev
    return out


def ema(x, n):
    return _smooth(x, n, 2.0 / (n + 1))


def atr(h, l, c, n):
    pc = np.roll(c, 1)
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    tr[0] = h[0] - l[0]
    return _smooth(tr, n, 1.0 / n)


# ───────────────────────────── strategy ─────────────────────────────
def backtest(bars, cost, len_base=LEN_BASE, rr=RR, atr_mult=ATR_MULT):
    """Returns a list of (direction, gross R, net R, exit index)."""
    h, l, c = bars[:, 2], bars[:, 3], bars[:, 4]
    a = atr(h, l, c, ATR_LEN)
    base = hma(c, len_base)
    diff = np.full(len(c), np.nan)
    diff[1:] = base[1:] - base[:-1]
    slope = ema(diff, SLOPE_SM)
    with np.errstate(invalid="ignore"):
        up = (c > base) & (slope > 0)
        dn = (c < base) & (slope < 0)
    long_sig = up & ~np.roll(up, 1)
    short_sig = dn & ~np.roll(dn, 1)
    long_sig[0] = short_sig[0] = False

    trades = []
    n = len(c)
    for i in np.flatnonzero(long_sig | short_sig):
        if np.isnan(a[i]):
            continue
        d = 1 if long_sig[i] else -1
        risk = a[i] * atr_mult
        entry = c[i]
        target, stop = entry + d * risk * rr, entry - d * risk
        cost_r = cost * entry / risk
        for j in range(i + 1, n):
            hit_stop = l[j] <= stop if d == 1 else h[j] >= stop
            hit_tgt = h[j] >= target if d == 1 else l[j] <= target
            if hit_stop:
                trades.append((d, -1.0, -1.0 - cost_r, j))
                break
            if hit_tgt:
                trades.append((d, rr, rr - cost_r, j))
                break
    return trades


def stats(trades, rr=RR):
    if not trades:
        return None
    t = sorted(trades, key=lambda x: x[3])
    gross = np.array([x[1] for x in t])
    net = np.array([x[2] for x in t])
    eq = np.cumsum(net)
    dd = (np.maximum.accumulate(np.concatenate([[0], eq])) - np.concatenate([[0], eq])).max()
    wins, losses = net[net > 0].sum(), -net[net < 0].sum()
    return dict(n=len(t), win=100 * (gross > 0).mean(), gross=gross.mean(), net=net.mean(),
                total=net.sum(), pf=wins / losses if losses else float("inf"), dd=dd)


def fmt(label, tf, bars, s):
    days = (bars[-1, 0] - bars[0, 0]) / 86400
    span = "%.1fy" % (days / 365) if days > 400 else "%dd" % days
    if s is None:
        return "%-19s %-4s %6s %6s" % (label, tf, span, "0")
    return "%-19s %-4s %6s %6d %6.1f%% %+8.3f %+8.3f %+9.1f %6.2f %7.1f" % (
        label, tf, span, s["n"], s["win"], s["gross"], s["net"], s["total"], s["pf"], s["dd"])


def main():
    datasets = []
    for label, source, symbol, cost in MARKETS:
        for tf in ("15m", "1h", "4h", "1d"):
            try:
                bars = load(source, symbol, tf)
            except Exception as e:
                print("skip %s %s: %s" % (label, tf, e), file=sys.stderr)
                continue
            if len(bars) > 300:
                datasets.append((label, tf, bars, cost))

    print("Default settings: HMA %d, risk %.1f x ATR(%d), reward %.1fR. Break-even win rate = %.1f%%"
          % (LEN_BASE, ATR_MULT, ATR_LEN, RR, 100 / (1 + RR)))
    print("%-19s %-4s %6s %6s %7s %8s %8s %9s %6s %7s" % (
        "market", "tf", "span", "trades", "win", "grossR", "netR", "totalR", "PF", "maxDD_R"))
    pooled, by_dir = [], {1: [], -1: []}
    for label, tf, bars, cost in datasets:
        tr = backtest(bars, cost)
        pooled += tr
        for x in tr:
            by_dir[x[0]].append(x)
        print(fmt(label, tf, bars, stats(tr)))

    s = stats(pooled)
    print("\nAll markets pooled: %d trades, win %.1f%%, gross %+.3fR/trade, net %+.3fR/trade"
          % (s["n"], s["win"], s["gross"], s["net"]))
    for d, name in ((1, "long "), (-1, "short")):
        s = stats(by_dir[d])
        print("  %s: %d trades, win %.1f%%, gross %+.3fR, net %+.3fR"
              % (name, s["n"], s["win"], s["gross"], s["net"]))

    print("\nSensitivity, all markets pooled: net R per trade (win %)")
    rrs = (1.0, 1.5, 2.0, 3.0)
    print("%-10s" % "HMA \\ RR" + "".join("%16.1f" % r for r in rrs))
    for lb in (20, 35, 50, 80, 120, 200):
        row = "%-10d" % lb
        for r in rrs:
            tr = []
            for _, _, bars, cost in datasets:
                tr += backtest(bars, cost, len_base=lb, rr=r)
            s = stats(tr)
            row += "%+9.3f (%4.1f%%)" % (s["net"], s["win"])
        print(row)


if __name__ == "__main__":
    main()
