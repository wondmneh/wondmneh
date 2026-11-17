"""OKX v5 private (trading) client for LATER use. NEVER called in paper mode.

!!! UNTESTED against the real exchange. Request signing is checked only against a hand-computed
HMAC vector; order payloads follow the OKX v5 docs but have never been sent. Use demo mode first.

Hard gate: construction raises unless config mode == "live" AND env DESK_GO_LIVE == "yes".
Keys come only from env OKX_API_KEY / OKX_API_SECRET / OKX_API_PASSPHRASE and are never logged.
No withdrawal or transfer endpoints are implemented, by design.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone

import requests

BASE = "https://www.okx.com"


class LiveGateError(RuntimeError):
    pass


def sign(secret: str, ts: str, method: str, path: str, body: str = "") -> str:
    """base64(HMAC-SHA256(secret, timestamp + METHOD + requestPath + body))."""
    return base64.b64encode(hmac.new(secret.encode(), (ts + method.upper() + path + body).encode(),
                                     hashlib.sha256).digest()).decode()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class LiveClient:
    def __init__(self, cfg: dict, env=None, demo: bool = False, http_post=None, base: str = BASE):
        env = os.environ if env is None else env
        if cfg.get("mode") != "live" or env.get("DESK_GO_LIVE") != "yes":
            raise LiveGateError("live trading requires config mode: live AND env DESK_GO_LIVE=yes")
        try:
            self._key, self._secret, self._pass = (env["OKX_API_KEY"], env["OKX_API_SECRET"], env["OKX_API_PASSPHRASE"])
        except KeyError as e:
            raise LiveGateError(f"missing credential env var {e.args[0]}") from None
        self.demo, self.base, self._post = demo, base, http_post or self._http_post

    def headers(self, method: str, path: str, body: str, ts: str | None = None) -> dict:
        ts = ts or _timestamp()
        h = {"OK-ACCESS-KEY": self._key, "OK-ACCESS-SIGN": sign(self._secret, ts, method, path, body),
             "OK-ACCESS-TIMESTAMP": ts, "OK-ACCESS-PASSPHRASE": self._pass, "Content-Type": "application/json"}
        if self.demo:
            h["x-simulated-trading"] = "1"
        return h

    def _http_post(self, url: str, headers: dict, body: str) -> dict:
        return requests.post(url, headers=headers, data=body, timeout=20).json()

    def _request(self, path: str, payload: dict) -> dict:
        body = json.dumps(payload, separators=(",", ":"))
        return self._post(self.base + path, self.headers("POST", path, body), body)

    def place_limit_with_stop(self, instId: str, side: str, size: str, price: str, stop_trigger: str) -> dict:
        """Limit order with an attached stop-loss that triggers at stop_trigger and fills at market (slOrdPx -1)."""
        return self._request("/api/v5/trade/order", {
            "instId": instId, "tdMode": "cross", "side": side, "ordType": "limit", "sz": str(size), "px": str(price),
            "attachAlgoOrds": [{"slTriggerPx": str(stop_trigger), "slOrdPx": "-1"}]})

    def close_position(self, instId: str, mgn_mode: str = "cross") -> dict:
        return self._request("/api/v5/trade/close-position", {"instId": instId, "mgnMode": mgn_mode})
