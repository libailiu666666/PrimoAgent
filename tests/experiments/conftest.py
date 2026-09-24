"""Fixtures for the walk-forward benchmark tests (Gate 2)."""
from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def _cleanup_historical_mode():
    """Ensure the historical-mode network guard is disabled after every test."""
    yield
    from src.data import historical_mode

    historical_mode.disable_historical_mode()


@pytest.fixture
def restore_global_config():
    """Snapshot/restore the global config object around a test."""
    from src.config import config

    before = copy.deepcopy(config._config_data)
    yield
    config._config_data = before


def _make_prices(symbols, n_days: int = 80, start: str = "2024-01-02", seed: int = 0):
    """Build a small deterministic synthetic OHLCV panel.

    Returns ``(prices, dates)`` where ``prices`` maps symbol -> DataFrame with
    columns ``open/high/low/close/volume`` indexed by business dates.
    """
    rng = np.random.default_rng(seed)
    dates = list(pd.bdate_range(start, periods=n_days))
    prices = {}
    for j, s in enumerate(symbols):
        base = 100.0 + 10.0 * j
        rets = rng.normal(0.0004, 0.012, n_days)
        close = base * np.cumprod(1.0 + rets)
        open_ = close * (1.0 + rng.normal(0.0, 0.0005, n_days))
        high = np.maximum(open_, close) * 1.002
        low = np.minimum(open_, close) * 0.998
        prices[s] = pd.DataFrame(
            {
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": np.full(n_days, 1_000_000.0),
            },
            index=pd.DatetimeIndex(dates, name="date"),
        )
    return prices, dates


@pytest.fixture
def make_prices():
    """Expose the synthetic-panel builder as a fixture-injected function."""
    return _make_prices


@pytest.fixture
def gate2_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "configs" / "experiments" / "gate2_baseline.yaml"
