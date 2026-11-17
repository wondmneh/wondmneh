"""Hunter: market sweep from the downloaded history plus a live open-interest snapshot."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import panel, research, strategies
from .data import OKX, _get

REPORTS = Path(__file__).resolve().parent.parent / "reports"


def open_interest_usd() -> dict:
    d = _get(f"{OKX}/api/v5/public/open-interest", {"instType": "SWAP"}).json().get("data") or []
    return {x["instId"]: float(x["oiUsd"]) for x in d if x.get("oiUsd")}


def sweep(D) -> pd.DataFrame:
    d = strategies.htf(D, "1D")
    c = d.close.iloc[:-1]                       # completed days only
    ret = c.pct_change(fill_method=None)
    vol30 = ret.rolling(30).std() * np.sqrt(365)
    oi = open_interest_usd()
    return pd.DataFrame({
        "last": D.close.iloc[-1],
        "ret_7d": c.iloc[-1] / c.iloc[-8] - 1,
        "ret_30d": c.iloc[-1] / c.iloc[-31] - 1,
        "ret_90d": c.iloc[-1] / c.iloc[-91] - 1,
        "above_ema50": c.iloc[-1] > strategies.ema(c, 50).iloc[-1],
        "above_ema100": c.iloc[-1] > strategies.ema(c, 100).iloc[-1],
        "vol_30d_ann": vol30.iloc[-1],
        "vol_pctile_1y": vol30.iloc[-365:].rank(pct=True).iloc[-1],
        "funding_7d_ann": D.funding.iloc[-168:].sum() * 365 / 7,
        "volume_vs_30d": d.vol.iloc[-8:-1].mean() / d.vol.iloc[-31:-1].mean(),
        "open_interest_usd": pd.Series(oi).reindex(D.close.columns),
    })


def main() -> None:
    D = panel.load_panel()
    t = sweep(D)
    regime = research.btc_regime(D).iloc[-1]
    as_of = D.close.index[-1]
    pct = lambda x: f"{x:+.1%}"
    lines = [f"# Market sweep, data to {as_of:%Y-%m-%d %H:%M} UTC", "",
             "Source: OKX public REST (candles, funding, open interest), fetched by desk/data.py and desk/hunter.py.",
             f"BTC regime (trailing 60-day return): **{regime}**.", "",
             f"- Breadth: {int(t.above_ema50.sum())}/{len(t)} above their 50-day average, "
             f"{int(t.above_ema100.sum())}/{len(t)} above their 100-day average.",
             f"- Median 30-day return {pct(t.ret_30d.median())}; BTC {pct(t.ret_30d[strategies.BTC])}.",
             f"- Median 30-day volatility at the {t.vol_pctile_1y.median():.0%} percentile of its last year; "
             f"median 7-day funding {pct(t.funding_7d_ann.median())} annualised.", "",
             "| Coin | Last | 7d | 30d | 90d | >EMA50 | >EMA100 | Vol 30d | Vol pctile | Funding 7d ann. | Volume vs 30d | Open interest |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s, r in t.sort_values("ret_30d", ascending=False).iterrows():
        oi = f"${r.open_interest_usd / 1e6:,.0f}m" if pd.notna(r.open_interest_usd) else "n/a"
        lines.append(f"| {s.split('-')[0]} | {r['last']:g} | {pct(r.ret_7d)} | {pct(r.ret_30d)} | {pct(r.ret_90d)} | "
                     f"{'yes' if r.above_ema50 else 'no'} | {'yes' if r.above_ema100 else 'no'} | {r.vol_30d_ann:.0%} | "
                     f"{r.vol_pctile_1y:.0%} | {pct(r.funding_7d_ann)} | {r.volume_vs_30d:.2f}x | {oi} |")
    lines += ["", "Open interest is a live snapshot only: no free source gives 4 years of it, so no strategy here uses it."]
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "market_sweep.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:9]))


if __name__ == "__main__":
    main()
