"""Shared synthetic fixtures for bot tests (no network)."""
import numpy as np
import pandas as pd

H = 3_600_000
CFG = {
    "mode": "paper", "exchange": "okx",
    "books": {"champion": {"strategy": "donchian_trend", "params": {"n": 5, "k": 2.0}},
              "alt": {"strategy": "ema_cross", "params": {"fast": 12, "slow": 48}}},
    "risk": {"equity": 10000, "risk_per_trade": 0.005, "max_pos_lev": 1.0, "max_gross_lev": 3.0, "max_positions": 8},
    "costs": {"fee": 0.0005, "slip_major": 0.0002, "slip_alt": 0.0005},
    "guard": {"day_loss": 0.03, "max_streak": 3, "halt_bars": 24},
    "feed": {"poll_seconds": 20, "stale_seconds": 180},
    "paper_start": None,
}
SYMS = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP"]
END_BAR = pd.Timestamp("2026-03-01 00:00", tz="UTC")  # open of the last closed bar


def synth(n_bars=2400, seed=0, end=END_BAR):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(end=end, periods=n_bars, freq="1h")
    candles, funding = {}, {}
    for s in SYMS:
        c = 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.012, n_bars)))
        o = np.r_[c[0], c[:-1]]
        hi = np.maximum(o, c) * (1 + rng.uniform(0, 0.004, n_bars))
        lo = np.minimum(o, c) * (1 - rng.uniform(0, 0.004, n_bars))
        candles[s] = pd.DataFrame({"ts": (idx.as_unit("ms").asi8).astype("int64"), "open": o, "high": hi, "low": lo,
                                   "close": c, "vol_usd": rng.uniform(1e6, 2e6, n_bars)})
        f_idx = idx[idx.hour % 8 == 0]
        funding[s] = pd.DataFrame({"ts": (f_idx.as_unit("ms").asi8).astype("int64"), "rate": rng.normal(0, 1e-4, len(f_idx)),
                                   "source": "okx"})
    return candles, funding


def ms(ts) -> int:
    return int(pd.Timestamp(ts).timestamp() * 1000)
