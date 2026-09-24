"""Frozen T close -> T+1 open execution protocol (causal invariant)."""
from __future__ import annotations

import pytest

from src.data.contracts import (
    PITTimeError,
    close_time_utc,
    open_time_utc,
    validate_causal_order,
)
from src.experiments.execution import CostModel, PITView, run_backtest
from src.experiments.strategies import EqualWeightStrategy


def test_fill_executes_at_next_open_and_respects_causal_order(make_prices):
    prices, dates = make_prices(["AAPL", "MSFT"], n_days=20)
    cost = CostModel(initial_capital=100000.0, commission_bps=0.0, slippage_bps=0.0)
    strat = EqualWeightStrategy()
    reb = strat.rebalance_indices(dates)

    res = run_backtest(strat, dates, prices, cost, reb)

    # "once" rebalance decides at close of dates[0], fills at open of dates[1].
    assert res.fills, "expected at least one fill"
    for f in res.fills:
        assert f.execution_date == dates[1]
        # fill price is the execution-day OPEN price (never the T close)
        assert f.fill_price == float(prices[f.symbol].loc[dates[1], "open"])
        # frozen causal chain: feature_as_of <= signal_generated_at < execution_at
        assert f.feature_as_of == close_time_utc(dates[0])
        assert f.signal_generated_at == close_time_utc(dates[0])
        assert f.execution_at == open_time_utc(dates[1])
        assert f.feature_as_of <= f.signal_generated_at < f.execution_at
        # decision strictly precedes execution (T+1, never T+0)
        assert f.execution_date > f.trade_date


def test_causal_invariant_rejects_lookahead():
    t = close_time_utc("2024-01-02")
    # execution at the same day's open is BEFORE the close -> violation
    with pytest.raises(PITTimeError):
        validate_causal_order(t, t, open_time_utc("2024-01-02"))
    # signal generated before the feature is knowable -> violation
    with pytest.raises(PITTimeError):
        validate_causal_order(t, close_time_utc("2024-01-01"), open_time_utc("2024-01-02"))
    # a valid T close -> T+1 open chain passes
    validate_causal_order(
        close_time_utc("2024-01-02"),
        close_time_utc("2024-01-02"),
        open_time_utc("2024-01-03"),
    )


def test_pit_view_history_is_truncated_to_as_of(make_prices):
    prices, dates = make_prices(["AAPL"], n_days=10)
    as_of = dates[5]
    view = PITView(as_of=as_of, trade_date=as_of, prices={"AAPL": prices["AAPL"].loc[:as_of]})
    hist = view.history("AAPL")
    assert hist.index.max() <= as_of
    assert len(hist) == 6  # dates[0..5] only
