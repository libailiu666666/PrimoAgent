"""Deterministic walk-forward baselines (Gate 2).

Five baselines, all long-only and fully deterministic (no randomness, no LLM):

- ``buy_and_hold``  — buy & hold SPY (single market asset), costed
- ``spy_benchmark`` — SPY total-return index (zero cost; handled by the runner)
- ``equal_weight``  — equal-weight 30-stock portfolio, buy once, hold
- ``technical_only``— daily SMA(crossover) trend, equal-weight longs
- ``fundamental_only``— monthly top-K by latest ROA, equal weight

The ``fit`` hook receives only train + calibration data (never test); baselines
leave it as a no-op. ``target_weights`` is called at each rebalance date with a
``PITView`` that contains only data known at that date, so a strategy cannot
reach forward even if written carelessly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd


@dataclass
class FitData:
    """Data available for fitting: train + calibration windows only."""

    train_dates: List[pd.Timestamp] = field(default_factory=list)
    calibration_dates: List[pd.Timestamp] = field(default_factory=list)
    prices: Dict[str, pd.DataFrame] = field(default_factory=dict)
    store: Optional[object] = None


class BaselineStrategy:
    """Base class for a deterministic baseline.

    Subclasses set ``name``, ``version``, ``rebalance`` (``daily``/``monthly``/
    ``once``) and implement ``target_weights``.
    """

    name: str = "base"
    version: str = "1.0.0"
    rebalance: str = "daily"

    def __init__(self, params: Optional[dict] = None, store: Optional[object] = None):
        self.params = dict(params or {})
        self.store = store

    def fit(self, fit_data: "FitData") -> None:
        """Fit on train + calibration only. Baselines are parameter-free."""
        return None

    def rebalance_indices(self, dates: List[pd.Timestamp]) -> set:
        if self.rebalance == "daily":
            return set(range(len(dates)))
        if self.rebalance == "monthly":
            return {i for i, d in enumerate(dates) if _is_first_trading_day(d, dates)}
        if self.rebalance == "once":
            return {0} if dates else set()
        raise ValueError(f"unknown rebalance frequency: {self.rebalance!r}")

    def target_weights(self, d: pd.Timestamp, view) -> Dict[str, float]:
        raise NotImplementedError


def _is_first_trading_day(d: pd.Timestamp, dates: List[pd.Timestamp]) -> bool:
    return d == min(x for x in dates if x.year == d.year and x.month == d.month)


def _equal_weight(symbols) -> Dict[str, float]:
    n = len(symbols)
    if n == 0:
        return {}
    return {s: 1.0 / n for s in sorted(symbols)}


class BuyAndHoldStrategy(BaselineStrategy):
    """Buy every symbol in the view once (equal weight) and hold to the end."""

    name = "buy_and_hold"
    rebalance = "once"

    def target_weights(self, d: pd.Timestamp, view) -> Dict[str, float]:
        return _equal_weight(list(view.prices.keys()))


class EqualWeightStrategy(BaselineStrategy):
    """Equal-weight portfolio, single entry, no rebalancing."""

    name = "equal_weight"
    rebalance = "once"

    def target_weights(self, d: pd.Timestamp, view) -> Dict[str, float]:
        return _equal_weight(list(view.prices.keys()))


class TechnicalStrategy(BaselineStrategy):
    """Daily trend filter: long a stock while SMA(fast) > SMA(slow)."""

    name = "technical_only"
    rebalance = "daily"

    def target_weights(self, d: pd.Timestamp, view) -> Dict[str, float]:
        fast = int(self.params.get("sma_fast", 20))
        slow = int(self.params.get("sma_slow", 50))
        longs = []
        for sym in sorted(view.prices):
            close = view.history(sym)["close"]
            if len(close) < slow:
                continue
            if float(close.rolling(fast).mean().iloc[-1]) > float(
                close.rolling(slow).mean().iloc[-1]
            ):
                longs.append(sym)
        return _equal_weight(longs)


class FundamentalStrategy(BaselineStrategy):
    """Monthly top-K by latest point-in-time ROA (NetIncomeLoss / Assets)."""

    name = "fundamental_only"
    rebalance = "monthly"

    def target_weights(self, d: pd.Timestamp, view) -> Dict[str, float]:
        top_k = int(self.params.get("top_k", 10))
        ni_c = self.params.get("net_income_concept", "NetIncomeLoss")
        assets_c = self.params.get("assets_concept", "Assets")

        scores: Dict[str, float] = {}
        for sym in sorted(view.prices):
            roa = self._latest_roa(sym, view.as_of, ni_c, assets_c)
            if roa is not None:
                scores[sym] = roa

        if not scores:
            return {}
        top = sorted(scores, key=scores.get, reverse=True)[:top_k]
        return _equal_weight(top)

    def _latest_roa(self, symbol: str, as_of, ni_c: str, assets_c: str) -> Optional[float]:
        if self.store is None:
            return None
        key = (symbol.upper(), pd.Timestamp(as_of).isoformat(), ni_c, assets_c)
        if key in _ROA_CACHE:
            return _ROA_CACHE[key]
        result = self._compute_roa(symbol.upper(), as_of, ni_c, assets_c)
        _ROA_CACHE[key] = result
        return result

    def _compute_roa(self, symbol: str, as_of, ni_c: str, assets_c: str) -> Optional[float]:
        facts = self.store.get_fundamentals(symbol, as_of)
        if facts is None or facts.empty:
            return None

        ni = facts[(facts["concept"] == ni_c) & (facts["unit"].astype(str) == "USD")]
        assets = facts[(facts["concept"] == assets_c) & (facts["unit"].astype(str) == "USD")]
        if ni.empty or assets.empty:
            return None

        common_ends = set(ni["end"]) & set(assets["end"])
        if not common_ends:
            return None
        end = max(common_ends)

        ni_val = ni[ni["end"] == end]["val"].iloc[-1]
        assets_val = assets[assets["end"] == end]["val"].iloc[-1]
        if pd.isna(assets_val) or pd.isna(ni_val) or float(assets_val) == 0.0:
            return None
        return float(ni_val) / float(assets_val)


_ROA_CACHE: Dict[tuple, Optional[float]] = {}


STRATEGY_CLASSES = {
    "buy_and_hold": BuyAndHoldStrategy,
    "equal_weight": EqualWeightStrategy,
    "technical_only": TechnicalStrategy,
    "fundamental_only": FundamentalStrategy,
}
