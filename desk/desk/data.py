"""Download real market history from free public endpoints.

Sources (recorded per file in data/manifest.json):
- Candles: OKX public REST /api/v5/market/history-candles (1H, USDT perpetual swaps).
- Funding: OKX /api/v5/public/funding-rate-history where it reaches (about 3 months),
  Binance USDT-M public archive (data.binance.vision) before that. The Binance part is
  a PROXY for OKX funding and is flagged as an estimate in the manifest.
"""
from __future__ import annotations

import io
import json
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

OKX = "https://www.okx.com"
BINANCE_ARCHIVE = "https://data.binance.vision/data/futures/um/monthly/fundingRate"
DATA = Path(__file__).resolve().parent.parent / "data"
HOUR_MS = 3_600_000

_lock = threading.Lock()
_last = [0.0]


def _get(url: str, params: dict | None = None, min_gap: float = 0.13) -> requests.Response:
    """GET with a global rate limit (OKX allows 20 requests / 2 s per IP) and retries."""
    for attempt in range(8):
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
            return r
        except requests.RequestException:
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"giving up on {url} {params}")


def pick_universe(years: int, top: int) -> list[dict]:
    """Live OKX USDT swaps listed before the history window starts, by 24h USD volume.

    Survivorship caveat: delisted contracts are not returned by this endpoint.
    """
    cutoff = int((time.time() - years * 365.25 * 86400) * 1000)
    inst = _get(f"{OKX}/api/v5/public/instruments", {"instType": "SWAP"}).json()["data"]
    tick = {t["instId"]: t for t in _get(f"{OKX}/api/v5/market/tickers", {"instType": "SWAP"}).json()["data"]}
    rows = []
    for i in inst:
        if i["settleCcy"] != "USDT" or i["state"] != "live" or int(i["listTime"]) > cutoff:
            continue
        t = tick.get(i["instId"])
        if not t or not t["last"]:
            continue
        usd = float(t["volCcy24h"]) * float(t["last"])
        rows.append({"instId": i["instId"], "listTime": int(i["listTime"]), "vol24h_usd": usd,
                     "ctVal": float(i["ctVal"]), "tickSz": float(i["tickSz"]), "lotSz": float(i["lotSz"]),
                     "minSz": float(i["minSz"])})
    rows.sort(key=lambda r: -r["vol24h_usd"])
    return rows[:top]


def fetch_candles(inst: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    out, after = [], end_ms
    while after > start_ms:
        r = _get(f"{OKX}/api/v5/market/history-candles",
                 {"instId": inst, "bar": "1H", "after": after, "limit": 100}).json()
        d = r.get("data") or []
        if not d:
            break
        out.extend(d)
        after = int(d[-1][0])
    df = pd.DataFrame(out, columns=["ts", "open", "high", "low", "close", "vol", "vol_ccy", "vol_usd", "confirm"])
    df = df[df["confirm"] == "1"].astype({"ts": "int64", "open": float, "high": float, "low": float,
                                          "close": float, "vol_usd": float})
    df = df[df["ts"] >= start_ms].drop_duplicates("ts").sort_values("ts")
    return df[["ts", "open", "high", "low", "close", "vol_usd"]].reset_index(drop=True)


def fetch_okx_funding(inst: str) -> pd.DataFrame:
    out, after = [], None
    while True:
        p = {"instId": inst, "limit": 100}
        if after:
            p["after"] = after
        d = _get(f"{OKX}/api/v5/public/funding-rate-history", p).json().get("data") or []
        if not d:
            break
        out.extend((int(x["fundingTime"]), float(x["realizedRate"] or x["fundingRate"])) for x in d)
        after = d[-1]["fundingTime"]
    return pd.DataFrame(out, columns=["ts", "rate"]).drop_duplicates("ts").sort_values("ts")


def fetch_binance_funding(inst: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    sym = inst.replace("-USDT-SWAP", "") + "USDT"
    frames = []
    for m in pd.period_range(pd.Timestamp(start_ms, unit="ms"), pd.Timestamp(end_ms, unit="ms"), freq="M"):
        url = f"{BINANCE_ARCHIVE}/{sym}/{sym}-fundingRate-{m.strftime('%Y-%m')}.zip"
        r = _get(url, min_gap=0.02)
        if r.status_code != 200:
            continue
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            f = pd.read_csv(z.open(z.namelist()[0]))
        frames.append(pd.DataFrame({"ts": f["calc_time"].astype("int64"), "rate": f["last_funding_rate"].astype(float)}))
    if not frames:
        return pd.DataFrame(columns=["ts", "rate"])
    df = pd.concat(frames)
    df["ts"] = (df["ts"] + HOUR_MS // 2) // HOUR_MS * HOUR_MS  # snap to the funding hour
    return df.drop_duplicates("ts").sort_values("ts")


def download_one(u: dict, start_ms: int, end_ms: int) -> dict:
    inst = u["instId"]
    c = fetch_candles(inst, start_ms, end_ms)
    c.to_parquet(DATA / f"{inst}.candles.parquet", index=False)
    okx_f = fetch_okx_funding(inst)
    bin_f = fetch_binance_funding(inst, start_ms, end_ms)
    okx_start = int(okx_f["ts"].min()) if len(okx_f) else end_ms
    proxy = bin_f[bin_f["ts"] < okx_start].assign(source="binance_proxy")
    f = pd.concat([proxy, okx_f.assign(source="okx")]).sort_values("ts")
    f = f[(f["ts"] >= start_ms) & (f["ts"] <= end_ms)].reset_index(drop=True)
    f.to_parquet(DATA / f"{inst}.funding.parquet", index=False)
    expected = (int(c["ts"].iloc[-1]) - int(c["ts"].iloc[0])) // HOUR_MS + 1 if len(c) else 0
    info = {
        **u,
        "candles": len(c), "missing_hours": expected - len(c),
        "first": _iso(c["ts"].iloc[0]) if len(c) else None, "last": _iso(c["ts"].iloc[-1]) if len(c) else None,
        "candle_source": f"{OKX}/api/v5/market/history-candles?instId={inst}&bar=1H",
        "funding_rows": len(f), "funding_okx_rows": len(okx_f), "funding_proxy_rows": len(proxy),
        "funding_okx_from": _iso(okx_start) if len(okx_f) else None,
        "funding_source": [f"{OKX}/api/v5/public/funding-rate-history?instId={inst}",
                           f"{BINANCE_ARCHIVE}/{inst.replace('-USDT-SWAP', '')}USDT/ (ESTIMATE: proxy for OKX)"],
        "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    print(f"{inst}: {len(c)} candles, {info['missing_hours']} missing, funding okx={len(okx_f)} proxy={len(proxy)}", flush=True)
    return info


def _iso(ms) -> str:
    return datetime.fromtimestamp(int(ms) / 1000, timezone.utc).isoformat(timespec="minutes")


def main(years: int = 4, top: int = 20) -> None:
    DATA.mkdir(exist_ok=True)
    end_ms = int(time.time() * 1000) // HOUR_MS * HOUR_MS
    start_ms = end_ms - int(years * 365.25 * 24) * HOUR_MS
    uni = pick_universe(years, top)
    print("universe:", [u["instId"] for u in uni], flush=True)
    with ThreadPoolExecutor(6) as ex:
        infos = list(ex.map(lambda u: download_one(u, start_ms, end_ms), uni))
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "window": [_iso(start_ms), _iso(end_ms)], "bar": "1H",
                "survivorship_note": "Universe = contracts live on OKX today and listed before the window. "
                                     "Delisted contracts are absent, which flatters results.",
                "symbols": infos}
    (DATA / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print("done", flush=True)


if __name__ == "__main__":
    main(*(int(a) for a in sys.argv[1:]))
