"""Adjusted price loading and deterministic data snapshot hashing (Gate 2).

Stocks are read from the Tiingo parquet cache using the *adjusted* OHLC columns
(``adjOpen/adjHigh/adjLow/adjClose/adjVolume``) so splits/dividends do not
corrupt returns or technical indicators. SPY is read from the Yahoo parquet
(``AdjClose`` for returns, raw ``Open`` for the T+1 fill — SPY did not split in
the window).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from ..config.paths import TIINGO_CACHE_DIR, YAHOO_DATA_DIR

PRICE_COLUMNS = ["open", "high", "low", "close", "volume"]


@dataclass
class UniversePrices:
    """Aligned adjusted prices for a set of symbols."""

    prices: Dict[str, pd.DataFrame] = field(default_factory=dict)
    dates: List[pd.Timestamp] = field(default_factory=list)

    @property
    def symbols(self) -> List[str]:
        return sorted(self.prices)

    def snapshot_hash(self) -> str:
        """Deterministic content hash over the whole aligned price panel."""
        h = hashlib.sha256()
        for sym in self.symbols:
            df = self.prices[sym].sort_index()
            h.update(sym.encode("utf-8"))
            h.update(b"\x00")
            for ts, row in df.iterrows():
                h.update(
                    (
                        f"{ts.date().isoformat()}|{row['open']:.6f}|{row['high']:.6f}|"
                        f"{row['low']:.6f}|{row['close']:.6f}|{row['volume']:.0f}\n"
                    ).encode("utf-8")
                )
        return h.hexdigest()


def _finalize(mapped: pd.DataFrame, dates: pd.Series) -> Optional[pd.DataFrame]:
    """Attach a normalized date index to a column-mapped frame and sort it."""
    out = mapped.copy()
    out["_date"] = pd.to_datetime(dates, errors="coerce")
    out = out.dropna(subset=["_date"])
    if out.empty:
        return None
    out = out.set_index(pd.DatetimeIndex(out["_date"].dt.normalize(), name="date"))
    out = out[~out.index.duplicated(keep="first")].sort_index()
    return out[PRICE_COLUMNS]


def _load_tiingo(symbol: str) -> Optional[pd.DataFrame]:
    path = TIINGO_CACHE_DIR / f"{symbol}_ohlcv.parquet"
    if not path.exists():
        return None
    raw = pd.read_parquet(path)
    if raw.empty:
        return None
    mapped = pd.DataFrame(
        {
            "open": raw["adjOpen"],
            "high": raw["adjHigh"],
            "low": raw["adjLow"],
            "close": raw["adjClose"],
            "volume": raw["adjVolume"],
        }
    )
    return _finalize(mapped, raw["date"])


def _load_yahoo(symbol: str) -> Optional[pd.DataFrame]:
    path = YAHOO_DATA_DIR / f"{symbol}_daily.parquet"
    if not path.exists():
        return None
    raw = pd.read_parquet(path)
    if raw.empty:
        return None
    # Yahoo stores raw OHLC plus a single adjusted close. Recover a fully
    # adjusted OHLC panel by scaling raw prices by the AdjClose/Close factor so
    # the T+1 open fill and the mark-to-market close live on the same basis.
    denom = raw["Close"].where(raw["Close"] != 0, 1.0)
    factor = (raw["AdjClose"] / denom).fillna(1.0)
    mapped = pd.DataFrame(
        {
            "open": raw["Open"] * factor,
            "high": raw["High"] * factor,
            "low": raw["Low"] * factor,
            "close": raw["AdjClose"],
            "volume": raw["Volume"],
        }
    )
    return _finalize(mapped, raw["Date"])


def load_universe(tickers: List[str], price_source: str = "tiingo") -> UniversePrices:
    """Load adjusted prices for every ticker and align to the common date set."""
    loader = _load_tiingo if price_source == "tiingo" else _load_yahoo
    prices: Dict[str, pd.DataFrame] = {}
    for t in tickers:
        df = loader(t.upper())
        if df is not None and not df.empty:
            prices[t.upper()] = df

    if not prices:
        return UniversePrices()

    common: set = None
    for df in prices.values():
        idx = set(df.index)
        common = idx if common is None else (common & idx)

    dates = sorted(common)
    aligned = {s: df.loc[dates] for s, df in prices.items()}
    return UniversePrices(prices=aligned, dates=list(dates))


def load_spy(ticker: str = "SPY", source: str = "yahoo") -> Optional[pd.DataFrame]:
    """Load the market benchmark series."""
    if source == "yahoo":
        return _load_yahoo(ticker.upper())
    return _load_tiingo(ticker.upper())
