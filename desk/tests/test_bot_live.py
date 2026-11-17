import base64
import hashlib
import hmac
import json

import pytest

from desk.bot.live import LiveClient, LiveGateError, sign

KEYS = {"OKX_API_KEY": "k", "OKX_API_SECRET": "s3cret", "OKX_API_PASSPHRASE": "pw"}


def test_gate_requires_both_conditions():
    with pytest.raises(LiveGateError):
        LiveClient({"mode": "paper"}, env={**KEYS, "DESK_GO_LIVE": "yes"})
    with pytest.raises(LiveGateError):
        LiveClient({"mode": "live"}, env=dict(KEYS))
    with pytest.raises(LiveGateError):
        LiveClient({"mode": "live"}, env={**KEYS, "DESK_GO_LIVE": "no"})
    with pytest.raises(LiveGateError):
        LiveClient({"mode": "live"}, env={"DESK_GO_LIVE": "yes"})
    LiveClient({"mode": "live"}, env={**KEYS, "DESK_GO_LIVE": "yes"})


def test_signing_matches_hand_computed_hmac():
    ts, body = "2020-12-08T09:08:57.715Z", '{"a":"1"}'
    expected = base64.b64encode(hmac.new(b"s3cret", (ts + "POST" + "/api/v5/trade/order" + body).encode(),
                                         hashlib.sha256).digest()).decode()
    assert sign("s3cret", ts, "post", "/api/v5/trade/order", body) == expected
    # fixed vector computed independently: HMAC-SHA256("key", "msg") base64
    assert sign("key", "m", "S", "g", "") == base64.b64encode(hmac.new(b"key", b"mSg", hashlib.sha256).digest()).decode()


def test_order_payload_and_demo_header():
    sent = {}
    c = LiveClient({"mode": "live"}, env={**KEYS, "DESK_GO_LIVE": "yes"}, demo=True,
                   http_post=lambda url, headers, body: sent.update(url=url, headers=headers, body=body) or {"code": "0"})
    c.place_limit_with_stop("BTC-USDT-SWAP", "buy", "1", "100", "95")
    b = json.loads(sent["body"])
    assert sent["url"].endswith("/api/v5/trade/order")
    assert b["attachAlgoOrds"] == [{"slTriggerPx": "95", "slOrdPx": "-1"}] and b["ordType"] == "limit"
    assert sent["headers"]["x-simulated-trading"] == "1"
    assert sent["headers"]["OK-ACCESS-SIGN"] == sign("s3cret", sent["headers"]["OK-ACCESS-TIMESTAMP"], "POST",
                                                     "/api/v5/trade/order", sent["body"])
