"""Pre-Gate2 legacy risk-regime audit: PIT safety fix + explicit off-switches.

Covers:
1. notify_order seeds the trailing-stop peak from ``order.executed.price``
   (the T+1 open fill), never ``self.data.close[0]`` (the T+1 close -> lookahead).
2. trailing stop / take profit can be explicitly disabled via strategy params
   (which defer to ``backtesting.enable_trailing_stop`` / ``enable_take_profit``).
3. the adaptive regime can be explicitly disabled via ``risk.regime.enabled``,
   making the risk manager a position pass-through and regime detection Neutral.

Requires backtrader.
"""
import asyncio
import copy

import pandas as pd
import pytest

bt = pytest.importorskip("backtrader")

from src.backtesting.strategies import PrimoAgentStrategy
from src.config import config


def _add_data(cerebro, ohlc):
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


def test_buy_peak_seeded_from_executed_price_not_close():
    """A BUY filling at T+1 open must not read T+1 close when seeding the peak."""
    ohlc = pd.DataFrame(
        {
            "Date": pd.date_range("2024-01-02", periods=4, freq="B"),
            "Open": [100.0, 101.0, 102.0, 103.0],
            "High": [110.0, 111.0, 112.0, 113.0],
            "Low": [99.0, 100.0, 101.0, 102.0],
            "Close": [105.0, 300.0, 107.0, 108.0],  # T+1 close far above open
            "Volume": [1000, 1000, 1000, 1000],
        }
    )
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02"]),
            "trading_signal": ["BUY"],
            "position_size": [100],
        }
    )

    class _Probe(PrimoAgentStrategy):
        def notify_order(self, order):
            super().notify_order(order)
            if order.status == order.Completed and order.isbuy():
                self.probe = {
                    "highest_price": self.highest_price,
                    "close0": self.data.close[0],
                    "executed": order.executed.price,
                }

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(100000)
    cerebro.broker.set_coc(False)
    cerebro.addstrategy(
        _Probe,
        signals_df=signals,
        printlog=False,
        enable_trailing_stop=False,
        enable_take_profit=False,
    )
    _add_data(cerebro, ohlc)
    strat = cerebro.run()[0]

    assert strat.probe["executed"] == 101.0  # T+1 open fill
    assert strat.probe["close0"] == 300.0  # T+1 close (the lookahead source)
    # The peak must be seeded from the fill, not the same-bar close.
    assert strat.probe["highest_price"] == strat.probe["executed"]
    assert strat.probe["highest_price"] != strat.probe["close0"]


def _run_switches(enable_trailing_stop, enable_take_profit):
    ohlc = pd.DataFrame(
        {
            "Date": pd.date_range("2024-01-02", periods=7, freq="B"),
            "Open": [100.0, 101.0, 102.0, 103.0, 104.0, 95.0, 94.0],
            "High": [110.0, 111.0, 112.0, 113.0, 114.0, 105.0, 104.0],
            "Low": [99.0, 100.0, 101.0, 102.0, 103.0, 94.0, 93.0],
            "Close": [105.0, 106.0, 107.0, 108.0, 109.0, 96.0, 95.0],
            "Volume": [1000, 1000, 1000, 1000, 1000, 1000, 1000],
        }
    )
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02"]),
            "trading_signal": ["BUY"],
            "position_size": [100],
        }
    )

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(100000)
    cerebro.broker.set_coc(False)
    cerebro.addstrategy(
        PrimoAgentStrategy,
        signals_df=signals,
        printlog=False,
        enable_trailing_stop=enable_trailing_stop,
        enable_take_profit=enable_take_profit,
    )
    _add_data(cerebro, ohlc)
    return cerebro.run()[0]


def test_trailing_stop_and_take_profit_can_be_disabled():
    with_stops = _run_switches(True, True)
    without_stops = _run_switches(False, False)

    # Trailing stop closes the position after the peak-to-crash drawdown.
    assert with_stops.position.size == 0
    assert len(with_stops.trade_log) >= 1

    # With both switches off, no auto-exit fires: position stays open, no trades.
    assert without_stops.position.size > 0
    assert len(without_stops.trade_log) == 0


def test_config_defaults_enable_legacy_features():
    """The shipped config keeps the legacy features ON by default."""
    assert config.backtest_enable_trailing_stop is True
    assert config.backtest_enable_take_profit is True
    assert config.risk_regime_enabled is True


def test_regime_disabled_returns_neutral(monkeypatch):
    import src.workflows.workflow  # noqa: F401  (break pre-existing cycle)

    from src.agents.risk_manager_agent import _compute_regime_score

    data = copy.deepcopy(config._config_data)
    data["risk"]["regime"]["enabled"] = False
    monkeypatch.setattr(config, "_config_data", data)

    closes = pd.Series([100.0 + i * 0.5 for i in range(80)])
    info = _compute_regime_score(closes)
    assert info["regime"] == "neutral"
    assert info["regime_score"] == 0.0


def test_regime_disabled_passes_position_through(monkeypatch):
    import src.workflows.workflow  # noqa: F401  (break pre-existing cycle)

    from src.agents.risk_manager_agent import risk_manager_agent_node

    data = copy.deepcopy(config._config_data)
    data["risk"]["regime"]["enabled"] = False
    monkeypatch.setattr(config, "_config_data", data)

    state = {
        "symbols": ["AAPL"],
        "portfolio_manager_results": {
            "AAPL": {
                "success": True,
                "trading_signal": "BUY",
                "confidence_level": 0.8,
                "position_size": 70,
            }
        },
        "data_collection_results": {
            "market_data": {
                "historical_data": [{"close": 100.0 + i} for i in range(80)],
            }
        },
    }

    out = asyncio.run(risk_manager_agent_node(state))
    pm = out["portfolio_manager_results"]["AAPL"]
    assert pm["position_size"] == 70  # unchanged: no regime-scaled cap applied
    assert out["risk_manager_results"]["action"] == "validated"
    assert out["risk_manager_results"]["risk_metrics"]["adaptive_regime"] == "disabled"
