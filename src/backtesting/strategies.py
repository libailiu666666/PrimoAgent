from __future__ import annotations

from typing import Any, List, Optional

import backtrader as bt
import pandas as pd

from ..data.contracts import close_time_utc, open_time_utc, validate_causal_order


class PrimoAgentStrategy(bt.Strategy):
    """AI-driven trading strategy using PrimoAgent signals.

    Execution is explicitly a next-bar-open market fill: a signal derived from
    the T close forms ``feature_as_of``/``signal_generated_at`` at T's official
    close, and the market order executes at T+1's open. No cheat-on-close /
    cheat-on-open is used, so the fill never leaks the T close into T itself.
    """

    params: tuple = (
        ("signals_df", None),
        ("printlog", False),
    )

    signals_df: Optional[pd.DataFrame]
    portfolio_values: List[float]
    order_count: int

    def __init__(self) -> None:
        self.signals_df = self.p.signals_df
        self.portfolio_values = []
        self.order_count = 0
        self.execution_log: List[dict] = []
        self.trade_log: List[dict] = []
        self._order_signal_date: dict = {}

    def log(self, txt: str, dt: Any = None) -> None:
        if self.p.printlog:
            dt = dt or self.datas[0].datetime.date(0)
            print(f"{dt.isoformat()}: {txt}")

    def notify_order(self, order: Any) -> None:
        if order.status == order.Completed:
            ref = order.ref
            signal_date = self._order_signal_date.get(ref)
            exec_dt = bt.num2date(order.executed.dt)
            fill_price = order.executed.price
            size = order.executed.size
            direction = "BUY" if order.isbuy() else "SELL"

            if signal_date is not None:
                feature_as_of = close_time_utc(signal_date)
                signal_generated_at = close_time_utc(signal_date)
                execution_at = open_time_utc(exec_dt.date())
                # Fail fast if the T close -> T+1 open chain ever breaks.
                validate_causal_order(feature_as_of, signal_generated_at, execution_at)
                self.execution_log.append({
                    "signal_date": pd.Timestamp(signal_date).date().isoformat(),
                    "feature_as_of": feature_as_of.isoformat(),
                    "signal_generated_at": signal_generated_at.isoformat(),
                    "execution_at": execution_at.isoformat(),
                    "execution_date": exec_dt.date().isoformat(),
                    "direction": direction,
                    "size": int(size),
                    "fill_price": float(fill_price),
                })
            self.log(
                f"   EXEC {direction} {size} @ {fill_price:.2f} on "
                f"{exec_dt.date()} (signal T={signal_date})"
            )
        elif order.status in (order.Canceled, order.Margin, order.Rejected):
            self.log(f"   Order {order.ref} {order.getstatusname()}")

    def notify_trade(self, trade: Any) -> None:
        if trade.isclosed:
            self.trade_log.append({
                "open_date": bt.num2date(trade.dtopen).date().isoformat(),
                "close_date": bt.num2date(trade.dtclose).date().isoformat(),
                "pnl": float(trade.pnl),
                "pnlcomm": float(trade.pnlcomm),
            })
            self.log(f"   TRADE closed pnl={trade.pnl:.2f}")

    def next(self) -> None:
        current_date = self.data.datetime.date(0)
        current_price = self.data.close[0]

        portfolio_value = self.broker.getvalue()
        self.portfolio_values.append(portfolio_value)

        if self.signals_df is None:
            return

        current_signal_row = self.signals_df[
            self.signals_df["date"].dt.date == current_date
        ]

        if current_signal_row.empty:
            return

        signal = current_signal_row.iloc[0]["trading_signal"]
        position_percent = current_signal_row.iloc[0]["position_size"] / 100.0

        self.log(
            f"{current_date} | Signal: {signal} | Price: ${current_price:.2f} | "
            f"Position: {self.position.size} shares"
        )

        if signal == "BUY":
            available_cash = self.broker.getcash()
            target_cash = available_cash * position_percent
            size = int(target_cash / current_price)

            if size >= 1:
                order = self.buy(size=size, exectype=bt.Order.Market)
                self._order_signal_date[order.ref] = current_date
                self.order_count += 1
                self.log(f"   BOUGHT {size} shares @ ${current_price:.2f}")
            else:
                self.log(
                    f"   Not enough cash for 1 share (need ${current_price:.2f}, "
                    f"have ${available_cash:.2f})"
                )

        elif signal == "SELL" and self.position:
            size = int(self.position.size * position_percent)
            if size >= 1:
                order = self.sell(size=size, exectype=bt.Order.Market)
                self._order_signal_date[order.ref] = current_date
                self.order_count += 1
                self.log(f"   SOLD {size} shares @ ${current_price:.2f}")
            else:
                self.log("   Less than 1 share to sell")


class BuyAndHoldStrategy(bt.Strategy):
    """Simple buy and hold strategy for comparison."""

    bought: bool
    portfolio_values: List[float]
    order_count: int

    def __init__(self) -> None:
        self.bought = False
        self.portfolio_values = []
        self.order_count = 0

    def next(self) -> None:
        portfolio_value = self.broker.getvalue()
        self.portfolio_values.append(portfolio_value)

        if not self.bought:
            size = int(self.broker.getcash() / self.data.close[0])

            if size > 0:
                self.buy(size=size)
                self.order_count += 1
                self.bought = True

