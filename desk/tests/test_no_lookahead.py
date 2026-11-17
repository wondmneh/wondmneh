import pytest

from desk import research, strategies


@pytest.mark.parametrize("name", list(strategies.REGISTRY))
def test_signals_do_not_change_when_the_future_is_removed(D, name):
    spec = strategies.REGISTRY[name]
    combos = spec.combos()
    assert research.leak_test(D, name, combos[len(combos) // 2])


def test_the_leak_test_catches_a_real_leak(D, monkeypatch):
    def cheat(D, n, k):
        s = strategies.donchian_trend(D, n, k)
        s.le = D.close.shift(-1) > D.close                 # peeks at the next bar
        return s
    monkeypatch.setitem(strategies.REGISTRY, "cheat", strategies.Spec(cheat, {"n": [20], "k": [2.0]}, "", "", "", "", "", ""))
    assert not research.leak_test(D, "cheat", {"n": 20, "k": 2.0})
