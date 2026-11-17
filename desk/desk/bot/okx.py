"""Public OKX v5 REST client (no keys). `http_get(url, params) -> dict` is injectable for tests."""
from __future__ import annotations

import threading
import time

import pandas as pd
import requests

BASE = "https://www.okx.com"
HOUR_MS = 3_600_000
_lock, _last = threading.Lock(), [0.0]


def default_get(url: str, params: dict | None = None, min_gap: float = 0.13) -> dict:
    """Rate-limited GET with retries (OKX allows 20 requests / 2 s per IP)."""
    for attempt in range(6):
        with _lock:
            wait = _last[0] + min_gap - time.time()
            if wait > 0:
                time.sleep(wait)
            _last[0] = time.time()
        try:
            r = requests.get(url, params=params, timeout=20)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(1.5 * (attempt + 1))
                continue
            return r.json()
        except (requests.RequestException, ValueError):
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"giving up on {url} {params}")


def _data(resp: dict) -> list:
    if resp.get("code", "0") != "0":
        raise RuntimeError(f"OKX error {resp.get('code')}: {resp.get('msg')}")
    return resp.get("data") or []


def _candle_frame(rows: list) -> pd.DataFrame:
    cols = ["ts", "open", "high", "low", "close", "vol", "vol_ccy", "vol_usd", "confirm"]
    df = pd.DataFrame([r[:9] for r in rows], columns=cols)
    df = df[df["confirm"] == "1"].astype({"ts": "int64", "open": float, "high": float, "low": float,
                                          "close": float, "vol_usd": float})
    return df.drop_duplicates("ts").sort_values("ts")[["ts", "open", "high", "low", "close", "vol_usd"]].reset_index(drop=True)


class OKX:
    def __init__(self, http_get=None, base: str = BASE):
        self.get, self.base = http_get or default_get, base

    def candles(self, inst: str, since_ms: int | None = None, max_pages: int = 200) -> pd.DataFrame:
        """Closed 1H candles with ts > since_ms (all that the recent endpoint returns if None)."""
        rows = _data(self.get(f"{self.base}/api/v5/market/candles", {"instId": inst, "bar": "1H", "limit": 100}))
        out = list(rows)
        after = int(rows[-1][0]) if rows else None
        # recent page doesn't reach what we hold yet: page further back via history-candles
        while rows and since_ms is not None and after > since_ms and max_pages > 0:
            rows = _data(self.get(f"{self.base}/api/v5/market/history-candles",
                                  {"instId": inst, "bar": "1H", "after": after, "limit": 100}))
            out.extend(rows)
            after = int(rows[-1][0]) if rows else after
            max_pages -= 1
        df = _candle_frame(out)
        return df if since_ms is None else df[df["ts"] > since_ms].reset_index(drop=True)

    def tickers(self) -> dict[str, dict]:
        """instId -> {last, ts(ms)} for all swaps."""
        rows = _data(self.get(f"{self.base}/api/v5/market/tickers", {"instType": "SWAP"}))
        return {r["instId"]: {"last": float(r["last"]), "ts": int(r["ts"])} for r in rows if r.get("last")}

    def funding(self, inst: str, since_ms: int | None = None, max_pages: int = 20) -> pd.DataFrame:
        """Funding rows with ts >= since_ms (realized rate, falling back to the announced rate)."""
        out, after = [], None
        for _ in range(max_pages):
            p = {"instId": inst, "limit": 100}
            if after:
                p["after"] = after
            d = _data(self.get(f"{self.base}/api/v5/public/funding-rate-history", p))
            if not d:
                break
            out.extend((int(x["fundingTime"]), float(x["realizedRate"] or x["fundingRate"])) for x in d)
            after = d[-1]["fundingTime"]
            if since_ms is not None and int(after) <= since_ms:
                break
        df = pd.DataFrame(out, columns=["ts", "rate"]).astype({"ts": "int64", "rate": float})
        if since_ms is not None:
            df = df[df["ts"] >= since_ms]
        return df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
