"""Performance metrics for walk-forward baselines (Gate 2)."""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd

TRADING_DAYS = 252
RISK_FREE = 0.0


def _annualized_return(total_return: float, n_days: int) -> float:
    if n_days <= 1 or total_return <= -1.0:
        return float("nan")
    return (1.0 + total_return) ** (TRADING_DAYS / n_days) - 1.0


def compute_metrics(
    equity: pd.Series,
    initial_capital: float,
    total_commission: float = 0.0,
    total_slippage: float = 0.0,
    total_turnover: float = 0.0,
    n_trades: int = 0,
) -> Dict[str, float]:
    """Return a flat dict of performance metrics for one equity curve."""
    if equity is None or len(equity) < 2:
        return {}

    returns = equity.pct_change().dropna()
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    n_days = len(equity)
    ann_return = _annualized_return(total_return, n_days)

    ann_vol = float(returns.std(ddof=1) * np.sqrt(TRADING_DAYS)) if len(returns) > 1 else 0.0
    sharpe = (ann_return - RISK_FREE) / ann_vol if ann_vol > 0 else float("nan")

    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    max_dd = float(drawdown.min())

    calmar = ann_return / abs(max_dd) if max_dd < 0 else float("nan")

    downside = returns[returns < 0]
    downside_std = float(downside.std(ddof=1) * np.sqrt(TRADING_DAYS)) if len(downside) > 1 else 0.0
    sortino = (ann_return - RISK_FREE) / downside_std if downside_std > 0 else float("nan")

    avg_equity = float(equity.mean()) if len(equity) else float(initial_capital)
    turnover_rate = total_turnover / avg_equity if avg_equity > 0 else 0.0
    total_cost = total_commission + total_slippage

    return {
        "final_value": float(equity.iloc[-1]),
        "total_return": total_return,
        "annualized_return": ann_return,
        "annualized_volatility": ann_vol,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "max_drawdown": max_dd,
        "calmar_ratio": calmar,
        "n_days": n_days,
        "n_trades": n_trades,
        "total_turnover": total_turnover,
        "turnover_rate": turnover_rate,
        "total_commission": total_commission,
        "total_slippage": total_slippage,
        "total_cost": total_cost,
    }


def pool_metrics(results: List[Dict[str, float]]) -> Dict[str, float]:
    """Aggregate per-fold metrics by chaining daily returns where available.

    Per-fold dicts carry a private ``_returns`` array; when absent, fall back to
    a value-weighted average of the per-fold metrics (less precise).
    """
    rets = []
    for r in results:
        if r and "_returns" in r and r["_returns"] is not None:
            rets.append(np.asarray(r["_returns"], dtype=float))
    if not rets:
        return {}

    chain = np.concatenate(rets)
    total_return = float(np.prod(1.0 + chain) - 1.0)
    n_days = len(chain)
    ann_return = _annualized_return(total_return, n_days)
    ann_vol = float(np.std(chain, ddof=1) * np.sqrt(TRADING_DAYS)) if len(chain) > 1 else 0.0
    sharpe = (ann_return - RISK_FREE) / ann_vol if ann_vol > 0 else float("nan")

    equity = (1.0 + chain).cumprod()
    running_max = np.maximum.accumulate(equity)
    drawdown = equity / running_max - 1.0
    max_dd = float(drawdown.min())
    calmar = ann_return / abs(max_dd) if max_dd < 0 else float("nan")

    return {
        "total_return": total_return,
        "annualized_return": ann_return,
        "annualized_volatility": ann_vol,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_dd,
        "calmar_ratio": calmar,
        "n_days": n_days,
    }


def attach_returns(metrics: Dict[str, float], equity: pd.Series) -> Dict[str, float]:
    """Attach the daily-return array so ``pool_metrics`` can chain folds."""
    m = dict(metrics)
    m["_returns"] = equity.pct_change().dropna().to_numpy() if len(equity) > 1 else None
    return m
