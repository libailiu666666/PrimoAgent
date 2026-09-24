"""Cost model: higher commission/slippage reduces net return."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.experiments.execution import CostModel, run_backtest
from src.experiments.metrics import compute_metrics
from src.experiments.strategies import EqualWeightStrategy


def _rising_prices(symbols, n_days=30):
    """A strictly rising panel so that less invested -> lower final value."""
    dates = list(pd.bdate_range("2024-01-02", periods=n_days))
    prices = {}
    for j, s in enumerate(symbols):
        base = 100.0 + 10.0 * j
        close = base * np.linspace(1.0, 1.3, n_days)
        open_ = close * 0.999
        prices[s] = pd.DataFrame(
            {
                "open": open_,
                "high": close * 1.01,
                "low": open_ * 0.99,
                "close": close,
                "volume": 1_000_000.0,
            },
            index=pd.DatetimeIndex(dates, name="date"),
        )
    return prices, dates


def _run(cost_bps, prices, dates):
    cost = CostModel(initial_capital=100000.0, commission_bps=cost_bps, slippage_bps=0.0)
    s = EqualWeightStrategy()
    return run_backtest(s, dates, prices, cost, s.rebalance_indices(dates))


def test_higher_commission_lowers_net_return():
    prices, dates = _rising_prices(["AAPL", "MSFT"])
    cheap = _run(0.0, prices, dates)
    expensive = _run(50.0, prices, dates)

    m0 = compute_metrics(cheap.equity, 100000.0, cheap.total_commission,
                         cheap.total_slippage, cheap.total_turnover, len(cheap.fills))
    m50 = compute_metrics(expensive.equity, 100000.0, expensive.total_commission,
                          expensive.total_slippage, expensive.total_turnover, len(expensive.fills))

    assert m0["total_commission"] == 0.0
    assert m50["total_commission"] > 0.0
    assert m50["final_value"] < m0["final_value"]
    assert m50["total_return"] < m0["total_return"]


def test_slippage_also_reduces_net_return():
    prices, dates = _rising_prices(["AAPL", "MSFT"])
    no_slip = CostModel(initial_capital=100000.0, commission_bps=0.0, slippage_bps=0.0)
    slip = CostModel(initial_capital=100000.0, commission_bps=0.0, slippage_bps=50.0)
    s1 = EqualWeightStrategy()
    s2 = EqualWeightStrategy()
    r0 = run_backtest(s1, dates, prices, no_slip, s1.rebalance_indices(dates))
    r1 = run_backtest(s2, dates, prices, slip, s2.rebalance_indices(dates))
    assert r1.total_slippage > 0.0
    assert r1.equity.iloc[-1] < r0.equity.iloc[-1]
