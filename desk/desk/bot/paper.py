"""Stateless paper accounts: the engine output (replayed from paper_start) IS the account.

Each cycle re-runs engine.run per book; only new events are appended to an idempotent journal.
"""
from __future__ import annotations

import json
import time
from dataclasses import fields, is_dataclass, replace
from pathlib import Path

import pandas as pd

from ..engine import Costs, Guard, Risk, run
from ..panel import build_panel
from ..strategies import REGISTRY, compute

REPLAY_AFTER_S = 2 * 3600


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, default=str))
    tmp.replace(path)


def read_json(path: Path, default):
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, ValueError):
        return default


def iso(t) -> str:
    return pd.Timestamp(t).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def get_paper_start(state: Path, cfg: dict, now_ms: int) -> pd.Timestamp:
    """Config value if set, else persisted; first run persists the start of the current hour."""
    if cfg.get("paper_start"):
        t = pd.Timestamp(cfg["paper_start"])
        return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    p = Path(state) / "paper_start.json"
    d = read_json(p, None)
    if not d:
        d = {"paper_start": iso(pd.Timestamp(now_ms // 3_600_000 * 3_600_000, unit="ms", tz="UTC"))}
        write_json(p, d)
    return pd.Timestamp(d["paper_start"])


def load_blocks(state: Path) -> list[str]:
    return read_json(Path(state) / "blocks.json", [])


def add_block(state: Path, bar: pd.Timestamp) -> bool:
    blocks = load_blocks(state)
    if iso(bar) in blocks:
        return False
    write_json(Path(state) / "blocks.json", sorted(blocks + [iso(bar)]))
    return True


def block_series(state: Path, index: pd.Index) -> pd.Series:
    s = pd.Series(False, index=index)
    for b in load_blocks(state):
        t = pd.Timestamp(b)
        if t in s.index:
            s[t] = True
    return s


def slice_from(obj, start):
    if isinstance(obj, pd.DataFrame):
        return obj.loc[start:]
    if is_dataclass(obj):
        return replace(obj, **{f.name: slice_from(getattr(obj, f.name), start) for f in fields(obj)})
    if hasattr(obj, "__dict__") and not isinstance(obj, (str, int, float)):
        return type(obj)(**{k: slice_from(v, start) for k, v in vars(obj).items()})
    return obj


def make_cfg(cfg: dict):
    return Costs(**cfg["costs"]), Risk(**cfg["risk"]), Guard(**cfg["guard"])


def _journal_key(e: dict) -> tuple:
    return (e["type"], e.get("symbol"), e.get("entry_time"), e.get("exit_time"), e.get("time") if e["type"] in ("halt", "alert") else None,
            e.get("reason") if e["type"] == "alert" else None)


def append_events(path: Path, events: list[dict]) -> list[dict]:
    """Append events whose key is not yet journaled; returns the ones appended."""
    path.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    if path.exists():
        seen = {_journal_key(json.loads(line)) for line in path.read_text().splitlines() if line.strip()}
    new = []
    for e in events:
        k = _journal_key(e)
        if k not in seen:
            seen.add(k)
            new.append(e)
    if new:
        with path.open("a") as f:
            f.writelines(json.dumps(e, default=str) + "\n" for e in new)
    return new


def build_events(book: str, bc: dict, res, now_ms: int) -> list[dict]:
    spec = REGISTRY[bc["strategy"]]
    strat = {"strategy": bc["strategy"], "params": bc.get("params", {}), "book": book}
    pos = res.positions

    def replayed(t) -> dict:
        closed_ms = int(pd.Timestamp(t).timestamp() * 1000) + 3_600_000
        return {"replayed": True} if now_ms - closed_ms > REPLAY_AFTER_S * 1000 else {}

    ev = []
    for r in res.trades.itertuples():
        side = "long" if r.dir > 0 else "short"
        et = pd.Timestamp(r.entry_time)
        ev.append({"type": "entry", "time": iso(et), "symbol": r.symbol, "entry_time": iso(et), "side": side,
                   "price": float(r.entry), "qty": abs(float(r.qty)), "stop": None, "target": None, **strat,
                   "reason": spec.rules, "signal_bar": iso(et - pd.Timedelta(hours=1)), **replayed(et)})
        ev.append({"type": "exit", "time": iso(r.exit_time), "symbol": r.symbol, "entry_time": iso(et),
                   "exit_time": iso(r.exit_time), "price": float(r.exit), "pnl": float(r.pnl), "fees": float(r.fees),
                   "funding": float(r.funding), "reason": r.reason, "book": book, **replayed(r.exit_time)})
    for sym, p in pos.iterrows():
        et = pd.Timestamp(p["entry_time"])
        ev.append({"type": "entry", "time": iso(et), "symbol": sym, "entry_time": iso(et),
                   "side": "long" if p["qty"] > 0 else "short", "price": float(p["entry"]), "qty": abs(float(p["qty"])),
                   "stop": _num(p["stop"]), "target": _num(p["target"]), **strat, "reason": spec.rules,
                   "signal_bar": iso(et - pd.Timedelta(hours=1)), **replayed(et)})
    for t, why in res.halts.items():
        ev.append({"type": "halt", "time": iso(t), "reason": why, "book": book, **replayed(t)})
    ev.sort(key=lambda e: (e["time"], e["type"] != "entry"))
    return ev


def _num(x):
    return None if pd.isna(x) else float(x)


def build_status(book: str, bc: dict, res, risk: Risk, start, now_ms: int) -> dict:
    eq, tr = res.equity, res.trades
    last = eq.index[-1]
    day0 = last.floor("D")
    before = eq[eq.index < day0]
    day_open = float(before.iloc[-1]) if len(before) else risk.equity
    cut = last - pd.Timedelta(hours=24)
    r24 = tr[pd.to_datetime(tr["exit_time"]) > cut]
    positions = [{"symbol": s, "side": "long" if p.qty > 0 else "short", "qty": abs(float(p.qty)),
                  "entry": float(p.entry), "stop": _num(p.stop), "target": _num(p.target),
                  "last": float(p["last"]), "unrealized": float(p.unrealized), "entry_time": iso(p.entry_time)}
                 for s, p in res.positions.iterrows()]
    return {"book": book, "strategy": bc["strategy"], "params": bc.get("params", {}), "as_of": iso(last),
            "paper_start": iso(start), "equity": float(eq.iloc[-1]), "day_open_equity": day_open,
            "return_since_start": float(eq.iloc[-1] / risk.equity - 1), "pnl_today": float(eq.iloc[-1] - day_open),
            "open_positions": positions, "trades": int(len(tr)), "wins": int((tr["pnl"] > 0).sum()),
            "losses": int((tr["pnl"] <= 0).sum()), "closed_24h": int(len(r24)), "pnl_24h": float(r24["pnl"].sum()),
            "halts_24h": [{"time": iso(t), "reason": w} for t, w in res.halts.items() if t > cut],
            "daily_equity": {k: float(v) for k, v in eq.groupby(eq.index.strftime("%Y-%m-%d")).last().tail(30).items()},
            "updated": iso(pd.Timestamp(now_ms, unit="ms", tz="UTC"))}


def process_books(state: Path, cfg: dict, candles: dict, funding: dict, now_ms: int | None = None) -> dict:
    """One cycle for every book. Returns {book: {"status": ..., "new_events": n}}."""
    state = Path(state)
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    costs, risk, guard = make_cfg(cfg)
    start = get_paper_start(state, cfg, now_ms)
    D = build_panel(candles, funding)
    out = {}
    for book, bc in cfg["books"].items():
        sig = compute(bc["strategy"], D, bc.get("params", {}))
        Ds, sigs = slice_from(D, start), slice_from(sig, start)
        if len(Ds.close) < 2:
            out[book] = {"status": {"book": book, "as_of": None, "note": "warming up: no closed bar since paper_start",
                                    "paper_start": iso(start)}, "new_events": 0}
            write_json(state / "books" / book / "status.json", out[book]["status"])
            continue
        res = run(Ds, sigs, costs, risk, guard, block_series(state, Ds.close.index), close_at_end=False)
        new = append_events(state / "books" / book / "journal.jsonl", build_events(book, bc, res, now_ms))
        st = build_status(book, bc, res, risk, start, now_ms)
        write_json(state / "books" / book / "status.json", st)
        out[book] = {"status": st, "new_events": len(new), "new": new}
    return out
