import pandas as pd

from desk.bot.feed import Feed
from desk.bot.okx import OKX
from tests.test_bot_common import H, ms


def row(ts, c, confirm="1"):
    return [str(ts), str(c), str(c + 1), str(c - 1), str(c), "5", "6", "7000", confirm]


def fake_http(store):
    calls = []

    def get(url, params=None):
        calls.append((url.split("/api/v5/")[1], dict(params or {})))
        path = url.split("/api/v5/")[1]
        if path == "market/candles":
            return {"code": "0", "data": store["recent"]}
        if path == "market/history-candles":
            older = [r for r in store["history"] if int(r[0]) < int(params["after"])]
            return {"code": "0", "data": older[:100]}
        if path == "market/tickers":
            return {"code": "0", "data": store["tickers"]}
        if path == "public/funding-rate-history":
            return {"code": "0", "data": store["funding"]}
        raise AssertionError(path)
    get.calls = calls
    return get


def test_candles_only_confirmed_and_sorted():
    t0 = ms("2026-01-01")
    store = {"recent": [row(t0 + 2 * H, 12, "0"), row(t0 + H, 11), row(t0, 10)]}
    df = OKX(fake_http(store)).candles("X")
    assert list(df["ts"]) == [t0, t0 + H] and list(df["close"]) == [10.0, 11.0]
    assert list(df["vol_usd"]) == [7000.0, 7000.0]


def test_candles_history_paging_to_since():
    t0 = ms("2026-01-01")
    allrows = [row(t0 + i * H, i) for i in range(300)][::-1]
    store = {"recent": allrows[:100], "history": allrows[100:]}
    http = fake_http(store)
    df = OKX(http).candles("X", since_ms=t0 + 120 * H)
    assert list(df["ts"]) == [t0 + i * H for i in range(121, 300)]
    assert any(c[0] == "market/history-candles" for c in http.calls)


def test_tickers_and_funding_parse():
    store = {"tickers": [{"instId": "A", "last": "2.5", "ts": "1000"}, {"instId": "B", "last": "", "ts": "1"}],
             "funding": [{"fundingTime": "2000", "realizedRate": "", "fundingRate": "0.0001"},
                         {"fundingTime": "1000", "realizedRate": "0.0002", "fundingRate": "0.0003"}]}
    o = OKX(fake_http(store))
    assert o.tickers() == {"A": {"last": 2.5, "ts": 1000}}
    f = o.funding("A")
    assert list(f["ts"]) == [1000, 2000] and list(f["rate"]) == [0.0002, 0.0001]


def seeded_feed(tmp_path, okx, t0):
    f = Feed(tmp_path, okx, {"stale_seconds": 180})
    f.merge("candles", "X", pd.DataFrame({"ts": [t0], "open": [1.0], "high": [2.0], "low": [0.5], "close": [1.5], "vol_usd": [9.0]}))
    return f


def test_feed_incremental_update_and_dedupe(tmp_path):
    t0 = ms("2026-01-01")
    store = {"recent": [row(t0 + 2 * H, 12), row(t0 + H, 11), row(t0, 10)],
             "funding": [{"fundingTime": str(t0 + H), "realizedRate": "0.0001", "fundingRate": "0"}]}
    feed = seeded_feed(tmp_path, OKX(fake_http(store)), t0)
    assert feed.update() == {"X": 2}
    assert feed.update() == {"X": 0}  # nothing new, no duplicates
    c = feed.load("candles", "X")
    assert list(c["ts"]) == [t0, t0 + H, t0 + 2 * H]
    assert float(c.loc[c.ts == t0, "close"].iloc[0]) == 1.5  # seeded row kept
    assert len(feed.load("funding", "X")) == 1


def test_feed_seed_does_not_overwrite(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    pd.DataFrame({"ts": [1], "open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "vol_usd": [1.0]}).to_parquet(data / "X.candles.parquet")
    feed = Feed(tmp_path / "state", OKX(fake_http({})), {})
    feed.seed(data, ["X"])
    feed.merge("candles", "X", pd.DataFrame({"ts": [2], "open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "vol_usd": [1.0]}))
    feed.seed(data, ["X"])
    assert len(feed.load("candles", "X")) == 2


def test_frozen_feed_detection(tmp_path):
    hour = ms("2026-01-01 10:00")
    now = hour + 10 * 60_000  # 10 minutes past the hour
    feed = seeded_feed(tmp_path, None, hour - H)  # holds bar 09:00 -> missing for want=09:00? (held)
    fresh = {"tickers": [{"instId": "X", "last": "1", "ts": str(now - 5_000)}]}
    feed.okx = OKX(fake_http(fresh))
    assert feed.health(now) == (True, "ok")
    feed.okx = OKX(fake_http({"tickers": [{"instId": "X", "last": "1", "ts": str(now - 600_000)}]}))
    ok, why = feed.health(now)
    assert not ok and "stale" in why
    # candle for the last closed bar (09:00) missing 5+ minutes after the hour
    feed2 = seeded_feed(tmp_path / "b", OKX(fake_http(fresh)), hour - 2 * H)
    ok, why = feed2.health(now)
    assert not ok and "candle missing" in why

    def boom(url, params=None):
        raise RuntimeError("net down")
    feed.okx = OKX(boom)
    ok, why = feed.health(now)
    assert not ok and "tickers unavailable" in why
