"""Paper bot CLI: --once (catch-up), --loop (forever), --status (compact JSON)."""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import pandas as pd
import yaml

from ..panel import DATA, manifest
from . import paper
from .feed import Feed, last_closed_bar
from .okx import OKX

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "state"
log = logging.getLogger("bot")


def load_cfg(path: Path = ROOT / "config.yaml") -> dict:
    return yaml.safe_load(Path(path).read_text())


def setup_logging(state: Path) -> None:
    state.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(state / "bot.log"), logging.StreamHandler()])


class Bot:
    def __init__(self, cfg: dict, state: Path = STATE, okx: OKX | None = None):
        self.cfg, self.state = cfg, Path(state)
        if cfg.get("mode", "paper") != "paper":
            raise SystemExit("run.py only drives paper mode; live execution is not wired up")
        self.okx = okx or OKX()
        self.feed = Feed(self.state, self.okx, cfg["feed"])
        if not self.feed.symbols():
            self.feed.seed(DATA, [s["instId"] for s in manifest()["symbols"]])
        self.processed_bar = None

    def alert(self, bar: pd.Timestamp, reason: str, now_ms: int) -> None:
        """Block the current bar and journal a Guardian alert in every book."""
        if paper.add_block(self.state, bar):
            ev = {"type": "alert", "time": paper.iso(bar), "reason": reason}
            for b in self.cfg["books"]:
                paper.append_events(self.state / "books" / b / "journal.jsonl", [{**ev, "book": b}])
            log.warning("guardian block %s: %s", paper.iso(bar), reason)

    def cycle(self, update: bool = True) -> dict:
        now_ms = int(time.time() * 1000)
        if update:
            self.feed.update()
        ok, why = self.feed.health(now_ms)
        if not ok:
            self.alert(pd.Timestamp(now_ms // 3_600_000 * 3_600_000, unit="ms", tz="UTC"), f"feed frozen: {why}", now_ms)
        candles, funding = self.feed.panel_inputs()
        out = paper.process_books(self.state, self.cfg, candles, funding, now_ms)
        self.processed_bar = last_closed_bar(now_ms)
        for b, o in out.items():
            log.info("%s as_of=%s equity=%s new_events=%d", b, o["status"].get("as_of"), o["status"].get("equity"), o["new_events"])
        return out

    def live_mark(self, tickers: dict, now_ms: int) -> None:
        """Mark open positions to the latest ticker; block the bar if a book is at/below -day_loss for the UTC day."""
        limit = self.cfg["guard"].get("day_loss", 0)
        if not limit:
            return
        for b in self.cfg["books"]:
            st = paper.read_json(self.state / "books" / b / "status.json", {})
            if not st.get("equity"):
                continue
            eq = st["equity"] + sum((1 if p["side"] == "long" else -1) * p["qty"] * (tickers[p["symbol"]]["last"] - p["last"])
                                    for p in st["open_positions"] if p["symbol"] in tickers)
            if eq / st["day_open_equity"] - 1 <= -limit:
                bar = pd.Timestamp(now_ms // 3_600_000 * 3_600_000, unit="ms", tz="UTC")
                self.alert(bar, f"live kill: {b} day P&L {eq / st['day_open_equity'] - 1:.2%}", now_ms)

    def heartbeat(self, ok: bool, why: str) -> None:
        paper.write_json(self.state / "heartbeat.json", {
            "time": paper.iso(pd.Timestamp.now(tz="UTC")), "last_bar": self.processed_bar and paper.iso(pd.Timestamp(self.processed_bar, unit="ms", tz="UTC")),
            "feed": "ok" if ok else "frozen", "feed_reason": why})

    def loop(self) -> None:
        poll = self.cfg["feed"]["poll_seconds"]
        while True:
            try:
                now_ms = int(time.time() * 1000)
                if self.processed_bar is None or (self.processed_bar < last_closed_bar(now_ms) and now_ms % 3_600_000 > 15_000):
                    self.cycle()
                ok, why = self.feed.health(now_ms)
                if not ok:
                    self.alert(pd.Timestamp(now_ms // 3_600_000 * 3_600_000, unit="ms", tz="UTC"), f"feed frozen: {why}", now_ms)
                else:
                    self.live_mark(self.okx.tickers(), now_ms)
                self.heartbeat(ok, why)
            except Exception:  # noqa: BLE001 - never crash on network/parse errors
                log.exception("loop error; retrying")
            time.sleep(poll)


def status_summary(state: Path = STATE) -> dict:
    out = {"heartbeat": paper.read_json(state / "heartbeat.json", None), "books": {}}
    for d in sorted((state / "books").glob("*")) if (state / "books").exists() else []:
        s = paper.read_json(d / "status.json", {})
        out["books"][d.name] = {k: s.get(k) for k in ("strategy", "as_of", "equity", "return_since_start", "pnl_today", "trades",
                                                      "wins", "losses", "pnl_24h", "closed_24h", "halts_24h")}
        out["books"][d.name]["open_positions"] = [f"{p['side']} {p['symbol']} unreal {p['unrealized']:.2f}" for p in s.get("open_positions", [])]
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--once", action="store_true")
    g.add_argument("--loop", action="store_true")
    g.add_argument("--status", action="store_true")
    a = ap.parse_args(argv)
    if a.status:
        print(json.dumps(status_summary(), indent=1, default=str))
        return
    setup_logging(STATE)
    bot = Bot(load_cfg())
    if a.once:
        bot.cycle()
    else:
        bot.loop()


if __name__ == "__main__":
    main()
