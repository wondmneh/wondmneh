import numpy as np
import pandas as pd
import pytest

from desk import panel


def make_panel(hours=9000, symbols=("BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP", "XRP-USDT-SWAP"), seed=1):
    rng = np.random.default_rng(seed)
    ts = (1_700_000_000_000 // 3_600_000 * 3_600_000) + np.arange(hours) * 3_600_000
    candles, funding = {}, {}
    for i, s in enumerate(symbols):
        close = 100 * (i + 1) * np.exp(np.cumsum(rng.normal(0, 0.008, hours)))
        open_ = np.r_[close[0], close[:-1]]
        spread = np.abs(rng.normal(0, 0.004, hours)) * close
        candles[s] = pd.DataFrame({"ts": ts, "open": open_, "high": np.maximum(open_, close) + spread,
                                   "low": np.minimum(open_, close) - spread, "close": close,
                                   "vol_usd": rng.lognormal(10, 1, hours)})
        funding[s] = pd.DataFrame({"ts": ts[::8], "rate": rng.normal(0.0001, 0.0003, len(ts[::8]))})
    return panel.build_panel(candles, funding)


@pytest.fixture(scope="session")
def D():
    return make_panel()
