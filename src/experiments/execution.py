"""T+1 execution engine and point-in-time view (Gate 2).

The frozen execution protocol is:

    T close forms the feature  ->  signal after T close  ->  T+1 open fills

The engine makes a rebalance decision at each rebalance date ``T`` (using only
data known at ``T`` close) and executes it at the next trading day's open. Every
fill records ``feature_as_of`` / ``signal_generated_at`` / ``execution_at`` and
is validated against the causal invariant ``feature_as_of <= signal_generated_at
< execution_at`` (fail fast on any violation).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

from ..data.contracts import close_time_utc, open_time_utc, validate_causal_order


@dataclass
class CostModel:
    """Execution cost assumptions shared by every strategy."""

    initial_capital: float = 100000.0
    commission_bps: float = 0.0
    slippage_bps: float = 0.0
    cash_reserve_pct: float = 0.0

    @property
    def commission_rate(self) -> float:
        return self.commission_bps / 10000.0

    @property
    def slippage_rate(self) -> float:
        return self.slippage_bps / 10000.0

    @property
    def investable_fraction(self) -> float:
        return 1.0 - self.cash_reserve_pct / 100.0

    def as_dict(self) -> dict:
        return {
            "initial_capital": self.initial_capital,
            "commission_bps": self.commission_bps,
            "slippage_bps": self.slippage_bps,
            "cash_reserve_pct": self.cash_reserve_pct,
        }


@dataclass
class PITView:
    """Data snapshot knowable at the ``T`` close (``feature_as_of``)."""

    as_of: pd.Timestamp
    trade_date: pd.Timestamp
    prices: Dict[str, pd.DataFrame]

    def history(self, symbol: str) -> pd.DataFrame:
        return self.prices.get(symbol.upper(), self.prices.get(symbol))


@dataclass
class Fill:
    symbol: str
    trade_date: pd.Timestamp
    execution_date: pd.Timestamp
    feature_as_of: pd.Timestamp
    signal_generated_at: pd.Timestamp
    execution_at: pd.Timestamp
    direction: str
    qty: float
    fill_price: float
    notional: float
    commission: float
    slippage: float

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "trade_date": self.trade_date.date().isoformat(),
            "execution_date": self.execution_date.date().isoformat(),
            "feature_as_of": self.feature_as_of.isoformat(),
            "signal_generated_at": self.signal_generated_at.isoformat(),
            "execution_at": self.execution_at.isoformat(),
            "direction": self.direction,
            "qty": self.qty,
            "fill_price": self.fill_price,
            "notional": self.notional,
            "commission": self.commission,
            "slippage": self.slippage,
        }


@dataclass
class BacktestResult:
    strategy: str
    version: str
    fold_index: int
    equity: pd.Series
    fills: List[Fill] = field(default_factory=list)
    total_commission: float = 0.0
    total_slippage: float = 0.0
    total_turnover: float = 0.0


def _clip_weights(weights: Dict[str, float], investable: float) -> Dict[str, float]:
    """Clip non-negative target weights so their sum is <= investable fraction."""
    clipped = {s: max(0.0, float(w)) for s, w in (weights or {}).items() if w and w > 0}
    total = sum(clipped.values())
    if total <= 0:
        return {}
    if total <= investable:
        return clipped
    scale = investable / total
    return {s: v * scale for s, v in clipped.items()}


def _rebalance(
    weights: Dict[str, float],
    open_px: Dict[str, float],
    cash: float,
    shares: Dict[str, float],
    investable: float,
    commission_rate: float,
    slippage_rate: float,
    decision_date: pd.Timestamp,
    execution_date: pd.Timestamp,
) -> Tuple[Dict[str, float], float, List[Fill], float, float, float]:
    """Execute target weights at the execution-day open; return updated state."""
    w = _clip_weights(weights, investable)
    value = cash + sum(shares.get(s, 0.0) * open_px.get(s, 0.0) for s in shares)

    feature_as_of = close_time_utc(decision_date)
    signal_generated_at = close_time_utc(decision_date)
    execution_at = open_time_utc(execution_date)
    # Fail fast if the T close -> T+1 open chain is ever broken.
    validate_causal_order(feature_as_of, signal_generated_at, execution_at)

    fills: List[Fill] = []
    comm_total = 0.0
    slip_total = 0.0
    turnover = 0.0

    for s in sorted(open_px):
        px = open_px[s]
        if px <= 0:
            continue
        target_shares = w.get(s, 0.0) * value / px
        cur = shares.get(s, 0.0)
        delta = target_shares - cur
        if abs(delta) < 1e-9:
            continue

        direction = "BUY" if delta > 0 else "SELL"
        qty = abs(delta)
        gross = qty * px
        slip = gross * slippage_rate
        comm = gross * commission_rate
        turnover += gross
        comm_total += comm
        slip_total += slip

        if direction == "BUY":
            cash -= gross + slip + comm
        else:
            cash += gross - slip - comm
        shares[s] = target_shares

        fills.append(
            Fill(
                symbol=s,
                trade_date=pd.Timestamp(decision_date),
                execution_date=pd.Timestamp(execution_date),
                feature_as_of=feature_as_of,
                signal_generated_at=signal_generated_at,
                execution_at=execution_at,
                direction=direction,
                qty=qty,
                fill_price=px,
                notional=gross,
                commission=comm,
                slippage=slip,
            )
        )

    return shares, cash, fills, comm_total, slip_total, turnover


def run_backtest(
    strategy,
    dates: Iterable[pd.Timestamp],
    prices: Dict[str, pd.DataFrame],
    costs: CostModel,
    rebalance_indices: Iterable[int],
    fold_index: int = 0,
) -> BacktestResult:
    """Run a single strategy over ``dates`` with T close -> T+1 open execution."""
    dates = list(pd.Timestamp(d).normalize() for d in dates)
    symbols = sorted(prices)
    shares = {s: 0.0 for s in symbols}
    cash = costs.initial_capital
    investable = costs.investable_fraction
    commission_rate = costs.commission_rate
    slippage_rate = costs.slippage_rate

    rebalance = set(rebalance_indices)

    fills: List[Fill] = []
    total_commission = 0.0
    total_slippage = 0.0
    total_turnover = 0.0

    equity_dates: List[pd.Timestamp] = []
    equity_vals: List[float] = []

    pending_weights: Optional[Dict[str, float]] = None
    pending_decision_date: Optional[pd.Timestamp] = None

    n = len(dates)
    for i in range(n):
        d = dates[i]
        open_px = {s: float(prices[s].loc[d, "open"]) for s in symbols}
        close_px = {s: float(prices[s].loc[d, "close"]) for s in symbols}

        # 1. Execute the rebalance decided at i-1, at today's open.
        if pending_weights is not None:
            shares, cash, new_fills, comm, slip, turnover = _rebalance(
                pending_weights,
                open_px,
                cash,
                shares,
                investable,
                commission_rate,
                slippage_rate,
                pending_decision_date,
                d,
            )
            fills.extend(new_fills)
            total_commission += comm
            total_slippage += slip
            total_turnover += turnover
            pending_weights = None
            pending_decision_date = None

        # 2. Mark to market at today's close.
        v = cash + sum(shares[s] * close_px.get(s, 0.0) for s in symbols)
        equity_dates.append(d)
        equity_vals.append(v)

        # 3. Decide the rebalance at today's close (executes tomorrow's open).
        if i in rebalance:
            view = PITView(
                as_of=close_time_utc(d),
                trade_date=d,
                prices={s: prices[s].loc[:d] for s in symbols},
            )
            pending_weights = strategy.target_weights(d, view)
            pending_decision_date = d

    equity = pd.Series(equity_vals, index=pd.DatetimeIndex(equity_dates, name="date"))
    return BacktestResult(
        strategy=strategy.name,
        version=strategy.version,
        fold_index=fold_index,
        equity=equity,
        fills=fills,
        total_commission=total_commission,
        total_slippage=total_slippage,
        total_turnover=total_turnover,
    )
