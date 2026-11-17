"""Candle/funding store under state/ plus feed-health checks."""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from .okx import HOUR_MS

CCOLS = ["ts", "open", "high", "low", "close", "vol_usd"]


def last_closed_bar(now_ms: int) -> int:
    """Open-time (ms) of the most recently closed 1H bar."""
    return now_ms // HOUR_MS * HOUR_MS - HOUR_MS


class Feed:
    def __init__(self, state: Path, okx, cfg: dict | None = None):
        self.state, self.okx = Path(state), okx
        self.stale_ms = int((cfg or {}).get("stale_seconds", 180) * 1000)
        self.cdir, self.fdir = self.state / "candles", self.state / "funding"
        self.cdir.mkdir(parents=True, exist_ok=True)
        self.fdir.mkdir(parents=True, exist_ok=True)

    def symbols(self) -> list[str]:
        return sorted(p.name.removesuffix(".parquet") for p in self.cdir.glob("*.parquet"))

    def seed(self, data_dir: Path, syms: list[str]) -> None:
        """Copy from data/*.parquet; existing state files are never overwritten."""
        for s in syms:
            for kind, d in (("candles", self.cdir), ("funding", self.fdir)):
                src, dst = Path(data_dir) / f"{s}.{kind}.parquet", d / f"{s}.parquet"
                if src.exists() and not dst.exists():
                    pd.read_parquet(src).to_parquet(dst)

    def _path(self, kind: str, sym: str) -> Path:
        return (self.cdir if kind == "candles" else self.fdir) / f"{sym}.parquet"

    def load(self, kind: str, sym: str) -> pd.DataFrame:
        p = self._path(kind, sym)
        if p.exists():
            return pd.read_parquet(p)
        return pd.DataFrame({c: pd.Series(dtype="int64" if c == "ts" else "float64") for c in
                             (CCOLS if kind == "candles" else ["ts", "rate"])})

    def merge(self, kind: str, sym: str, new: pd.DataFrame, source: str | None = None) -> int:
        """Append rows deduped on ts (newer wins); returns the number of added timestamps."""
        if new.empty:
            return 0
        old = self.load(kind, sym)
        if source:
            new = new.assign(source=source)
        merged = pd.concat([old, new]).drop_duplicates("ts", keep="last").sort_values("ts").reset_index(drop=True)
        merged["ts"] = merged["ts"].astype("int64")
        merged.to_parquet(self._path(kind, sym))
        return len(merged) - len(old)

    def update(self, with_funding: bool = True) -> dict[str, int]:
        """Fetch closed candles (and funding) per symbol; a failing symbol is skipped, not fatal."""
        added = {}
        for s in self.symbols():
            try:
                c = self.load("candles", s)
                added[s] = self.merge("candles", s, self.okx.candles(s, int(c["ts"].max()) if len(c) else None))
                if with_funding:
                    f = self.load("funding", s)
                    self.merge("funding", s, self.okx.funding(s, int(f["ts"].max()) if len(f) else None), "okx")
            except Exception as e:  # noqa: BLE001 - network/parse errors must not kill the bot
                added[s] = -1
                print(f"feed update failed for {s}: {e}")
        return added

    def health(self, now_ms: int | None = None) -> tuple[bool, str]:
        """(ok, reason). Frozen if tickers are stale/unavailable or a closed candle is late."""
        now_ms = int(time.time() * 1000) if now_ms is None else now_ms
        try:
            t = self.okx.tickers()
        except Exception as e:  # noqa: BLE001
            return False, f"tickers unavailable: {e}"
        if not t:
            return False, "tickers empty"
        age = now_ms - max(v["ts"] for v in t.values())
        if age > self.stale_ms:
            return False, f"ticker stale {age / 1000:.0f}s"
        if now_ms - now_ms // HOUR_MS * HOUR_MS > 300_000:
            want = last_closed_bar(now_ms)
            late = [s for s in self.symbols() if (c := self.load("candles", s)).empty or int(c["ts"].max()) < want]
            if late:
                return False, f"candle missing for {len(late)} symbols (e.g. {late[0]})"
        return True, "ok"

    def panel_inputs(self):
        syms = self.symbols()
        return {s: self.load("candles", s) for s in syms}, {s: self.load("funding", s) for s in syms}
