"""Test data must never enter the fitting interface (Gate 2 isolation)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.experiments import runner
from src.experiments.config import ExperimentConfig
from src.experiments.data import UniversePrices
from src.experiments.runner import run_walk_forward
from src.experiments.strategies import BaselineStrategy, _equal_weight

RECORDED = []


class RecordingStrategy(BaselineStrategy):
    """Records the latest date the fitting interface ever exposes."""

    name = "recording"
    rebalance = "once"

    def fit(self, fit_data):
        max_price = None
        for df in fit_data.prices.values():
            if df is not None and len(df):
                m = df.index.max()
                max_price = m if max_price is None else max(max_price, m)
        all_dates = list(fit_data.train_dates) + list(fit_data.calibration_dates)
        RECORDED.append(
            {
                "max_price": max_price,
                "max_fit_date": max(all_dates) if all_dates else None,
            }
        )

    def target_weights(self, d, view):
        return _equal_weight(list(view.prices.keys()))


def _patch_loaders(monkeypatch, prices, dates):
    universe = UniversePrices(prices=prices, dates=dates)
    monkeypatch.setattr(runner, "load_universe", lambda *a, **k: universe)
    monkeypatch.setattr(runner, "load_spy", lambda *a, **k: None)


def _config():
    raw = {
        "experiment": {"name": "leak", "version": "1.0.0", "random_seed": 42},
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
        "strategies": ["recording"],
        "strategy_params": {},
        "output": {"root": "output/experiments"},
    }
    return ExperimentConfig(raw, Path("leak_config.yaml"))


def test_fit_receives_no_test_data(make_prices, restore_global_config, monkeypatch):
    RECORDED.clear()
    prices, dates = make_prices(["AAPL", "MSFT"], n_days=1800, start="2017-01-02")
    _patch_loaders(monkeypatch, prices, dates)
    monkeypatch.setitem(runner.STRATEGY_CLASSES, "recording", RecordingStrategy)

    out = run_walk_forward(
        _config(), cost_grid=[0], strategies=["recording"], write_outputs=False
    )

    folds = out["folds"]
    assert len(RECORDED) == len(folds)

    for rec, fold in zip(RECORDED, folds):
        cal_end = pd.Timestamp(fold["calibration_end"])
        test_start = pd.Timestamp(fold["test_start"])
        # the fitting interface exposes nothing past the calibration window
        assert rec["max_price"] is not None
        assert rec["max_price"] <= cal_end
        assert rec["max_fit_date"] <= cal_end
        # and certainly nothing from the test window
        assert rec["max_fit_date"] < test_start
