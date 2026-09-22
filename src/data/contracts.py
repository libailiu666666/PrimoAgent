"""Frozen point-in-time time contracts (PIT_FROZEN_SPEC v1.1 section 1).

The single causal chain is:

    feature_as_of <= signal_generated_at < execution_at

All four decision-path timestamps are tz-aware UTC; naive datetimes, date
strings, and local times are rejected at the boundary.
"""
from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Tuple
from zoneinfo import ZoneInfo

import pandas as pd

UTC = timezone.utc

# Exchange -> (IANA timezone, official close wall-clock time).
# PIT_FROZEN_SPEC 3.3: daily-bar visibility is judged against the exchange's
# official close moment, converted to UTC via the tz database (never a hardcoded
# offset).
EXCHANGE_CLOSE: dict[str, Tuple[str, time]] = {
    "US": ("America/New_York", time(16, 0)),
}

EXCHANGE_OPEN: dict[str, Tuple[str, time]] = {
    "US": ("America/New_York", time(9, 30)),
}

DEFAULT_EXCHANGE = "US"


class PITTimeError(ValueError):
    """Raised when a decision-path timestamp violates a PIT invariant."""


def ensure_utc(value) -> pd.Timestamp:
    """Normalize a timestamp to tz-aware UTC; reject naive/local datetimes.

    Accepts anything ``pd.Timestamp`` understands. A naive value raises
    ``PITTimeError`` because it has no defined instant on the UTC timeline.
    """
    ts = value if isinstance(value, pd.Timestamp) else pd.Timestamp(value)
    if ts is pd.NaT:
        raise PITTimeError("NaT is not a valid decision-path timestamp")
    if ts.tzinfo is None:
        raise PITTimeError(
            "naive datetime is forbidden in the decision path; "
            "provide a tz-aware UTC timestamp"
        )
    return ts.tz_convert("UTC")


def close_time_utc(trade_date, exchange: str = DEFAULT_EXCHANGE) -> pd.Timestamp:
    """Return the exchange official close moment for ``trade_date`` as UTC.

    A daily bar dated ``trade_date`` is only knowable at/after this instant.
    US equities close at 16:00 America/New_York -> 20:00 UTC (DST) / 21:00 UTC
    (standard); the conversion is delegated to the tz database.
    """
    tz_name, close_t = EXCHANGE_CLOSE[exchange]
    tz = ZoneInfo(tz_name)
    d = pd.Timestamp(trade_date)
    if d.tzinfo is not None:
        d = d.tz_convert(tz_name)
    local_close = datetime.combine(d.date(), close_t, tzinfo=tz)
    return pd.Timestamp(local_close).tz_convert("UTC")


def open_time_utc(trade_date, exchange: str = DEFAULT_EXCHANGE) -> pd.Timestamp:
    """Return the exchange official open moment for ``trade_date`` as UTC.

    US equities open at 09:30 America/New_York. Used to timestamp a T+1 open
    fill precisely enough to validate the causal invariant.
    """
    tz_name, open_t = EXCHANGE_OPEN[exchange]
    tz = ZoneInfo(tz_name)
    d = pd.Timestamp(trade_date)
    if d.tzinfo is not None:
        d = d.tz_convert(tz_name)
    local_open = datetime.combine(d.date(), open_t, tzinfo=tz)
    return pd.Timestamp(local_open).tz_convert("UTC")


def validate_causal_order(
    feature_as_of, signal_generated_at, execution_at
) -> None:
    """Enforce ``feature_as_of <= signal_generated_at < execution_at``.

    Raises ``PITTimeError`` on violation (fail fast at the data entry, never
    silently pass a lookahead trade through).
    """
    f = ensure_utc(feature_as_of)
    s = ensure_utc(signal_generated_at)
    e = ensure_utc(execution_at)
    if not (f <= s < e):
        raise PITTimeError(
            "causal invariant violated: "
            f"feature_as_of={f.isoformat()} <= "
            f"signal_generated_at={s.isoformat()} < "
            f"execution_at={e.isoformat()}"
        )
