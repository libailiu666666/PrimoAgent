"""T close -> T+1 open execution test (PIT_FROZEN_SPEC 3.1 / V1 fix).

Proves a signal formed from the T close executes at the NEXT bar's open, with
order-level timestamps validating ``feature_as_of <= signal_generated_at <
execution_at``. Requires backtrader.
"""
import pandas as pd
import pytest

bt = pytest.importorskip("backtrader")

from src.backtesting.strategies import PrimoAgentStrategy
from src.data.contracts import validate_causal_order


def _run():
    ohlc = pd.DataFrame(
        {
            "Date": pd.date_range("2024-01-02", periods=5, freq="B"),
            "Open": [100.0, 101.0, 102.0, 103.0, 104.0],
            "High": [110.0, 111.0, 112.0, 113.0, 114.0],
            "Low": [99.0, 100.0, 101.0, 102.0, 103.0],
            "Close": [105.0, 106.0, 107.0, 108.0, 109.0],
            "Volume": [1000, 1000, 1000, 1000, 1000],
        }
    )
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "trading_signal": ["BUY", "SELL"],
            "position_size": [50, 50],
        }
    )

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(100000)
    cerebro.broker.set_coc(False)  # explicit: no cheat-on-close
    cerebro.addstrategy(PrimoAgentStrategy, signals_df=signals, printlog=False)
    cerebro.adddata(
        bt.feeds.PandasData(
            dataname=ohlc.set_index("Date"),
            open="Open",
            high="High",
            low="Low",
            close="Close",
            volume="Volume",
            openinterest=None,
        )
    )
    return cerebro.run()[0]


def test_buy_executes_next_bar_open():
    strat = _run()
    assert strat.execution_log, "expected order-level execution records"

    buy = strat.execution_log[0]
    assert buy["direction"] == "BUY"
    assert buy["signal_date"] == "2024-01-02"  # T
    assert buy["execution_date"] == "2024-01-03"  # T+1
    assert buy["fill_price"] == 101.0  # T+1 open, not the T close (105.0)


def test_causal_invariant_holds_on_every_fill():
    strat = _run()
    for rec in strat.execution_log:
        validate_causal_order(
            rec["feature_as_of"], rec["signal_generated_at"], rec["execution_at"]
        )
