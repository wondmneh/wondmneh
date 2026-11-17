"""Load downloaded history into wide (time x symbol) frames."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"


def manifest() -> dict:
    return json.loads((DATA / "manifest.json").read_text())


def build_panel(candles: dict[str, pd.DataFrame], funding: dict[str, pd.DataFrame]) -> SimpleNamespace:
    """candles[sym]: ts(ms), open, high, low, close, vol_usd. funding[sym]: ts(ms), rate."""
    wide = {}
    for col in ("open", "high", "low", "close", "vol_usd"):
        wide[col] = pd.DataFrame({s: c.set_index("ts")[col] for s, c in candles.items()})
    lo, hi = wide["close"].index.min(), wide["close"].index.max()
    idx = pd.date_range(pd.Timestamp(lo, unit="ms", tz="UTC"), pd.Timestamp(hi, unit="ms", tz="UTC"), freq="1h")
    out = {}
    for col, w in wide.items():
        w.index = pd.to_datetime(w.index, unit="ms", utc=True)
        out[col] = w.reindex(idx)
    f = pd.DataFrame({s: x.drop_duplicates("ts").set_index("ts")["rate"] for s, x in funding.items() if len(x)})
    f.index = pd.to_datetime(f.index, unit="ms", utc=True)
    f = f.reindex(idx).reindex(columns=out["close"].columns).fillna(0.0)
    return SimpleNamespace(open=out["open"], high=out["high"], low=out["low"], close=out["close"],
                           vol=out["vol_usd"], funding=f)


def load_panel() -> SimpleNamespace:
    syms = [s["instId"] for s in manifest()["symbols"]]
    candles = {s: pd.read_parquet(DATA / f"{s}.candles.parquet") for s in syms}
    funding = {s: pd.read_parquet(DATA / f"{s}.funding.parquet") for s in syms}
    return build_panel(candles, funding)


def truncate(D: SimpleNamespace, end) -> SimpleNamespace:
    return SimpleNamespace(**{k: v.loc[:end] for k, v in vars(D).items()})
