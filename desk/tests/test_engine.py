from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from desk.engine import Costs, Guard, Risk, Signals, run

SYM = ["BTC-USDT-SWAP"]


def tiny(open_, high, low, close, funding=None):
    idx = pd.date_range("2024-01-01", periods=len(open_), freq="1h", tz="UTC")
    f = lambda x: pd.DataFrame({SYM[0]: np.array(x, float)}, index=idx)
    return SimpleNamespace(open=f(open_), high=f(high), low=f(low), close=f(close), vol=f([1] * len(open_)),
                           funding=f(funding or [0] * len(open_)))


def sig(D, le_at=None, se_at=None, lx_at=None, sd=2.0, tp=None, tr=None, max_hold=0):
    def b(at):
        x = pd.DataFrame(False, index=D.close.index, columns=SYM)
        if at is not None:
            x.iloc[at] = True
        return x
    c = lambda v: None if v is None else pd.DataFrame(float(v), index=D.close.index, columns=SYM)
    return Signals(le=b(le_at), se=b(se_at), lx=b(lx_at), sd=c(sd), tp=c(tp), tr=c(tr), max_hold=max_hold)


FREE = Costs(0, 0, 0)


def test_entry_fills_at_next_open_and_stop_loses_exactly_the_risk():
    D = tiny([100, 100, 101, 99, 99], [100, 100, 102, 100, 99], [100, 100, 100, 97, 99], [100, 100, 101, 98, 99])
    r = run(D, sig(D, le_at=1, sd=2.0), FREE, Risk(equity=10_000, risk_per_trade=0.01))
    t = r.trades.iloc[0]
    assert t.entry == 101 and t.entry_time == D.close.index[2]      # signal on bar 1, filled at bar 2 open
    assert t.reason == "stop" and t.exit == 99                      # stop = 101 - 2
    assert t.qty == pytest.approx(50) and t.pnl == pytest.approx(-100)  # 1% of 10,000


def test_gap_through_stop_fills_at_the_open_not_the_stop():
    D = tiny([100, 100, 101, 95, 95], [100, 100, 102, 96, 95], [100, 100, 100, 94, 95], [100, 100, 101, 95, 95])
    t = run(D, sig(D, le_at=1, sd=2.0), FREE).trades.iloc[0]
    assert t.reason == "stop" and t.exit == 95


def test_stop_wins_when_stop_and_target_touch_in_one_bar():
    D = tiny([100, 100, 101, 101, 101], [100, 100, 101, 110, 101], [100, 100, 101, 90, 101], [100, 100, 101, 101, 101])
    t = run(D, sig(D, le_at=1, sd=2.0, tp=3.0), FREE).trades.iloc[0]
    assert t.reason == "stop"


def test_fees_slippage_and_funding_are_charged():
    D = tiny([100] * 6, [100] * 6, [100] * 6, [100] * 6, funding=[0, 0, 0, 0.001, 0, 0])
    r = run(D, sig(D, le_at=1, lx_at=3, sd=50.0), Costs(0.001, 0.01, 0.01), Risk(equity=10_000, risk_per_trade=0.5))
    t = r.trades.iloc[0]
    assert t.entry == pytest.approx(101) and t.exit == pytest.approx(99)   # 1% slippage each way
    q = t.qty
    assert t.fees == pytest.approx(q * 101 * 0.001 + q * 99 * 0.001)
    assert t.funding == pytest.approx(q * 100 * 0.001)                   # long pays positive funding
    assert t.pnl == pytest.approx(q * (99 - 101) - t.fees - t.funding)
    assert r.equity.iloc[-1] == pytest.approx(10_000 + t.pnl)


def test_short_and_trailing_stop():
    D = tiny([100, 100, 100, 95, 90, 93], [100, 100, 100, 96, 91, 96], [100, 100, 100, 94, 89, 92], [100, 100, 100, 95, 90, 95])
    t = run(D, sig(D, se_at=1, sd=5.0, tr=4.0), FREE).trades.iloc[0]
    assert t.dir == -1 and t.entry == 100
    assert t.reason == "stop" and t.exit == 94                            # trailed to 90 + 4


def test_time_exit_and_position_cap():
    D = tiny([100] * 8, [100] * 8, [100] * 8, [100] * 8)
    r = run(D, sig(D, le_at=1, sd=0.01, max_hold=3), FREE, Risk(equity=10_000, risk_per_trade=0.01, max_pos_lev=1.0))
    t = r.trades.iloc[0]
    assert t.reason == "time" and t.exit_time == D.close.index[5]
    assert t.qty * t.entry == pytest.approx(10_000)                       # capped at 1x equity


def test_guardian_day_loss_flattens_and_halts():
    o = [100, 100, 100, 96, 96, 96, 96, 96]
    D = tiny(o, o, [100, 100, 96, 96, 96, 96, 96, 96], [100, 100, 96, 96, 96, 96, 96, 96])
    s = sig(D, le_at=[1, 4], sd=50.0)
    r = run(D, s, FREE, Risk(equity=10_000, risk_per_trade=1.0), Guard(day_loss=0.03, max_streak=0, halt_bars=24))
    assert list(r.halts) == ["day_loss"] and r.halts.index[0] == D.close.index[2]
    assert len(r.trades) == 1 and r.trades.iloc[0].reason == "guardian"   # second signal is blocked by the halt
    assert r.trades.iloc[0].exit_time == D.close.index[3]


def test_open_positions_are_reported_when_not_closed_at_end():
    D = tiny([100] * 5, [100] * 5, [100] * 5, [100] * 5)
    r = run(D, sig(D, le_at=1, sd=5.0), FREE, close_at_end=False)
    assert len(r.trades) == 0 and r.positions.loc[SYM[0], "stop"] == 95
