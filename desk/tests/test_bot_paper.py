import copy
import json

import pandas as pd

from desk.bot import paper
from desk.engine import run
from desk.panel import build_panel
from desk.strategies import compute
from tests.test_bot_common import CFG, END_BAR, H, ms, synth

NOW = ms(END_BAR) + H + 30_000  # shortly after the last bar closed


def cfg_for(start_back_hours=900):
    c = copy.deepcopy(CFG)
    c["paper_start"] = str(END_BAR - pd.Timedelta(hours=start_back_hours))
    return c


def journal(state, book):
    p = state / "books" / book / "journal.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_cycle_is_idempotent(tmp_path):
    candles, funding = synth()
    cfg = cfg_for()
    first = paper.process_books(tmp_path, cfg, candles, funding, NOW)
    before = {b: journal(tmp_path, b) for b in cfg["books"]}
    second = paper.process_books(tmp_path, cfg, candles, funding, NOW)
    assert sum(len(v) for v in before.values()) > 0
    assert all(second[b]["new_events"] == 0 for b in cfg["books"])
    assert before == {b: journal(tmp_path, b) for b in cfg["books"]}
    assert first["champion"]["status"]["equity"] == second["champion"]["status"]["equity"]


def test_journal_matches_engine(tmp_path):
    candles, funding = synth()
    cfg = cfg_for()
    paper.process_books(tmp_path, cfg, candles, funding, NOW)
    D = build_panel(candles, funding)
    start = pd.Timestamp(cfg["paper_start"])
    for book, bc in cfg["books"].items():
        sig = compute(bc["strategy"], D, bc["params"])
        costs, risk, guard = paper.make_cfg(cfg)
        res = run(paper.slice_from(D, start), paper.slice_from(sig, start), costs, risk, guard, None, close_at_end=False)
        ev = journal(tmp_path, book)
        exits = [e for e in ev if e["type"] == "exit"]
        entries = [e for e in ev if e["type"] == "entry"]
        assert len(exits) == len(res.trades)
        for e, t in zip(sorted(exits, key=lambda e: (e["exit_time"], e["symbol"])),
                        res.trades.sort_values(["exit_time", "symbol"]).itertuples()):
            assert (e["symbol"], e["pnl"], e["price"], e["reason"]) == (t.symbol, float(t.pnl), float(t.exit), t.reason)
        assert len(entries) == len(res.trades) + len(res.positions)
        for sym, p in res.positions.iterrows():
            e = next(x for x in entries if x["symbol"] == sym and x["entry_time"] == paper.iso(p["entry_time"]))
            assert e["price"] == float(p["entry"]) and e["qty"] == abs(float(p["qty"])) and e["stop"] == float(p["stop"])
            assert e["signal_bar"] == paper.iso(pd.Timestamp(p["entry_time"]) - pd.Timedelta(hours=1))
        st = json.loads((tmp_path / "books" / book / "status.json").read_text())
        assert st["equity"] == float(res.equity.iloc[-1]) and st["trades"] == len(res.trades)
        assert len(st["open_positions"]) == len(res.positions)
        assert all(e.get("replayed") for e in ev if e["type"] == "exit")


def test_block_flattens_and_journals_halt(tmp_path):
    candles, funding = synth()
    cfg = cfg_for()
    cfg["books"] = {"champion": cfg["books"]["champion"]}
    paper.process_books(tmp_path, cfg, candles, funding, NOW)
    # find a bar where the book holds positions, block the next bar, and expect a flat book afterwards
    D = build_panel(candles, funding)
    costs, risk, guard = paper.make_cfg(cfg)
    start = pd.Timestamp(cfg["paper_start"])
    sig = paper.slice_from(compute("donchian_trend", D, cfg["books"]["champion"]["params"]), start)
    Ds = paper.slice_from(D, start)
    base = run(Ds, sig, costs, risk, guard, None, close_at_end=False)
    t = base.trades.iloc[len(base.trades) // 2]
    blk_bar = pd.Timestamp(t["entry_time"]) + pd.Timedelta(hours=2)
    paper.add_block(tmp_path, blk_bar)
    assert paper.load_blocks(tmp_path) == [paper.iso(blk_bar)]
    paper.process_books(tmp_path, cfg, candles, funding, NOW)
    halts = [e for e in journal(tmp_path, "champion") if e["type"] == "halt"]
    assert any(h["reason"] == "feed_block" and h["time"] == paper.iso(blk_bar) for h in halts)
    ex = [e for e in journal(tmp_path, "champion") if e["type"] == "exit" and e["symbol"] == t["symbol"]
          and e["entry_time"] == paper.iso(t["entry_time"])]
    assert ex  # the position that was open at the block was closed (reason may be guardian or earlier exit)
