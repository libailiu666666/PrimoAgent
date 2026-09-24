"""Determinism: identical inputs -> identical outputs; stable hashes."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from src.experiments import runner
from src.experiments.config import ExperimentConfig
from src.experiments.data import UniversePrices
from src.experiments.execution import CostModel, run_backtest
from src.experiments.runner import run_walk_forward
from src.experiments.strategies import EqualWeightStrategy, TechnicalStrategy


def test_engine_deterministic(make_prices):
    prices, dates = make_prices(["AAPL", "MSFT"], n_days=60)
    cost = CostModel(initial_capital=100000.0)

    def run():
        s = EqualWeightStrategy()
        return run_backtest(s, dates, prices, cost, s.rebalance_indices(dates))

    r1, r2 = run(), run()
    assert np.array_equal(r1.equity.to_numpy(), r2.equity.to_numpy())
    f1 = [(f.symbol, f.direction, f.qty, f.fill_price) for f in r1.fills]
    f2 = [(f.symbol, f.direction, f.qty, f.fill_price) for f in r2.fills]
    assert f1 == f2


def test_technical_strategy_deterministic(make_prices):
    prices, dates = make_prices(["AAPL", "MSFT"], n_days=80)

    def run():
        s = TechnicalStrategy()
        cost = CostModel(initial_capital=100000.0)
        return run_backtest(s, dates, prices, cost, s.rebalance_indices(dates))

    r1, r2 = run(), run()
    assert np.array_equal(r1.equity.to_numpy(), r2.equity.to_numpy())


def test_config_hash_stable_and_order_independent():
    a = {"experiment": {"name": "x", "random_seed": 42}, "universe": {"tickers": ["AAPL", "MSFT"]}}
    b = {"universe": {"tickers": ["AAPL", "MSFT"]}, "experiment": {"name": "x", "random_seed": 42}}
    h1 = ExperimentConfig(a, Path("a.yaml")).config_hash()
    h2 = ExperimentConfig(b, Path("b.yaml")).config_hash()
    assert h1 == h2
    c = {"experiment": {"name": "x", "random_seed": 43}, "universe": {"tickers": ["AAPL", "MSFT"]}}
    assert ExperimentConfig(c, Path("c.yaml")).config_hash() != h1


def test_data_snapshot_hash_stable_and_sensitive(make_prices):
    prices, dates = make_prices(["AAPL", "MSFT"], n_days=30)
    u1 = UniversePrices(prices=prices, dates=dates)
    h1 = u1.snapshot_hash()
    assert u1.snapshot_hash() == h1

    # a different panel must produce a different hash
    prices2, _ = make_prices(["AAPL", "MSFT"], n_days=30, seed=99)
    assert UniversePrices(prices=prices2, dates=dates).snapshot_hash() != h1


def _patch_loaders(monkeypatch, prices, dates):
    universe = UniversePrices(prices=prices, dates=dates)
    monkeypatch.setattr(runner, "load_universe", lambda *a, **k: universe)
    monkeypatch.setattr(runner, "load_spy", lambda *a, **k: None)


def _config():
    raw = {
        "experiment": {"name": "det", "version": "1.0.0", "random_seed": 42},
        "universe": {"price_source": "tiingo", "tickers": ["AAPL", "MSFT"]},
        "benchmark": {"spy_ticker": "SPY", "spy_source": "yahoo"},
        "walk_forward": {
            "scheme": "annual_expanding",
            "start_year": 2017,
            "train_years": 4,
            "calibration_years": 1,
            "test_years": 1,
        },
        "execution": {"protocol": "T close -> signal after close -> T+1 open"},
        "costs": {
            "initial_capital": 100000,
            "commission_bps": 0,
            "slippage_bps": 0,
            "cash_reserve_pct": 0,
        },
        "legacy_risk": {
            "risk": {"regime": {"enabled": False}},
            "backtesting": {"enable_trailing_stop": False, "enable_take_profit": False},
        },
        "strategies": ["equal_weight", "technical_only"],
        "strategy_params": {},
        "output": {"root": "output/experiments"},
    }
    return ExperimentConfig(raw, Path("det_config.yaml"))


def _result_key(results):
    key = []
    for r in results:
        m = r["metrics"]
        key.append(
            (
                r["strategy"],
                r["fold"],
                r["cost_bps"],
                round(m["final_value"], 8),
                round(m["total_return"], 8),
                round(m["total_cost"], 8),
                round(m["total_turnover"], 8),
                m["n_days"],
                m["n_trades"],
                tuple(np.round(r["_returns"], 9)),
            )
        )
    return key


def test_full_walk_forward_is_deterministic(make_prices, restore_global_config, monkeypatch):
    prices, dates = make_prices(["AAPL", "MSFT"], n_days=1800, start="2017-01-02")
    _patch_loaders(monkeypatch, prices, dates)

    def run():
        return run_walk_forward(
            _config(),
            cost_grid=[0],
            strategies=["equal_weight", "technical_only"],
            write_outputs=False,
        )

    out1, out2 = run(), run()
    assert _result_key(out1["results"]) == _result_key(out2["results"])
